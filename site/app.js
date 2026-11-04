/* Painel Seguros & Saúde — lê site/data/*.json (gerados pelo robô em etl/) e desenha o dashboard. */
"use strict";

const D = { susep: null, ans: null, status: null };
const graficos = {};
const MESES = ["jan", "fev", "mar", "abr", "mai", "jun", "jul", "ago", "set", "out", "nov", "dez"];

/* ------------------------------------------------------------------ formatação */
const nf1 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 1, minimumFractionDigits: 1 });
const nf0 = new Intl.NumberFormat("pt-BR", { maximumFractionDigits: 0 });
const mesRot = (m) => `${MESES[(m % 100) - 1]}/${String(Math.floor(m / 100)).slice(2)}`;
const mesLongo = (m) => `${MESES[(m % 100) - 1]}/${Math.floor(m / 100)}`;
function reais(v) {
  const a = Math.abs(v);
  if (a >= 1e9) return `R$ ${nf1.format(v / 1e9)} bi`;
  if (a >= 1e6) return `R$ ${nf1.format(v / 1e6)} mi`;
  if (a >= 1e3) return `R$ ${nf1.format(v / 1e3)} mil`;
  return `R$ ${nf0.format(v)}`;
}
function vidas(v) {
  if (Math.abs(v) >= 1e6) return `${nf1.format(v / 1e6)} mi`;
  if (Math.abs(v) >= 1e3) return `${nf1.format(v / 1e3)} mil`;
  return nf0.format(v);
}
const pct = (v) => (v == null || !isFinite(v) ? "—" : `${nf1.format(v * 100)}%`);
const var_ = (a, b) => (b > 0 ? a / b - 1 : null);
function delta(v, sufixo = "") {
  if (v == null || !isFinite(v)) return `<span class="delta">—</span>`;
  const cls = v > 0.0005 ? "up" : v < -0.0005 ? "down" : "";
  const seta = v > 0.0005 ? "▲" : v < -0.0005 ? "▼" : "■";
  return `<span class="delta ${cls}">${seta} ${nf1.format(Math.abs(v * 100))}%${sufixo}</span>`;
}
function deltaPP(v, neutro = false) {
  if (v == null || !isFinite(v)) return "—";
  if (Math.abs(v) < 0.0005) v = 0;
  const cls = neutro ? "" : v > 0 ? "up" : v < 0 ? "down" : "";
  return `<span class="delta ${cls}">${v > 0 ? "+" : ""}${nf1.format(v * 100)} p.p.</span>`;
}
const esc = (s) => String(s ?? "").replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

/* ------------------------------------------------------------------ cores (lidas do CSS: trocam com o tema) */
const css = (n) => Graf.cssv(n);
const L = (name, data, i, extra = {}) => ({ name, data, color: Graf.cor(i), ...extra });
const bi = (v) => `R$ ${nf0.format(v)} bi`, biTip = (v) => `R$ ${nf1.format(v)} bi`;
const mi = (v) => (Math.abs(v) >= 1000 ? `R$ ${(Math.abs(v) >= 10000 ? nf0 : nf1).format(v / 1000)} bi` : `R$ ${nf0.format(v)} mi`);
const miTip = (v) => reais(v * 1e6);
const vmi = (v) => `${nf1.format(v)} mi`;
const pctN = (v) => `${nf0.format(v)}%`, pctTip = (v) => `${nf1.format(v)}%`;

