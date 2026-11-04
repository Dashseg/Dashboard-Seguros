/* Gráficos SVG leves, sem dependências: linhas, barras verticais (com linha opcional) e barras horizontais.
   Cada gráfico se redesenha ao mudar o tamanho do contêiner e lê as cores do CSS (tema claro/escuro). */
"use strict";

const Graf = (() => {
  const NS = "http://www.w3.org/2000/svg";
  const cssv = (n) => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
  const ativos = new Map(); // id -> {spec, ro}

  function el(tag, attrs = {}, pai) {
    const e = document.createElementNS(NS, tag);
    for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
    if (pai) pai.appendChild(e);
    return e;
  }

  // "bons" valores de eixo
  function ticks(min, max, n = 5) {
    if (!(max > min)) { max = min + 1; }
    const passo0 = (max - min) / n, mag = 10 ** Math.floor(Math.log10(passo0));
    const passo = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((p) => p >= passo0) || mag * 10;
    const ini = Math.floor(min / passo) * passo, fim = Math.ceil(max / passo) * passo;
    const out = [];
    for (let v = ini; v <= fim + passo / 2; v += passo) out.push(+v.toFixed(10));
    return out;
  }

  function preparar(id, series) {
    const host = document.getElementById(id);
    if (!host) return null;
    host.innerHTML = "";
    host.classList.add("gw");
    const area = document.createElement("div");
    area.className = "g-area";
    host.appendChild(area);
    legenda(host, series); // antes de medir: a legenda ocupa parte da altura
    const tip = document.createElement("div");
    tip.className = "g-tip";
    tip.hidden = true;
    area.appendChild(tip);
    return { host, area, tip, w: area.clientWidth || 600, h: area.clientHeight || 280 };
  }

  function legenda(host, series) {
    if (series.length < 2) return;
    const lg = document.createElement("div");
    lg.className = "g-leg";
    lg.innerHTML = series.map((s) => `<span><i style="background:${s.color}${s.dash ? ";opacity:.75" : ""}"></i>${s.name}</span>`).join("");
    host.appendChild(lg);
  }

  function mostrarTip(ctx, x, y, html) {
    const { tip, w } = ctx;
    tip.innerHTML = html;
    tip.hidden = false;
    const tw = tip.offsetWidth, th = tip.offsetHeight;
    let left = x + 14;
    if (left + tw > w) left = x - tw - 14;
    tip.style.left = `${Math.max(0, left)}px`;
    tip.style.top = `${Math.max(0, Math.min(y - th / 2, ctx.h - th))}px`;
  }

  /* --------------------------------------------------------------- eixos XY (vertical) */
  function eixosXY(svg, ctx, labels, vmin, vmax, fmt, margemEsq) {
    const ink = cssv("--muted"), grid = cssv("--grid"), axis = cssv("--axis");
    const t = ticks(vmin, vmax);
    const m = { l: margemEsq, r: 12, t: 10, b: 26 };
    const pw = ctx.w - m.l - m.r, ph = ctx.h - m.t - m.b;
    const y = (v) => m.t + ph - ((v - t[0]) / (t[t.length - 1] - t[0])) * ph;
    for (const v of t) {
      el("line", { x1: m.l, x2: m.l + pw, y1: y(v), y2: y(v), stroke: grid, "stroke-width": 1 }, svg);
      const tx = el("text", { x: m.l - 8, y: y(v) + 4, "text-anchor": "end", fill: ink, "font-size": 11.5 }, svg);
      tx.textContent = fmt(v);
    }
    el("line", { x1: m.l, x2: m.l + pw, y1: y(t[0]), y2: y(t[0]), stroke: axis, "stroke-width": 1 }, svg);
    // rótulos do eixo x espaçados para não colidir
    const n = labels.length, cada = Math.max(1, Math.ceil((n * 46) / pw));
    const x = (i) => m.l + (n <= 1 ? pw / 2 : (i + 0.5) * (pw / n));
    for (let i = n - 1; i >= 0; i -= cada) {
      const tx = el("text", { x: x(i), y: ctx.h - 8, "text-anchor": "middle", fill: ink, "font-size": 11.5 }, svg);
      tx.textContent = labels[i];
    }
    return { m, pw, ph, y, x, t };
  }

  function larguraRotulos(valores, fmt) {
    const maior = Math.max(...valores.map((v) => fmt(v).length));
    return Math.min(90, 14 + maior * 6.6);
  }

  /* --------------------------------------------------------------- linhas e barras verticais */
  function xy(id, spec) {
    const ctx = preparar(id, spec.series);
    if (!ctx) return;
    const { labels, series, fmt, fmtTip = fmt } = spec;
    const bars = series.filter((s) => s.type === "bar"), lines = series.filter((s) => s.type !== "bar");
    const todos = series.flatMap((s) => s.data).filter((v) => v != null && isFinite(v));
    let vmin = Math.min(...todos), vmax = Math.max(...todos);
    if (spec.zero !== false || bars.length) vmin = Math.min(0, vmin);
    else { const pad = (vmax - vmin) * 0.1 || Math.abs(vmax) * 0.1 || 1; vmin -= pad; vmax += pad; }
    const svg = el("svg", { width: ctx.w, height: ctx.h, role: "img", "aria-label": spec.titulo || "gráfico" });
    ctx.area.insertBefore(svg, ctx.tip);
    const ax = eixosXY(svg, ctx, labels, vmin, vmax, fmt, larguraRotulos(ticks(vmin, vmax), fmt));
    const n = labels.length, slot = ax.pw / Math.max(1, n);
    const surface = cssv("--surface");

    // barras: largura proporcional ao slot, ponta arredondada de 3px ancorada na base
    bars.forEach((s, bi) => {
      const bw = Math.max(1, (slot * 0.78) / bars.length - (bars.length > 1 ? 2 : 0));
      s.data.forEach((v, i) => {
        if (v == null) return;
        const x0 = ax.x(i) - (slot * 0.78) / 2 + bi * (bw + 2), y0 = ax.y(Math.max(0, v)), y1 = ax.y(Math.min(0, v));
        const h = Math.max(0.5, y1 - y0), r = Math.min(3, bw / 2, h);
        const d = `M${x0},${y1}V${y0 + r}Q${x0},${y0} ${x0 + r},${y0}H${x0 + bw - r}Q${x0 + bw},${y0} ${x0 + bw},${y0 + r}V${y1}Z`;
        el("path", { d, fill: s.color }, svg);
      });
    });
    // linhas (2px), quebrando nos nulos
    lines.forEach((s) => {
      let d = "", aberto = false;
      s.data.forEach((v, i) => {
        if (v == null || !isFinite(v)) { aberto = false; return; }
        d += `${aberto ? "L" : "M"}${ax.x(i).toFixed(1)},${ax.y(v).toFixed(1)}`;
        aberto = true;
      });
      el("path", { d, fill: "none", stroke: s.color, "stroke-width": 2, "stroke-linejoin": "round", "stroke-linecap": "round", ...(s.dash ? { "stroke-dasharray": "5 4" } : {}) }, svg);
    });

    // camada de hover: guia vertical + pontos + tooltip
    const guia = el("line", { y1: ax.m.t, y2: ax.m.t + ax.ph, stroke: cssv("--axis"), "stroke-width": 1, visibility: "hidden" }, svg);
    const pontos = lines.map((s) => el("circle", { r: 4, fill: s.color, stroke: surface, "stroke-width": 2, visibility: "hidden" }, svg));
    const hit = el("rect", { x: ax.m.l, y: ax.m.t, width: ax.pw, height: ax.ph, fill: "transparent" }, svg);
    const mover = (ev) => {
      const r = svg.getBoundingClientRect();
      const px = (ev.touches ? ev.touches[0].clientX : ev.clientX) - r.left;
      const i = Math.max(0, Math.min(n - 1, Math.floor((px - ax.m.l) / slot)));
      guia.setAttribute("x1", ax.x(i)); guia.setAttribute("x2", ax.x(i)); guia.setAttribute("visibility", "visible");
      lines.forEach((s, k) => {
        const v = s.data[i];
        if (v == null) { pontos[k].setAttribute("visibility", "hidden"); return; }
        pontos[k].setAttribute("cx", ax.x(i)); pontos[k].setAttribute("cy", ax.y(v)); pontos[k].setAttribute("visibility", "visible");
      });
      const linhas = series.map((s) => `<div><i style="background:${s.color}"></i>${s.name}<b>${s.data[i] == null ? "—" : fmtTip(s.data[i])}</b></div>`).join("");
      mostrarTip(ctx, ax.x(i), ax.m.t + ax.ph / 3, `<div class="g-tt">${spec.tituloTip ? spec.tituloTip(i) : labels[i]}</div>${linhas}`);
    };
    const sair = () => { guia.setAttribute("visibility", "hidden"); pontos.forEach((p) => p.setAttribute("visibility", "hidden")); ctx.tip.hidden = true; };
    hit.addEventListener("mousemove", mover); hit.addEventListener("touchstart", mover, { passive: true });
    hit.addEventListener("mouseleave", sair);
  }

  /* --------------------------------------------------------------- barras horizontais (agrupadas) */
  function hbar(id, spec) {
    const ctx = preparar(id, spec.series);
    if (!ctx) return;
    const { labels, series, fmt, fmtTip = fmt } = spec;
    const ink = cssv("--muted"), ink2 = cssv("--ink-2"), grid = cssv("--grid"), axis = cssv("--axis");
    const todos = series.flatMap((s) => s.data).filter((v) => v != null);
    const t = ticks(0, Math.max(...todos, 0));
    const largRot = Math.min(ctx.w * 0.42, 12 + Math.max(...labels.map((l) => l.length)) * 6.4);
    const m = { l: largRot, r: 16, t: 4, b: 22 };
    const pw = ctx.w - m.l - m.r, ph = ctx.h - m.t - m.b;
    const svg = el("svg", { width: ctx.w, height: ctx.h, role: "img", "aria-label": spec.titulo || "gráfico" });
    ctx.area.insertBefore(svg, ctx.tip);
    const x = (v) => m.l + (v / t[t.length - 1]) * pw;
    for (const v of t) {
      el("line", { x1: x(v), x2: x(v), y1: m.t, y2: m.t + ph, stroke: grid }, svg);
      const tx = el("text", { x: x(v), y: ctx.h - 6, "text-anchor": "middle", fill: ink, "font-size": 11.5 }, svg);
      tx.textContent = fmt(v);
    }
    const n = labels.length, slot = ph / n, ns = series.length;
    const bh = Math.max(3, Math.min(18, (slot * 0.72) / ns - (ns > 1 ? 2 : 0)));
    labels.forEach((lab, i) => {
      const yc = m.t + slot * (i + 0.5);
      const tx = el("text", { x: m.l - 8, y: yc + 4, "text-anchor": "end", fill: ink2, "font-size": 12 }, svg);
      tx.textContent = lab.length > 40 ? lab.slice(0, 38) + "…" : lab;
      series.forEach((s, k) => {
        const v = s.data[i];
        if (v == null) return;
        const y0 = yc - (ns * bh + (ns - 1) * 2) / 2 + k * (bh + 2), w = Math.max(0.5, x(v) - m.l), r = Math.min(3, bh / 2, w);
        el("path", { d: `M${m.l},${y0}H${m.l + w - r}Q${m.l + w},${y0} ${m.l + w},${y0 + r}V${y0 + bh - r}Q${m.l + w},${y0 + bh} ${m.l + w - r},${y0 + bh}H${m.l}Z`, fill: s.color }, svg);
      });
    });
    el("line", { x1: m.l, x2: m.l, y1: m.t, y2: m.t + ph, stroke: axis }, svg);
    const realce = el("rect", { x: 0, width: ctx.w, height: slot, fill: cssv("--hover"), visibility: "hidden" }, svg);
    svg.insertBefore(realce, svg.firstChild);
    const hit = el("rect", { x: 0, y: m.t, width: ctx.w, height: ph, fill: "transparent" }, svg);
    const mover = (ev) => {
      const r = svg.getBoundingClientRect();
      const py = (ev.touches ? ev.touches[0].clientY : ev.clientY) - r.top;
      const i = Math.max(0, Math.min(n - 1, Math.floor((py - m.t) / slot)));
      realce.setAttribute("y", m.t + i * slot); realce.setAttribute("visibility", "visible");
      const linhas = series.map((s) => `<div><i style="background:${s.color}"></i>${s.name}<b>${s.data[i] == null ? "—" : fmtTip(s.data[i], i)}</b></div>`).join("");
      mostrarTip(ctx, Math.min(ctx.w - 20, x(Math.max(...series.map((s) => s.data[i] || 0)))), m.t + slot * (i + 0.5), `<div class="g-tt">${labels[i]}</div>${linhas}${spec.extraTip ? spec.extraTip(i) : ""}`);
    };
    hit.addEventListener("mousemove", mover); hit.addEventListener("touchstart", mover, { passive: true });
    hit.addEventListener("mouseleave", () => { realce.setAttribute("visibility", "hidden"); ctx.tip.hidden = true; });
  }

  function render(id, tipo, spec) {
    const fn = tipo === "hbar" ? hbar : xy;
    fn(id, spec);
    // redesenha ao redimensionar (uma vez por quadro)
    const host = document.getElementById(id);
    if (!host) return;
    const reg = ativos.get(id);
    if (reg) reg.ro.disconnect();
    let pendente = false, largura = host.clientWidth;
    const ro = new ResizeObserver(() => {
      if (pendente || Math.abs(host.clientWidth - largura) < 2) return;
      pendente = true;
      requestAnimationFrame(() => { pendente = false; largura = host.clientWidth; fn(id, spec); });
    });
    ro.observe(host);
    ativos.set(id, { ro });
  }

  return { render, cor: (i) => cssv(`--s${(i % 8) + 1}`), cssv };
})();
