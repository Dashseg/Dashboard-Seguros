"""SUSEP — Sistema de Estatísticas (SES), base completa.

Fonte: https://www2.susep.gov.br/menuestatistica/ses/  (atualizada semanalmente)
Arquivos usados de dentro do BaseCompleta.zip:
  Ses_seguros.csv      fatos mensais por empresa (coenti) x ramo (coramo)
  Ses_cias.csv         empresas e grupos econômicos (coenti, noenti, cogrupo, nogrupo)
  Ses_ramos.csv        nomes dos ramos (coramo, noramo)
  Ses_gruposramos.csv  nomes dos grupos de ramos (GRACODIGO, GRANOME)
  Ses_grupos_economicos.csv  grupo econômico de cada empresa, mês a mês
  Ses_Contrib_Benef.csv      contribuições de previdência por tipo (VGBL, PGBL, tradicional)
  ses_cap_uf.csv             receitas de capitalização

Métricas:
  prêmio emitido  = premio_direto
  prêmio ganho    = premio_ganho
  sinistralidade  = sinistro_ocorrido / premio_ganho
  comissionamento = desp_com / premio_ganho
"""
from __future__ import annotations

import os
import re
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from common import DOWNLOAD_DIR, abrir_texto, detectar_separador, download, env_int, log, norm, salvar_json

URLS = [
    "https://www2.susep.gov.br/download/estatisticas/BaseCompleta.zip",
    "https://www2.susep.gov.br/redarq.asp?arq=BaseCompleta%2ezip",
    "https://www2.susep.gov.br/menuestatistica/ses/BaseDados/BaseCompleta.zip",
]

# Grupos de ramos (Circular SUSEP 535/2016) — usado só se Ses_gruposramos.csv não vier no zip
GRUPOS_PADRAO = {
    "01": "Patrimonial", "02": "Riscos Especiais", "03": "Responsabilidades", "04": "Cascos",
    "05": "Automóvel", "06": "Transportes", "07": "Riscos Financeiros", "08": "Crédito",
    "09": "Pessoas Coletivo", "10": "Habitacional", "11": "Rural", "12": "Outros",
    "13": "Pessoas Individual", "14": "Marítimos", "15": "Aeronáuticos", "16": "Microsseguros",
    "17": "Exterior", "18": "Riscos Nucleares", "22": "Outros",
}

METRICAS = {  # nome no site -> colunas candidatas no Ses_seguros.csv (em ordem de preferência)
    "pd": ["premio_direto", "premio_emitido2", "premio_de_seguros"],
    "pg": ["premio_ganho"],
    "so": ["sinistro_ocorrido", "sinistro_retido", "sinistro_direto"],
    "dc": ["desp_com", "despesa_comercial"],
}

ANO_INICIO = env_int("SUSEP_ANO_INICIO", 2014)
TOP_N = 15


# ----------------------------------------------------------------------------- leitura
def para_numero(s: pd.Series) -> pd.Series:
    """Converte textos como '1.234,56' ou '1234.56' em float."""
    if s.dtype.kind in "if":
        return s.astype(float)
    t = s.astype(str).str.strip()
    tem_virgula = t.str.contains(",", regex=False)
    t = t.where(~tem_virgula, t.str.replace(".", "", regex=False).str.replace(",", ".", regex=False))
    return pd.to_numeric(t, errors="coerce").fillna(0.0)


def _membro(zf: zipfile.ZipFile, *partes: str, excluir: tuple[str, ...] = ()) -> str | None:
    """Acha um arquivo do zip cujo nome (normalizado) contém todas as partes."""
    for nome in zf.namelist():
        base = norm(Path(nome).name)
        if base.endswith(".csv") and all(p in base for p in partes) and not any(x in base for x in excluir):
            return nome
    return None