/* ------------------------------------------------------------------ SUSEP: agregações */
function susepMensal(sel) {
  // sel: "SEG" (seguros exceto VGBL), "VGBL" ou código do grupo de ramo
  const out = new Map();
  for (const [m, l, pd, pg, so, dc] of D.susep.serie) {
    if (sel === "SEG" ? l === "VGBL" : l !== sel) continue;
    const o = out.get(m) || { pd: 0, pg: 0, so: 0, dc: 0 };
    o.pd += pd; o.pg += pg; o.so += so; o.dc += dc;
    out.set(m, o);
  }
  return D.susep.meses.map((m) => ({ m, ...(out.get(m) || { pd: 0, pg: 0, so: 0, dc: 0 }) }));
}
function movel(arr, k = 12) {
  // soma móvel de k meses para cada métrica; null enquanto a janela não fecha
  return arr.map((_, i) => {
    if (i < k - 1) return null;
    const j = arr.slice(i - k + 1, i + 1);
    return { m: arr[i].m, pd: soma(j, "pd"), pg: soma(j, "pg"), so: soma(j, "so"), dc: soma(j, "dc") };
  });
}
const soma = (arr, k) => arr.reduce((s, x) => s + (x[k] || 0), 0);
function ltmResumo(sel) {
  const mens = susepMensal(sel);
  const n = mens.length;
  const atual = mens.slice(Math.max(0, n - 12)), ant = mens.slice(Math.max(0, n - 24), Math.max(0, n - 12));
  const r = (a) => ({ pd: soma(a, "pd"), pg: soma(a, "pg"), so: soma(a, "so"), dc: soma(a, "dc") });
  return { atual: r(atual), ant: r(ant), temAnt: ant.length === 12 };
}
const nomeLinha = (l) => (l === "SEG" ? "Seguros (exceto VGBL)" : D.susep.linhas[l] || l);

/* ------------------------------------------------------------------ ANS: agregações */
function ansMensal(cob, chave) {
  // retorna {m -> {categoria -> ativos}} para a dimensão pedida (contr | mod | null)
  const idx = { contr: 2, mod: 3 }[chave];
  const out = new Map();
  for (const r of D.ans.serie) {
    if (cob && r[1] !== cob) continue;
    const cat = idx ? r[idx] : "total";
    const o = out.get(r[0]) || {};
    o[cat] = (o[cat] || 0) + r[4];
    out.set(r[0], o);
  }
  return out;
}

/* ------------------------------------------------------------------ componentes */
function tile(rot, val, det = "") {
  return `<div class="tile"><div class="rot">${rot}</div><div class="val">${val}</div><div class="det">${det}</div></div>`;
}
function tabela(el, cab, linhas, opts = {}) {
  const t = document.getElementById(el);
  t.innerHTML = `<thead><tr>${cab.map((c) => `<th>${c}</th>`).join("")}</tr></thead><tbody>${linhas
    .map((l) => `<tr${l.attrs || ""}>${l.cells.map((c) => `<td>${c}</td>`).join("")}</tr>`)
    .join("")}</tbody>`;
  if (opts.onClick) t.querySelectorAll("tbody tr[data-k]").forEach((tr) => tr.addEventListener("click", () => opts.onClick(tr.dataset.k)));
}
const barra = (share, max) => `<span class="barra" style="width:${Math.max(2, (share / max) * 80)}px"></span>`;

