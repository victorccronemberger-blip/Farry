"""Configuração do capturador RogLife (não altera a pasta original)."""
from __future__ import annotations

import json
import os
from pathlib import Path

# Finally/moneymin/roglife_appcheck -> Finally/
_FINALLY_ROOT = Path(__file__).resolve().parents[2]
_DEFAULT_CONFIG = _FINALLY_ROOT / "vendor" / "roglife" / "config.json"


def config_path() -> Path:
    override = os.environ.get("QMONEY_ROGLIFE_CONFIG", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return _DEFAULT_CONFIG


def load_config() -> dict:
    path = config_path()
    if not path.exists():
        raise FileNotFoundError(
            f"Config RogLife ausente: {path}. "
            "Copie vendor/roglife/config.json ou defina QMONEY_ROGLIFE_CONFIG."
        )
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("config RogLife inválida")
    required = ("package", "appcheck_xml", "appcheck_token_key")
    missing = [key for key in required if not str(data.get(key) or "").strip()]
    if missing:
        raise ValueError("config RogLife incompleta: " + ", ".join(missing))
    data.setdefault("min_appcheck_left_s", 600)
    data.setdefault("prefer_physical_device", True)
    data.setdefault("exclude_adb_serials", [])
    return data