def _ler_csv(zf: zipfile.ZipFile, nome: str, **kw) -> pd.DataFrame:
    with zf.open(nome) as bruto:
        txt = abrir_texto(bruto)
        primeira = txt.readline()
        sep = detectar_separador(primeira)
        txt.seek(0)
        df = pd.read_csv(txt, sep=sep, dtype=str, **kw)
    df.columns = [norm(c) for c in df.columns]
    return df


def _ler_seguros(zf: zipfile.ZipFile, nome: str) -> pd.DataFrame:
    with zf.open(nome) as bruto:
        txt = abrir_texto(bruto)
        cab = txt.readline()
    sep = detectar_separador(cab)
    colunas = [norm(c.strip().strip('"')) for c in cab.strip().split(sep)]
    log.info("Ses_seguros.csv — colunas: %s", ", ".join(colunas))

    escolha = {}
    for k, cands in METRICAS.items():
        escolha[k] = next((c for c in cands if c in colunas), None)
        if escolha[k] is None:
            log.warning("métrica %s sem coluna correspondente (procurei %s)", k, cands)
    faltam = [c for c in ("damesano", "coenti", "coramo") if c not in colunas]
    if faltam:
        raise RuntimeError(f"Ses_seguros.csv sem colunas obrigatórias: {faltam}")
    log.info("colunas usadas: %s", escolha)

    usar = ["damesano", "coenti", "coramo"] + [c for c in escolha.values() if c]
    partes = []
    with zf.open(nome) as bruto:
        txt = abrir_texto(bruto)
        leitor = pd.read_csv(
            txt, sep=sep, dtype=str, chunksize=1_000_000,
            usecols=lambda c: norm(c) in usar,
        )
        for i, ch in enumerate(leitor):
            ch.columns = [norm(c) for c in ch.columns]
            ch["damesano"] = pd.to_numeric(ch["damesano"], errors="coerce")
            ch = ch[ch["damesano"] >= ANO_INICIO * 100]
            if ch.empty:
                continue
            out = pd.DataFrame({
                "m": ch["damesano"].astype(int),
                "coenti": ch["coenti"].str.strip().str.lstrip("0"),
                "coramo": ch["coramo"].str.strip().str.zfill(4),
            })
            for k, c in escolha.items():
                out[k] = para_numero(ch[c]) if c else 0.0
            partes.append(out.groupby(["m", "coenti", "coramo"], as_index=False).sum())
            log.info("  bloco %d lido (%d linhas)", i + 1, len(ch))
    if not partes:
        raise RuntimeError("nenhuma linha de Ses_seguros.csv no período")
    df = pd.concat(partes).groupby(["m", "coenti", "coramo"], as_index=False).sum()
    return df


# Cadastros com dados de pessoas: nunca entram no registro de estrutura
_PESSOAIS = ("administradores", "contatos", "part_acion", "dependencias")


def registrar_estrutura(zf: zipfile.ZipFile) -> None:
    """Grava data/susep_estrutura.json com as colunas e 3 linhas de exemplo de cada arquivo do zip.

    Serve para diagnosticar mudanças de layout da SUSEP sem precisar baixar a base inteira.
    """
    import json
    from common import CACHE_DIR
    out = {}
    for nome in zf.namelist():
        base = Path(nome).name
        if not base.lower().endswith(".csv"):
            continue
        info = {"bytes": zf.getinfo(nome).file_size}
        if not any(p in norm(base) for p in _PESSOAIS):
            try:
                with zf.open(nome) as bruto:
                    txt = abrir_texto(bruto)
                    linhas = [txt.readline().rstrip("\r\n") for _ in range(4)]
                info["cabecalho"] = linhas[0]
                info["exemplo"] = [l for l in linhas[1:] if l]
            except Exception as e:  # noqa: BLE001
                info["erro"] = str(e)
        out[base] = info
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    (CACHE_DIR / "susep_estrutura.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")


# ----------------------------------------------------------------------------- cálculos
def _ltm(meses: list[int], ultima: int, deslocamento: int = 0) -> list[int]:
    i = meses.index(ultima) - deslocamento
    return meses[max(0, i - 11): i + 1] if i >= 0 else []