/* ================================================================== VISÃO GERAL */
function renderGeral() {
  const tiles = [];
  if (D.susep) {
    const s = ltmResumo("SEG"), v = ltmResumo("VGBL");
    const per = `12 meses até ${mesLongo(D.susep.ultima)}`;
    tiles.push(tile("Prêmios de seguros (ex-VGBL)", reais(s.atual.pd), `${delta(s.temAnt ? var_(s.atual.pd, s.ant.pd) : null)} a/a · ${per}`));
    tiles.push(tile("Sinistralidade (ex-VGBL)", pct(s.atual.so / s.atual.pg), `${per} · antes ${pct(s.ant.so / s.ant.pg)}`));
    if (D.susep.linhas.VGBL) tiles.push(tile("Prêmios VGBL", reais(v.atual.pd), `${delta(v.temAnt ? var_(v.atual.pd, v.ant.pd) : null)} a/a · ${per}`));
    if (D.susep.pgbl && D.susep.pgbl.length >= 24) {
      const p = D.susep.pgbl.map((x) => x.v), n = p.length;
      const a = p.slice(n - 12).reduce((x, y) => x + y, 0), b = p.slice(n - 24, n - 12).reduce((x, y) => x + y, 0);
      tiles.push(tile("Contribuições PGBL", reais(a), `${delta(var_(a, b))} a/a · ${per}`));
    }
  }
  if (D.ans) {
    for (const [cob, rot] of [["MH", "Beneficiários médico-hospitalares"], ["OD", "Beneficiários odontológicos"]]) {
      const m = ansMensal(cob, null);
      const a = m.get(D.ans.ultima)?.total || 0, b = m.get(D.ans.comparacao)?.total || 0;
      tiles.push(tile(rot, vidas(a), `${delta(var_(a, b))} vs ${mesLongo(D.ans.comparacao)} · ${mesLongo(D.ans.ultima)}`));
    }
  }
  document.getElementById("tiles-geral").innerHTML = tiles.join("");
  document.getElementById("g-geral-premios").closest(".card").hidden = !D.susep;
  document.getElementById("g-geral-benef").closest(".card").hidden = !D.ans;

  if (D.susep) {
    const seg = movel(susepMensal("SEG")), vg = movel(susepMensal("VGBL"));
    const meses = D.susep.meses;
    const sets = [L("Seguros (ex-VGBL)", seg.map((x) => (x ? x.pd / 1e9 : null)), 0)];
    if (D.susep.linhas.VGBL) sets.push(L("VGBL", vg.map((x) => (x ? x.pd / 1e9 : null)), 1));
    Graf.render("g-geral-premios", "xy", { labels: meses.map(mesRot), series: sets, fmt: bi, fmtTip: biTip,
      tituloTip: (i) => `12 meses até ${mesLongo(meses[i])}` });
  }
  if (D.ans) {
    const mh = ansMensal("MH", null), od = ansMensal("OD", null);
    Graf.render("g-geral-benef", "xy", { labels: D.ans.meses.map(mesRot), fmt: vmi, series: [
      L("Médico-hospitalar", D.ans.meses.map((m) => (mh.get(m)?.total || 0) / 1e6), 0),
      L("Odontológico", D.ans.meses.map((m) => (od.get(m)?.total || 0) / 1e6), 1),
    ], tituloTip: (i) => mesLongo(D.ans.meses[i]) });
  }
}

