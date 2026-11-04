"""Ponto de entrada do robô: atualiza SUSEP e ANS de forma independente.

Se uma fonte falhar (portal fora do ar, mudança de layout), a outra segue normalmente e o
site continua mostrando os últimos dados bons daquela fonte. O resultado de cada etapa fica
em site/data/status.json, exibido no rodapé do dashboard.

Uso:  python etl/atualizar.py [susep] [ans]
"""
from __future__ import annotations

import json
import sys
import traceback
from datetime import datetime, timezone

from common import SITE_DATA, log, setup_logging


def _agora() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def main(fontes: list[str]) -> int:
    setup_logging()
    caminho = SITE_DATA / "status.json"
    status = json.loads(caminho.read_text(encoding="utf-8")) if caminho.exists() else {}
    falhas = 0
    for fonte in fontes:
        log.info("=== %s ===", fonte.upper())
        try:
            if fonte == "susep":
                import susep
                susep.main()
            elif fonte == "ans":
                import ans
                ans.main()
            status[fonte] = {"ok": True, "em": _agora()}
        except Exception as e:  # noqa: BLE001
            falhas += 1
            traceback.print_exc()
            anterior = status.get(fonte, {})
            status[fonte] = {"ok": False, "em": _agora(), "erro": str(e)[:300],
                             "ultimo_ok": anterior.get("em") if anterior.get("ok") else anterior.get("ultimo_ok")}
    SITE_DATA.mkdir(parents=True, exist_ok=True)
    caminho.write_text(json.dumps(status, ensure_ascii=False, indent=1), encoding="utf-8")
    return 1 if falhas == len(fontes) else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["susep", "ans"]))
