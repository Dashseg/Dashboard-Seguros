"""SUSEP — Sistema de Estatísticas (SES), base completa.

Fonte: https://www2.susep.gov.br/menuestatistica/ses/  (atualizada semanalmente)
Arquivos usados de dentro do BaseCompleta.zip:
  Ses_seguros.csv      fatos mensais por empresa (coenti) x ramo (coramo)
  Ses_cias.csv         empresas e grupos econômicos (coenti, noenti, cogrupo, nogrupo)
  Ses_ramos.csv        nomes dos ramos (coramo, noramo)
  Ses_gruposramos.csv  nomes dos grupos de ramos (GRACODIGO, GRANOME)
  ses_pgbl_contrib*    contribuições de PGBL (opcional)

Métricas:
  prêmio emitido  = premio_direto
  prêmio ganho    = premio_ganho
  sinistralidade  = sinistro_ocorrido / premio_ganho
  comissionamento = desp_com / premio_ganho
"""
from __future__ import annotations

import os
import zipfile
from pathlib import Path

import numpy as np
import pandas as pd

from common import DOWNLOAD_DIR, abrir_texto, detectar_separador, download, env_int, log, norm, salvar_json

URLS = [
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


def _ler_opcional_serie(zf: zipfile.ZipFile, nome: str | None, rotulo: str) -> list[dict]:
    """Série mensal total de um arquivo auxiliar (ex.: contribuições PGBL)."""
    if not nome:
        log.info("%s: arquivo não encontrado no zip — pulando", rotulo)
        return []
    try:
        df = _ler_csv(zf, nome)
        log.info("%s (%s) — colunas: %s", rotulo, nome, ", ".join(df.columns))
        if "damesano" not in df.columns:
            return []
        valores = [c for c in df.columns if c not in ("damesano", "coenti", "uf", "coramo", "cogrupo", "noenti")]
        val = next((c for c in valores if any(p in c for p in ("contrib", "receit", "valor", "premio", "arrec"))), None)
        val = val or (valores[0] if valores else None)
        if not val:
            return []
        df["m"] = pd.to_numeric(df["damesano"], errors="coerce")
        df = df[df["m"] >= ANO_INICIO * 100]
        df["v"] = para_numero(df[val])
        s = df.groupby("m")["v"].sum().sort_index()
        return [{"m": int(m), "v": float(v)} for m, v in s.items()]
    except Exception as e:  # opcional: nunca derruba a atualização
        log.warning("%s: falha ao ler (%s)", rotulo, e)
        return []


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
        nome_seg = _membro(zf, "ses_seguros")
        if not nome_seg:
            raise RuntimeError("Ses_seguros.csv não encontrado no zip")
        fatos = _ler_seguros(zf, nome_seg)

        cias = _ler_csv(zf, _membro(zf, "ses_cias")) if _membro(zf, "ses_cias") else pd.DataFrame()
        ramos = _ler_csv(zf, _membro(zf, "ses_ramos")) if _membro(zf, "ses_ramos") else pd.DataFrame()
        nome_gr = _membro(zf, "gruposramos")
        grupos_ramo = _ler_csv(zf, nome_gr) if nome_gr else pd.DataFrame()
        pgbl = _ler_opcional_serie(zf, _membro(zf, "pgbl", "contrib"), "PGBL contribuições")

    # --- dimensões
    nome_ramo, nome_grupo = {}, dict(GRUPOS_PADRAO)
    if not ramos.empty and "coramo" in ramos.columns:
        ramos["coramo"] = ramos["coramo"].str.strip().str.zfill(4)
        nome_ramo = dict(zip(ramos["coramo"], ramos.get("noramo", ramos["coramo"]).str.strip()))
    if not grupos_ramo.empty and {"gracodigo", "granome"} <= set(grupos_ramo.columns):
        cod = grupos_ramo["gracodigo"].str.replace(r"\.0$", "", regex=True).str.strip().str.zfill(2)
        nome_grupo.update(dict(zip(cod, grupos_ramo["granome"].str.strip().str.title())))

    grupo_eco = {}
    if not cias.empty and "coenti" in cias.columns:
        cias["coenti"] = cias["coenti"].str.strip().str.lstrip("0")
        nomes = cias.get("noenti", cias["coenti"]).fillna("").str.strip()
        grupos = cias.get("nogrupo", pd.Series("", index=cias.index)).fillna("").str.strip()
        rotulo = grupos.where(grupos != "", nomes).str.title()
        grupo_eco = dict(zip(cias["coenti"], rotulo))

    fatos["gr"] = fatos["coramo"].str[:2]
    fatos["vgbl"] = fatos["coramo"].map(lambda c: "vgbl" in norm(nome_ramo.get(c, "")))
    fatos["linha"] = np.where(fatos["vgbl"], "VGBL", fatos["gr"])
    fatos["grupo_eco"] = fatos["coenti"].map(grupo_eco).fillna("Empresa " + fatos["coenti"])

    meses = sorted(fatos["m"].unique().tolist())
    ultima = meses[-1]
    ltm, ltm_ant = _ltm(meses, ultima), _ltm(meses, ultima, 12)
    log.info("SUSEP: %d meses (%d a %d)", len(meses), meses[0], ultima)

    # --- série mensal por linha (grupo de ramo ou VGBL)
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
            "vgbl": "vgbl" in norm(nome_ramo.get(cod, "")),
            "pd": float(r.pd), "pd_ant": float(r_ant.get(cod, 0.0)),
            "sin": float(r.so / r.pg) if r.pg > 0 else None,
            "com": float(r.dc / r.pg) if r.pg > 0 else None,
        })
    lista_ramos.sort(key=lambda x: -x["pd"])

    # --- concentração por linha + total de seguros (ex-VGBL)
    conc = {"SEG": _concentracao(fatos[~fatos["vgbl"]], ltm, ltm_ant)}
    for linha in sorted(fatos["linha"].unique()):
        c = _concentracao(fatos[fatos["linha"] == linha], ltm, ltm_ant)
        if c:
            conc[linha] = c

    linhas_usadas = sorted(set(serie["linha"]))
    return {
        "fonte": "SUSEP — SES (Base Completa)",
        "ultima": int(ultima), "meses": [int(m) for m in meses],
        "ltm": [int(m) for m in ltm],
        "linhas": {l: ("VGBL" if l == "VGBL" else nome_grupo.get(l, f"Grupo {l}")) for l in linhas_usadas},
        "serie_cols": ["m", "linha", "pd", "pg", "so", "dc"],
        "serie": serie_rows,
        "ramos": lista_ramos,
        "concentracao": conc,
        "pgbl": pgbl,
    }


def main() -> None:
    dados = processar()
    salvar_json("susep.json", dados)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