/* ================================================================== SEGUROS */
let selSeg = "SEG";
function renderSeguros() {
  if (!D.susep) return;
  const sel = document.getElementById("f-seg-linha");
  if (!sel.options.length) {
    const ops = [["SEG", "Seguros (exceto VGBL)"], ...Object.entries(D.susep.linhas).filter(([k]) => k !== "VGBL").sort((a, b) => a[1].localeCompare(b[1])), ["VGBL", "VGBL"]];
    sel.innerHTML = ops.filter(([k]) => k === "SEG" || D.susep.linhas[k]).map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join("");
    sel.addEventListener("change", () => { selSeg = sel.value; renderSeguros(); });
  }
  sel.value = selSeg;
  document.getElementById("seg-periodo").textContent = `Dados até ${mesLongo(D.susep.ultima)}`;

  const r = ltmResumo(selSeg), tot = ltmResumo("SEG");
  const per = `12 meses até ${mesLongo(D.susep.ultima)}`;
  document.getElementById("tiles-seg").innerHTML = [
    tile("Prêmio emitido", reais(r.atual.pd), `${delta(r.temAnt ? var_(r.atual.pd, r.ant.pd) : null)} a/a · ${per}`),
    tile("Prêmio ganho", reais(r.atual.pg), `${delta(r.temAnt ? var_(r.atual.pg, r.ant.pg) : null)} a/a`),
    tile("Sinistralidade", pct(r.atual.so / r.atual.pg), `${deltaPP(r.atual.so / r.atual.pg - r.ant.so / r.ant.pg, true)} vs 12m anteriores`),
    tile("Comissionamento", pct(r.atual.dc / r.atual.pg), `${deltaPP(r.atual.dc / r.atual.pg - r.ant.dc / r.ant.pg, true)} vs 12m anteriores`),
    selSeg !== "SEG" && selSeg !== "VGBL" ? tile("Peso no mercado (ex-VGBL)", pct(r.atual.pd / tot.atual.pd), "do prêmio emitido em 12 meses") : "",
  ].join("");

  const mens = susepMensal(selSeg), mov = movel(mens);
  // últimos 60 meses para as barras continuarem legíveis
  const ini = Math.max(0, mens.length - 60);
  const rotM = mens.slice(ini).map((x) => mesRot(x.m)), tipM = (i) => mesLongo(mens[ini + i].m);
  Graf.render("g-seg-mensal", "xy", { labels: rotM, fmt: mi, fmtTip: miTip, tituloTip: tipM, series: [
    L("Prêmio no mês", mens.slice(ini).map((x) => x.pd / 1e6), 0, { type: "bar" }),
    L("Média móvel 12m", mov.slice(ini).map((x) => (x ? x.pd / 12 / 1e6 : null)), 1),
  ] });
  Graf.render("g-seg-indices", "xy", { labels: rotM, fmt: pctN, fmtTip: pctTip, tituloTip: (i) => `12 meses até ${tipM(i)}`, series: [
    L("Sinistralidade", mov.slice(ini).map((x) => (x && x.pg > 0 ? (x.so / x.pg) * 100 : null)), 0),
    L("Comissionamento", mov.slice(ini).map((x) => (x && x.pg > 0 ? (x.dc / x.pg) * 100 : null)), 1),
  ] });

  // tabela de grupos
  // participação medida sobre seguros ex-VGBL; VGBL aparece por último, à parte
  const grupos = Object.keys(D.susep.linhas).map((k) => ({ k, ...ltmResumo(k) }))
    .sort((a, b) => (a.k === "VGBL") - (b.k === "VGBL") || b.atual.pd - a.atual.pd);
  const totalTudo = grupos.filter((g) => g.k !== "VGBL").reduce((s, g) => s + g.atual.pd, 0) || 1;
  const max = Math.max(...grupos.filter((g) => g.k !== "VGBL").map((g) => g.atual.pd / totalTudo));
  tabela("t-seg-grupos", ["Grupo de ramos", "Prêmio emitido", "Var. a/a", "Part. (ex-VGBL)", "Sinistralidade", "Comissionamento"],
    grupos.filter((g) => g.atual.pd > 0).map((g) => ({
      attrs: ` data-k="${g.k}" class="clicavel${g.k === selSeg ? " ativo" : ""}"`,
      cells: [esc(nomeLinha(g.k)), reais(g.atual.pd), delta(g.temAnt ? var_(g.atual.pd, g.ant.pd) : null),
        g.k === "VGBL" ? "—" : `${pct(g.atual.pd / totalTudo)}${barra(g.atual.pd / totalTudo, max)}`, pct(g.atual.so / g.atual.pg), pct(g.atual.dc / g.atual.pg)],
    })), { onClick: (k) => { selSeg = k; renderSeguros(); window.scrollTo({ top: 0, behavior: "smooth" }); } });

  // tabela de ramos
  const ramos = D.susep.ramos.filter((x) => selSeg === "SEG" ? !x.vgbl : selSeg === "VGBL" ? x.vgbl : x.gr === selSeg && !x.vgbl).slice(0, 40);
  const totR = ramos.reduce((s, x) => s + x.pd, 0) || 1;
  document.getElementById("t-seg-ramos-tit").textContent = `Principais ramos — ${nomeLinha(selSeg)}, últimos 12 meses`;
  tabela("t-seg-ramos", ["Ramo", "Prêmio emitido", "Var. a/a", "Part. no segmento", "Sinistralidade", "Comissionamento"],
    ramos.map((x) => ({ cells: [`${esc(x.nome)} <span class="filtro-info">${x.cod}</span>`, reais(x.pd), delta(var_(x.pd, x.pd_ant)), pct(x.pd / totR), pct(x.sin), pct(x.com)] })));
}