def _concentracao(df: pd.DataFrame, ltm: list[int], ltm_ant: list[int]) -> dict:
    atual = df[df["m"].isin(ltm)].groupby("grupo_eco")["pd"].sum()
    ant = df[df["m"].isin(ltm_ant)].groupby("grupo_eco")["pd"].sum()
    atual = atual[atual > 0].sort_values(ascending=False)
    total = float(atual.sum())
    if total <= 0:
        return {}
    share = atual / total
    total_ant = float(ant[ant > 0].sum())
    share_ant = ant / total_ant if total_ant > 0 else ant * np.nan
    top = []
    for nome, v in atual.head(TOP_N).items():
        top.append({
            "nome": nome, "v": float(v), "share": float(share[nome]),
            "v_ant": float(ant.get(nome, 0.0)),
            "share_ant": float(share_ant.get(nome, np.nan)) if total_ant > 0 else None,
        })
    return {
        "total": total, "total_ant": total_ant, "n": int(len(atual)),
        "hhi": float((share.pow(2) * 10_000).sum()),
        "cr5": float(share.head(5).sum()), "cr10": float(share.head(10).sum()),
        "top": top,
    }


NOMES_PRODUTO = {"VGBL": "VGBL", "PGBL": "PGBL", "TRAD": "Previdência tradicional", "CAP": "Capitalização"}


def _sem_codigo(txt) -> str:
    t = re.sub(r"^\s*\d+\s*-\s*", "", str(txt or "")).strip()
    t = re.sub(r"\s{2,}", " ", t)
    return t[:1].upper() + t[1:] if t else t


def _produto(txt: str) -> str:
    t = norm(txt)
    if "vgbl" in t:
        return "VGBL"
    if "pgbl" in t:
        return "PGBL"
    if "trad" in t or "prev" in t:
        return "TRAD"
    return str(txt).strip() or "OUTROS"


def _mapa_grupo_economico(cias: pd.DataFrame, hist: pd.DataFrame) -> dict:
    """coenti -> nome do grupo econômico mais recente (ou o nome da empresa, se não tiver grupo)."""
    mapa = {}
    if not cias.empty and "coenti" in cias.columns:
        c = cias.assign(coenti=cias["coenti"].str.strip().str.lstrip("0"))
        nomes = c.get("noenti", c["coenti"]).fillna("").str.strip()
        mapa.update(dict(zip(c["coenti"], nomes.str.title())))
    if not hist.empty and {"coenti", "damesano", "nogrupo"} <= set(hist.columns):
        h = hist.assign(coenti=hist["coenti"].str.strip().str.lstrip("0"),
                        m=pd.to_numeric(hist["damesano"], errors="coerce"),
                        nogrupo=hist["nogrupo"].fillna("").str.strip())
        # "Independente" / "Outros Grupos" não são grupos de verdade: a empresa aparece pelo próprio nome
        sem_grupo = h["nogrupo"].map(norm).isin({"independente", "independentes", "outros grupos", "outros", "sem grupo"})
        h = h[(h["nogrupo"] != "") & ~sem_grupo].sort_values("m").drop_duplicates("coenti", keep="last")
        mapa.update(dict(zip(h["coenti"], h["nogrupo"].str.title())))
        log.info("grupos econômicos: %d empresas com grupo (base até %s)", len(h), int(h["m"].max()) if len(h) else "-")
    return mapa


