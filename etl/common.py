"""Utilitários compartilhados pelo robô de dados (download, leitura de CSV, JSON)."""
from __future__ import annotations

import io
import json
import logging
import math
import os
import re
import time
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

import requests
import urllib3

ROOT = Path(__file__).resolve().parents[1]
CACHE_DIR = ROOT / "data"          # cache versionado no repositório (agregados intermediários)
DOWNLOAD_DIR = ROOT / ".downloads"  # arquivos brutos (não versionados)
SITE_DATA = ROOT / "site" / "data"  # JSON consumido pelo site

HEADERS = {"User-Agent": "dashboard-seguros/1.0 (+https://github.com)"}

log = logging.getLogger("etl")


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
    )


def norm(texto: str) -> str:
    """minúsculas, sem acento, sem espaços extras — para comparar nomes de colunas/arquivos."""
    t = unicodedata.normalize("NFKD", str(texto)).encode("ascii", "ignore").decode()
    return re.sub(r"\s+", " ", t).strip().lower()


def download(url: str, destino: Path, tentativas: int = 4, timeout: int = 120) -> Path | None:
    """Baixa um arquivo em streaming. Retorna None se não existir (404).

    Os servidores do governo às vezes têm cadeia de certificado incompleta; nesse caso
    a segunda tentativa desativa a verificação TLS (os dados são públicos e de leitura).
    """
    destino.parent.mkdir(parents=True, exist_ok=True)
    verificar = True
    for i in range(1, tentativas + 1):
        try:
            with requests.get(url, headers=HEADERS, stream=True, timeout=timeout, verify=verificar) as r:
                if r.status_code == 404:
                    return None
                r.raise_for_status()
                tmp = destino.with_suffix(destino.suffix + ".part")
                with open(tmp, "wb") as f:
                    for bloco in r.iter_content(chunk_size=1 << 20):
                        f.write(bloco)
                tmp.replace(destino)
                log.info("baixado %s (%.1f MB)", url, destino.stat().st_size / 1e6)
                return destino
        except requests.exceptions.SSLError:
            log.warning("erro de certificado em %s; tentando sem verificação TLS", url)
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            verificar = False
        except requests.RequestException as e:
            log.warning("tentativa %d/%d falhou para %s: %s", i, tentativas, url, e)
            time.sleep(10 * i)
    raise RuntimeError(f"não foi possível baixar {url}")


def get_text(url: str, timeout: int = 60) -> str | None:
    for verificar in (True, False):
        try:
            r = requests.get(url, headers=HEADERS, timeout=timeout, verify=verificar)
            if r.status_code == 404:
                return None
            r.raise_for_status()
            return r.text
        except requests.exceptions.SSLError:
            urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
            continue
        except requests.RequestException as e:
            log.warning("falha ao ler %s: %s", url, e)
            return None
    return None


def abrir_texto(binario) -> io.TextIOWrapper:
    """Abre um arquivo binário como texto, detectando UTF-8 x Latin-1 pelos primeiros bytes."""
    inicio = binario.read(1 << 16)
    binario.seek(0)
    try:
        inicio.decode("utf-8")
        enc = "utf-8-sig"
    except UnicodeDecodeError:
        enc = "latin-1"
    return io.TextIOWrapper(binario, encoding=enc, errors="replace", newline="")


def detectar_separador(linha: str) -> str:
    return max([";", ",", "\t", "|"], key=linha.count)


def _limpa(obj):
    """Converte NaN/inf para None e arredonda floats, para JSON enxuto e válido."""
    if isinstance(obj, float):
        if math.isnan(obj) or math.isinf(obj):
            return None
        return round(obj, 4) if abs(obj) < 100 else round(obj, 1)
    if isinstance(obj, dict):
        return {k: _limpa(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_limpa(v) for v in obj]
    if hasattr(obj, "item"):  # tipos numpy
        return _limpa(obj.item())
    return obj


def salvar_json(nome: str, dados: dict) -> Path:
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    dados = dict(dados)
    dados.setdefault("gerado_em", datetime.now(timezone.utc).isoformat(timespec="seconds"))
    caminho = SITE_DATA / nome
    caminho.write_text(json.dumps(_limpa(dados), ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    log.info("gravado %s (%.0f KB)", caminho.relative_to(ROOT), caminho.stat().st_size / 1e3)
    return caminho


def env_int(nome: str, padrao: int) -> int:
    try:
        return int(os.environ.get(nome, "") or padrao)
    except ValueError:
        return padrao