/* ================================================================== SAÚDE */
function renderSaude() {
  if (!D.ans) return;
  const cob = document.getElementById("f-ans-cob").value;
  const { ultima, comparacao, meses } = D.ans;
  document.getElementById("ans-periodo").textContent = `Dados até ${mesLongo(ultima)} · comparação com ${mesLongo(comparacao)}`;

  const tot = ansMensal(cob, null);
  const a = tot.get(ultima)?.total || 0, b = tot.get(comparacao)?.total || 0;
  const contr = ansMensal(cob, "contr");
  const ca = contr.get(ultima) || {}, cb = contr.get(comparacao) || {};
  const cats = Object.keys(ca).sort((x, y) => ca[y] - ca[x]);
  const tiles = [tile("Beneficiários ativos", vidas(a), `${delta(var_(a, b))} vs ${mesLongo(comparacao)} · ${nf0.format(a - b)} vidas`)];
  for (const c of cats.slice(0, 3)) tiles.push(tile(esc(c), vidas(ca[c]), `${pct(ca[c] / a)} do total · ${delta(var_(ca[c], cb[c] || 0))}`));
  document.getElementById("tiles-ans").innerHTML = tiles.join("");

  // séries por contratação: as 4 maiores + "Outros" (cores fixas por categoria, nunca por posição)
  const ordemFixa = ["Coletivo empresarial", "Coletivo por adesão", "Individual ou familiar"];
  const principais = [...ordemFixa.filter((c) => cats.includes(c)), ...cats.filter((c) => !ordemFixa.includes(c))].slice(0, 4);
  const sets = principais.map((c, i) => L(c, meses.map((m) => (contr.get(m)?.[c] || 0) / 1e6), i));
  const outros = meses.map((m) => Object.entries(contr.get(m) || {}).filter(([k]) => !principais.includes(k)).reduce((s, [, v]) => s + v, 0) / 1e6);
  if (outros.some((v) => v > 0)) sets.push({ name: "Outros / não informado", data: outros, color: css("--muted"), dash: true });
  Graf.render("g-ans-contr", "xy", { labels: meses.map(mesRot), series: sets, fmt: vmi, tituloTip: (i) => mesLongo(meses[i]) });

  // UF
  const ufs = D.ans.uf.filter((r) => r[1] === cob && r[0] !== "XX").sort((x, y) => y[2] - x[2]);
  const top = ufs.slice(0, 12);
  Graf.render("g-ans-uf", "hbar", { labels: top.map((r) => r[0]), fmt: vmi,
    series: [L("Beneficiários", top.map((r) => r[2] / 1e6), 0)],
    extraTip: (i) => `<div class="g-sub">${delta(var_(top[i][2], top[i][3]))} vs ${mesRot(comparacao)}</div>` });

  const totUF = ufs.reduce((s, r) => s + r[2], 0) || 1;
  tabela("t-ans-uf", ["UF", "Beneficiários", `Var. vs ${mesRot(comparacao)}`, "Participação"],
    ufs.map((r) => ({ cells: [r[0], nf0.format(r[2]), delta(var_(r[2], r[3])), pct(r[2] / totUF)] })));

  // modalidade
  const mod = ansMensal(cob, "mod");
  const ma = mod.get(ultima) || {}, mb = mod.get(comparacao) || {};
  const mods = Object.keys(ma).sort((x, y) => ma[y] - ma[x]);
  const maxM = Math.max(...mods.map((k) => ma[k] / a));
  tabela("t-ans-mod", ["Modalidade", "Beneficiários", `Var. vs ${mesRot(comparacao)}`, "Participação", "Var. participação"],
    mods.map((k) => ({ cells: [esc(k), nf0.format(ma[k]), delta(var_(ma[k], mb[k] || 0)), `${pct(ma[k] / a)}${barra(ma[k] / a, maxM)}`, deltaPP(ma[k] / a - (mb[k] || 0) / (b || 1))] })));
}