def _ler_produtos(zf: zipfile.ZipFile) -> pd.DataFrame:
    """Contribuições de previdência (por tipo de produto) e receitas de capitalização, por empresa e mês."""
    partes = []
    try:
        nome = _membro(zf, "contrib_benef")
        if nome:
            df = _ler_csv(zf, nome)
            if {"damesano", "coenti", "tipoprod", "contrib"} <= set(df.columns):
                log.info("Ses_Contrib_Benef — tipos de produto: %s", sorted(df["tipoprod"].dropna().str.strip().unique().tolist()))
                partes.append(pd.DataFrame({"m": pd.to_numeric(df["damesano"], errors="coerce"),
                                            "coenti": df["coenti"].str.strip().str.lstrip("0"),
                                            "produto": df["tipoprod"].map(_produto), "pd": para_numero(df["contrib"])}))
        tem_pgbl = any((p["produto"] == "PGBL").any() for p in partes)
        nome = _membro(zf, "pgbl_contrib")
        if nome and not tem_pgbl:
            df = _ler_csv(zf, nome)
            if {"damesano", "coenti", "valor"} <= set(df.columns):
                partes.append(pd.DataFrame({"m": pd.to_numeric(df["damesano"], errors="coerce"),
                                            "coenti": df["coenti"].str.strip().str.lstrip("0"),
                                            "produto": "PGBL", "pd": para_numero(df["valor"])}))
        nome = _membro(zf, "ses_cap_uf")
        if nome:
            df = _ler_csv(zf, nome)
            if {"damesano", "coenti", "premio"} <= set(df.columns):
                partes.append(pd.DataFrame({"m": pd.to_numeric(df["damesano"], errors="coerce"),
                                            "coenti": df["coenti"].str.strip().str.lstrip("0"),
                                            "produto": "CAP", "pd": para_numero(df["premio"])}))
    except Exception as e:  # noqa: BLE001 — opcional: nunca derruba a atualização
        log.warning("previdência/capitalização: falha ao ler (%s)", e)
    if not partes:
        return pd.DataFrame(columns=["m", "coenti", "produto", "pd"])
    df = pd.concat(partes).dropna(subset=["m"])
    df["m"] = df["m"].astype(int)
    out = df.groupby(["m", "coenti", "produto"], as_index=False)["pd"].sum()
    for k, g in out.groupby("produto"):
        log.info("produto %s: %d meses (%d a %d)", k, g["m"].nunique(), g["m"].min(), g["m"].max())
    return out


