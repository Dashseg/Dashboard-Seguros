"""ANS — Informações Consolidadas de Beneficiários (dados abertos, PDA 024).

Fonte: https://dadosabertos.ans.gov.br/FTP/PDA/informacoes_consolidadas_de_beneficiarios-024/
Um zip por UF por mês:  {AAAAMM}/pda-024-icb-{UF}-{AAAA}_{MM}.zip  (~400 MB/mês no total)

Cada mês baixado é reduzido a um agregado pequeno e guardado em data/ans/icb_AAAAMM.csv.gz,
que fica versionado no repositório. Assim cada execução só baixa os meses novos.
"""
from __future__ import annotations

import os
import re
import zipfile
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from common import CACHE_DIR, DOWNLOAD_DIR, abrir_texto, detectar_separador, download, env_int, get_text, log, norm, salvar_json

BASE = "https://dadosabertos.ans.gov.br/FTP/PDA/informacoes_consolidadas_de_beneficiarios-024/"
UFS = ["AC", "AL", "AM", "AP", "BA", "CE", "DF", "ES", "GO", "MA", "MG", "MS", "MT", "PA", "PB", "PE",
       "PI", "PR", "RJ", "RN", "RO", "RR", "RS", "SC", "SE", "SP", "TO", "XX"]  # XX = UF não identificada
CACHE = CACHE_DIR / "ans"

MESES_HISTORICO = env_int("ANS_MESES_HISTORICO", 25)   # janela mantida no dashboard
MAX_NOVOS = env_int("ANS_MAX_MESES_POR_EXECUCAO", 6)    # limita a duração de cada execução
TOP_N = 15

COLS = {
    "cd_operadora": "op", "nm_razao_social": "nome", "modalidade_operadora": "mod",
    "sg_uf": "uf", "de_contratacao_plano": "contr", "cobertura_assist_plan": "cob",
    "qt_beneficiario_ativo": "ativos",
}
CHAVES = ["op", "nome", "mod", "uf", "contr", "cob"]


def _cobertura(txt: str) -> str:
    t = norm(txt)
    if t.startswith("odont"):
        return "OD"
    if t.startswith("medic") or "hosp" in t:
        return "MH"
    return "OUT"


# ----------------------------------------------------------------------------- download
def meses_disponiveis() -> list[int]:
    local = os.environ.get("ANS_DIR")
    if local:
        return sorted({int(p.name) for p in Path(local).iterdir() if re.fullmatch(r"\d{6}", p.name)})
    html = get_text(BASE)
    if html:
        meses = sorted({int(m) for m in re.findall(r'href="(\d{6})/?"', html)})
        if meses:
            return meses
    # sem listagem: considera os últimos 36 meses e deixa o download dizer o que existe
    hoje = date.today()
    out = []
    for k in range(36):
        y, m = divmod(hoje.year * 12 + hoje.month - 1 - k, 12)
        out.append(y * 100 + m + 1)
    return sorted(out)


def _arquivo_uf(mes: int, uf: str) -> Path | None:
    aaaa, mm = divmod(mes, 100)
    nome = f"pda-024-icb-{uf}-{aaaa}_{mm:02d}.zip"
    local = os.environ.get("ANS_DIR")
    if local:
        p = Path(local) / str(mes) / nome
        return p if p.exists() else None
    return download(f"{BASE}{mes}/{nome}", DOWNLOAD_DIR / "ans" / nome, timeout=900)


def _agregar_zip(caminho: Path) -> pd.DataFrame:
    partes = []
    with zipfile.ZipFile(caminho) as zf:
        for membro in zf.namelist():
            if not membro.lower().endswith(".csv"):
                continue
            with zf.open(membro) as bruto:
                txt = abrir_texto(bruto)
                sep = detectar_separador(txt.readline())
            with zf.open(membro) as bruto:
                txt = abrir_texto(bruto)
                leitor = pd.read_csv(txt, sep=sep, dtype=str, chunksize=1_500_000,
                                     usecols=lambda c: norm(c) in COLS)
                for ch in leitor:
                    ch.columns = [COLS[norm(c)] for c in ch.columns]
                    faltam = set(COLS.values()) - set(ch.columns)
                    for f in faltam:
                        ch[f] = "Não informado" if f != "ativos" else "0"
                    ch["ativos"] = pd.to_numeric(ch["ativos"], errors="coerce").fillna(0)
                    ch["op"] = ch["op"].str.strip().str.lstrip("0")
                    ch["cob"] = ch["cob"].map(_cobertura)
                    for c in ("nome", "mod", "uf", "contr"):
                        ch[c] = ch[c].fillna("Não informado").str.strip()
                    partes.append(ch.groupby(CHAVES, as_index=False)["ativos"].sum())
    if not partes:
        return pd.DataFrame(columns=CHAVES + ["ativos"])
    return pd.concat(partes).groupby(CHAVES, as_index=False)["ativos"].sum()