/* ================================================================== CONCENTRAÇÃO */
function hhiLeitura(h) {
  if (h < 1500) return "pouco concentrado";
  if (h < 2500) return "moderadamente concentrado";
  return "altamente concentrado";
}
function renderConc() {
  const sel = document.getElementById("f-conc");
  if (!sel.options.length) {
    const ops = [];
    if (D.susep) {
      ops.push(["S:SEG", "Seguros (exceto VGBL)"]);
      Object.entries(D.susep.linhas).filter(([k]) => k !== "VGBL" && D.susep.concentracao[k]).sort((a, b) => a[1].localeCompare(b[1])).forEach(([k, n]) => ops.push([`S:${k}`, `Seguros · ${n}`]));
      if (D.susep.concentracao.VGBL) ops.push(["S:VGBL", "VGBL"]);
    }
    if (D.ans) {
      if (D.ans.concentracao.MH) ops.push(["A:MH", "Saúde · médico-hospitalar"]);
      if (D.ans.concentracao.OD) ops.push(["A:OD", "Saúde · odontológico"]);
    }
    sel.innerHTML = ops.map(([k, n]) => `<option value="${k}">${esc(n)}</option>`).join("");
    sel.addEventListener("change", renderConc);
  }
  if (!sel.value) return;
  const [fonte, chave] = sel.value.split(":");
  const isS = fonte === "S";
  const c = isS ? D.susep.concentracao[chave] : D.ans.concentracao[chave];
  if (!c) return;
  const fmt = isS ? reais : vidas;
  const quem = isS ? "grupos econômicos" : "operadoras";
  const periodo = isS ? `prêmio emitido em 12 meses até ${mesLongo(D.susep.ultima)}` : `beneficiários em ${mesLongo(D.ans.ultima)}`;
  const comp = isS ? "12 meses anteriores" : mesLongo(D.ans.comparacao);
  document.getElementById("conc-periodo").textContent = `Base: ${periodo}`;

  document.getElementById("tiles-conc").innerHTML = [
    tile("Tamanho do mercado", fmt(c.total), `${delta(var_(c.total, c.total_ant))} vs ${comp}`),
    tile("Índice HHI", nf0.format(c.hhi), hhiLeitura(c.hhi)),
    tile("Top 5 (CR5)", pct(c.cr5), `Top 10: ${pct(c.cr10)}`),
    tile(`Nº de ${quem}`, nf0.format(c.n), "com produção no período"),
  ].join("");

  document.getElementById("g-conc-tit").textContent = `Participação dos ${c.top.length} maiores ${quem}`;
  document.getElementById("g-conc-nota").textContent = `% do ${isS ? "prêmio emitido" : "total de beneficiários"} — atual x ${comp}`;
  const rot = c.top.map((t) => (t.nome.length > 34 ? t.nome.slice(0, 32) + "…" : t.nome));
  Graf.render("g-conc", "hbar", { labels: rot, fmt: pctN, fmtTip: pctTip, series: [
    L("Atual", c.top.map((t) => t.share * 100), 0),
    { name: comp.charAt(0).toUpperCase() + comp.slice(1), data: c.top.map((t) => (t.share_ant ?? 0) * 100), color: css("--axis") },
  ] });

  tabela("t-conc", ["#", isS ? "Grupo econômico" : "Operadora", ...(isS ? [] : ["Modalidade"]), isS ? "Prêmio emitido" : "Beneficiários", `Var. vs ${comp}`, "Participação", "Var. participação"],
    c.top.map((t, i) => ({ cells: [String(i + 1), esc(t.nome), ...(isS ? [] : [esc(t.mod || "")]), fmt(t.v), delta(var_(t.v, t.v_ant)), pct(t.share), deltaPP(t.share_ant == null ? null : t.share - t.share_ant)] })));

}