def processar() -> dict:
    local = os.environ.get("SUSEP_ZIP")
    if local:
        caminho = Path(local)
    else:
        caminho = None
        for url in URLS:
            try:
                caminho = download(url, DOWNLOAD_DIR / "BaseCompleta.zip", timeout=600)
            except RuntimeError as e:
                log.warning(str(e))
            if caminho:
                break
        if not caminho:
            raise RuntimeError("BaseCompleta.zip indisponível em todas as URLs")

    with zipfile.ZipFile(caminho) as zf:
        log.info("arquivos no zip: %s", ", ".join(Path(n).name for n in zf.namelist()))
        registrar_estrutura(zf)
        nome_seg = _membro(zf, "ses_seguros")
        if not nome_seg:
            raise RuntimeError("Ses_seguros.csv não encontrado no zip")
        fatos = _ler_seguros(zf, nome_seg)

        cias = _ler_csv(zf, _membro(zf, "ses_cias")) if _membro(zf, "ses_cias") else pd.DataFrame()
        nome_ge = _membro(zf, "grupos_economicos")
        grupos_hist = _ler_csv(zf, nome_ge) if nome_ge else pd.DataFrame()
        ramos = _ler_csv(zf, _membro(zf, "ses_ramos")) if _membro(zf, "ses_ramos") else pd.DataFrame()
        nome_gr = _membro(zf, "gruposramos")
        grupos_ramo = _ler_csv(zf, nome_gr) if nome_gr else pd.DataFrame()
        produtos = _ler_produtos(zf)

    # --- dimensões (nomes sem o código na frente: "0531 - Automóvel - Casco" -> "Automóvel - Casco")
    nome_ramo, nome_grupo = {}, dict(GRUPOS_PADRAO)
    if not ramos.empty and "coramo" in ramos.columns:
        ramos["coramo"] = ramos["coramo"].str.strip().str.zfill(4)
        nome_ramo = dict(zip(ramos["coramo"], ramos.get("noramo", ramos["coramo"]).map(_sem_codigo)))
    if not grupos_ramo.empty and {"gracodigo", "granome"} <= set(grupos_ramo.columns):
        cod = grupos_ramo["gracodigo"].str.replace(r"\.0$", "", regex=True).str.strip().str.zfill(2)
        nome_grupo.update(dict(zip(cod, grupos_ramo["granome"].map(_sem_codigo))))

    grupo_eco = _mapa_grupo_economico(cias, grupos_hist)
    rot_eco = lambda s: s.map(grupo_eco).fillna("Empresa " + s)  # noqa: E731

    fatos["gr"] = fatos["coramo"].str[:2]
    fatos["linha"] = fatos["gr"]
    fatos["grupo_eco"] = rot_eco(fatos["coenti"])

    meses = sorted(fatos["m"].unique().tolist())
    ultima = meses[-1]
    ltm, ltm_ant = _ltm(meses, ultima), _ltm(meses, ultima, 12)
    log.info("SUSEP: %d meses (%d a %d)", len(meses), meses[0], ultima)

    # --- série mensal por grupo de ramos
    met = ["pd", "pg", "so", "dc"]
    serie = fatos.groupby(["m", "linha"], as_index=False)[met].sum()
    serie_rows = [[int(r.m), r.linha, float(r.pd), float(r.pg), float(r.so), float(r.dc)] for r in serie.itertuples()]

    # --- ramos (últimos 12 meses x 12 meses anteriores)
    r_atual = fatos[fatos["m"].isin(ltm)].groupby("coramo")[met].sum()
    r_ant = fatos[fatos["m"].isin(ltm_ant)].groupby("coramo")["pd"].sum()
    lista_ramos = []
    for cod, r in r_atual.iterrows():
        if r.pd <= 0:
            continue
        lista_ramos.append({
            "cod": cod, "nome": nome_ramo.get(cod, f"Ramo {cod}"), "gr": cod[:2],
            "pd": float(r.pd), "pd_ant": float(r_ant.get(cod, 0.0)),
            "sin": float(r.so / r.pg) if r.pg > 0 else None,
            "com": float(r.dc / r.pg) if r.pg > 0 else None,
        })
    lista_ramos.sort(key=lambda x: -x["pd"])

    # --- concentração: seguros (todos os grupos) e cada grupo de ramos
    conc = {"SEG": _concentracao(fatos, ltm, ltm_ant)}
    for linha in sorted(fatos["linha"].unique()):
        c = _concentracao(fatos[fatos["linha"] == linha], ltm, ltm_ant)
        if c:
            conc[linha] = c

    # --- previdência e capitalização (contribuições / receitas mensais)
    saida_prod = {}
    if not produtos.empty:
        produtos = produtos[produtos["m"] >= ANO_INICIO * 100]
        produtos["grupo_eco"] = rot_eco(produtos["coenti"])
        for chave, df in produtos.groupby("produto"):
            s = df.groupby("m")["pd"].sum().sort_index()
            m_prod = s.index.tolist()
            saida_prod[chave] = {"nome": NOMES_PRODUTO.get(chave, chave), "serie": [[int(m), float(v)] for m, v in s.items()]}
            if len(m_prod) >= 12:
                c = _concentracao(df, _ltm(m_prod, m_prod[-1]), _ltm(m_prod, m_prod[-1], 12))
                if c:
                    conc[chave] = c

    return {
        "fonte": "SUSEP — SES (Base Completa)",
        "ultima": int(ultima), "meses": [int(m) for m in meses],
        "ltm": [int(m) for m in ltm],
        "linhas": {l: nome_grupo.get(l, f"Grupo {l}") for l in sorted(set(serie["linha"]))},
        "serie_cols": ["m", "linha", "pd", "pg", "so", "dc"],
        "serie": serie_rows,
        "ramos": lista_ramos,
        "concentracao": conc,
        "produtos": saida_prod,
    }


def main() -> None:
    dados = processar()
    salvar_json("susep.json", dados)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