def processar_mes(mes: int) -> bool:
    partes, achados = [], 0
    for uf in UFS:
        try:
            arq = _arquivo_uf(mes, uf)
        except RuntimeError as e:
            log.warning("%s", e)
            arq = None
        if not arq:
            continue
        achados += 1
        partes.append(_agregar_zip(arq))
        if not os.environ.get("ANS_DIR"):
            arq.unlink(missing_ok=True)  # libera disco do runner
    if achados < 20:
        log.info("ANS %d: só %d UFs disponíveis — mês ainda não publicado", mes, achados)
        return False
    df = pd.concat(partes).groupby(CHAVES, as_index=False)["ativos"].sum()
    df["ativos"] = df["ativos"].astype(np.int64)
    CACHE.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE / f"icb_{mes}.csv.gz", index=False, compression="gzip")
    log.info("ANS %d: %d UFs, %.1f mi de beneficiários ativos", mes, achados, df["ativos"].sum() / 1e6)
    return True


def atualizar_cache() -> None:
    disponiveis = meses_disponiveis()
    alvo = disponiveis[-MESES_HISTORICO:]
    feitos = {int(p.name[4:10]) for p in CACHE.glob("icb_*.csv.gz")} if CACHE.exists() else set()
    faltando = [m for m in reversed(alvo) if m not in feitos]  # mais recentes primeiro
    log.info("ANS: %d meses no alvo, %d em cache, %d faltando (limite por execução: %d)",
             len(alvo), len(feitos & set(alvo)), len(faltando), MAX_NOVOS)
    novos = 0
    for mes in faltando:
        if novos >= MAX_NOVOS:
            log.info("ANS: limite da execução atingido; o restante entra nas próximas")
            break
        if processar_mes(mes):
            novos += 1
    # remove meses que saíram da janela
    if alvo:
        for p in CACHE.glob("icb_*.csv.gz"):
            if int(p.name[4:10]) < alvo[0]:
                p.unlink()


# ----------------------------------------------------------------------------- saída para o site
def _concentracao(atual: pd.Series, ant: pd.Series, nomes: dict) -> dict:
    atual = atual[atual > 0].sort_values(ascending=False)
    total = float(atual.sum())
    if total <= 0:
        return {}
    share = atual / total
    total_ant = float(ant.sum())
    top = [{
        "nome": nomes.get(op, op), "mod": None, "v": float(v), "share": float(share[op]),
        "v_ant": float(ant.get(op, 0)),
        "share_ant": float(ant.get(op, 0) / total_ant) if total_ant else None,
    } for op, v in atual.head(TOP_N).items()]
    return {"total": total, "total_ant": total_ant, "n": int(len(atual)),
            "hhi": float((share.pow(2) * 10_000).sum()),
            "cr5": float(share.head(5).sum()), "cr10": float(share.head(10).sum()), "top": top}


def montar_json() -> dict | None:
    arquivos = sorted(CACHE.glob("icb_*.csv.gz")) if CACHE.exists() else []
    if not arquivos:
        log.warning("ANS: nenhum mês em cache")
        return None
    meses, series = [], []
    ultimo_df = None
    por_mes = {}
    for p in arquivos:
        mes = int(p.name[4:10])
        df = pd.read_csv(p, dtype={"op": str})
        meses.append(mes)
        por_mes[mes] = df
        s = df.groupby(["cob", "contr", "mod"], as_index=False)["ativos"].sum()
        series += [[mes, r.cob, r.contr, r.mod, int(r.ativos)] for r in s.itertuples()]
    ultima = meses[-1]
    aaaa, mm = divmod(ultima, 100)
    alvo_ant = (aaaa - 1) * 100 + mm
    comparacao = alvo_ant if alvo_ant in por_mes else meses[0]
    ultimo_df, ant_df = por_mes[ultima], por_mes[comparacao]

    uf_atual = ultimo_df.groupby(["uf", "cob"])["ativos"].sum()
    uf_ant = ant_df.groupby(["uf", "cob"])["ativos"].sum()
    ufs = [[uf, cob, int(v), int(uf_ant.get((uf, cob), 0))] for (uf, cob), v in uf_atual.items()]

    nomes = (ultimo_df.drop_duplicates("op").set_index("op")["nome"].str.title()).to_dict()
    mod_op = ultimo_df.drop_duplicates("op").set_index("op")["mod"].to_dict()
    conc = {}
    for cob in ("MH", "OD"):
        a = ultimo_df[ultimo_df["cob"] == cob].groupby("op")["ativos"].sum()
        b = ant_df[ant_df["cob"] == cob].groupby("op")["ativos"].sum()
        c = _concentracao(a, b, nomes)
        for item, op in zip(c.get("top", []), a.sort_values(ascending=False).head(TOP_N).index):
            item["mod"] = mod_op.get(op)
        if c:
            conc[cob] = c

    return {
        "fonte": "ANS — Informações Consolidadas de Beneficiários (PDA 024)",
        "ultima": ultima, "comparacao": comparacao, "meses": meses,
        "serie_cols": ["m", "cob", "contr", "mod", "ativos"], "serie": series,
        "uf_cols": ["uf", "cob", "ativos", "ativos_ant"], "uf": ufs,
        "concentracao": conc,
    }


def main() -> None:
    if os.environ.get("ANS_PULAR_DOWNLOAD") != "1":
        atualizar_cache()
    dados = montar_json()
    if dados:
        salvar_json("ans.json", dados)


if __name__ == "__main__":
    from common import setup_logging
    setup_logging()
    main()