/* ================================================================== navegação e carga */
const renders = { geral: renderGeral, seguros: renderSeguros, saude: renderSaude, conc: renderConc };
let abaAtual = "geral";
function abrir(aba) {
  abaAtual = aba;
  document.querySelectorAll(".abas button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.aba === aba)));
  document.querySelectorAll(".aba").forEach((s) => { s.hidden = s.id !== `aba-${aba}`; });
  history.replaceState(null, "", `#${aba}`);
  try { renders[aba](); } catch (e) { console.error(e); }
}

async function carregar(nome) {
  try {
    const r = await fetch(`data/${nome}.json?v=${Date.now() / 36e5 | 0}`);
    return r.ok ? await r.json() : null;
  } catch { return null; }
}

function rodape() {
  const s = D.status || {};
  const quando = (iso) => iso ? new Date(iso).toLocaleString("pt-BR", { dateStyle: "short", timeStyle: "short" }) : "—";
  const parte = (k, nome, dados) => {
    const st = s[k];
    if (!st) return `${nome}: ${dados ? `dados até ${mesLongo(dados.ultima)}` : "sem dados"}`;
    return st.ok ? `${nome}: dados até ${dados ? mesLongo(dados.ultima) : "—"} (verificado em ${quando(st.em)})`
      : `${nome}: última tentativa falhou em ${quando(st.em)} — exibindo os últimos dados válidos${dados ? ` (até ${mesLongo(dados.ultima)})` : ""}`;
  };
  document.getElementById("status").textContent = `${parte("susep", "SUSEP", D.susep)} · ${parte("ans", "ANS", D.ans)}`;
}

async function iniciar() {
  [D.susep, D.ans, D.status] = await Promise.all([carregar("susep"), carregar("ans"), carregar("status")]);
  const aviso = document.getElementById("aviso");
  const faltam = [!D.susep && "SUSEP", !D.ans && "ANS"].filter(Boolean);
  if (faltam.length) {
    aviso.hidden = false;
    aviso.innerHTML = faltam.length === 2
      ? "<strong>Ainda não há dados.</strong> A primeira atualização roda automaticamente no GitHub (aba <em>Actions</em> → “Atualizar dados”). Ela pode levar algumas horas na primeira vez."
      : `<strong>Dados de ${faltam[0]} ainda indisponíveis.</strong> Eles entram na próxima atualização automática.`;
  }
  if (!D.susep) { document.querySelector('[data-aba="seguros"]').hidden = true; }
  if (!D.ans) { document.querySelector('[data-aba="saude"]').hidden = true; }
  if (!D.susep && !D.ans) { document.querySelector('[data-aba="conc"]').hidden = true; }
  const partes = [];
  if (D.susep) partes.push(`SUSEP até ${mesLongo(D.susep.ultima)}`);
  if (D.ans) partes.push(`ANS até ${mesLongo(D.ans.ultima)}`);
  if (partes.length) document.getElementById("sub").textContent = `Mercado segurador e saúde suplementar · ${partes.join(" · ")}`;
  rodape();

  document.querySelectorAll(".abas button").forEach((b) => b.addEventListener("click", () => abrir(b.dataset.aba)));
  document.getElementById("f-ans-cob").addEventListener("change", renderSaude);
  window.addEventListener("hashchange", () => { const h = location.hash.slice(1); if (renders[h] && h !== abaAtual) abrir(h); });
  matchMedia("(prefers-color-scheme: dark)").addEventListener("change", () => renders[abaAtual]());
  const inicial = location.hash.slice(1);
  abrir(renders[inicial] && !document.querySelector(`[data-aba="${inicial}"]`).hidden ? inicial : "geral");
}

document.addEventListener("DOMContentLoaded", iniciar);
