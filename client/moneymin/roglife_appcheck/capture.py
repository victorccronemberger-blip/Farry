"""Captura/renovação do JWT App Check nas SharedPreferences do Minute."""
from __future__ import annotations

import base64
import json
import time
import xml.etree.ElementTree as ET

from .adb import adb_shell


def _b64url_json(segment: str):
    pad = "=" * ((4 - len(segment) % 4) % 4)
    return json.loads(base64.urlsafe_b64decode(segment + pad))


def read_appcheck(serial: str, cfg: dict) -> dict | None:
    xml_path = cfg["appcheck_xml"]
    token_key = cfg["appcheck_token_key"]
    result = adb_shell(serial, f'su 0 cat "{xml_path}"')
    if result.returncode != 0 or not (result.stdout or "").strip():
        result = adb_shell(serial, f"su -c 'cat \"{xml_path}\"'")
    if result.returncode != 0 or not (result.stdout or "").strip():
        return None
    try:
        root = ET.fromstring(result.stdout)
    except ET.ParseError:
        return None
    value = None
    for element in root.iter("string"):
        if element.get("name") == token_key:
            value = element.text or ""
    if not value:
        return None
    data = json.loads(value)
    jwt = data["token"]
    payload = _b64url_json(jwt.split(".")[1])
    return {
        "token": jwt,
        "iat": payload.get("iat"),
        "exp": payload.get("exp"),
        "provider": payload.get("provider"),
        "left": (payload.get("exp") or 0) - int(time.time()),
    }


def restart_minute(serial: str, package: str) -> None:
    adb_shell(serial, f"am force-stop {package}")
    time.sleep(2)
    adb_shell(serial, f"monkey -p {package} -c android.intent.category.LAUNCHER 1")


def refresh_appcheck(serial: str, cfg: dict, baseline_iat: int = 0) -> dict | None:
    package = cfg["package"]
    xml_path = cfg["appcheck_xml"]
    min_left = int(cfg.get("min_appcheck_left_s", 600))
    restart_minute(serial, package)
    deadline = time.time() + 180
    while time.time() < deadline:
        token = read_appcheck(serial, cfg)
        if token and token.get("iat") is not None and token["iat"] > baseline_iat:
            if token["left"] > min_left and token.get("provider") == "play_integrity":
                return token
        time.sleep(5)
    adb_shell(serial, f'su 0 rm -f "{xml_path}"')
    adb_shell(serial, f"su -c 'rm -f \"{xml_path}\"'")
    restart_minute(serial, package)
    deadline = time.time() + 180
    while time.time() < deadline:
        token = read_appcheck(serial, cfg)
        if token and token.get("left", 0) > min_left:
            return token
        time.sleep(5)
    return None


def ensure_appcheck(serial: str, cfg: dict, force: bool = False) -> dict:
    min_left = int(cfg.get("min_appcheck_left_s", 600))
    token = read_appcheck(serial, cfg)
    if token and not force and token.get("left", 0) >= min_left:
        return token
    baseline = (token or {}).get("iat") or 0
    fresh = refresh_appcheck(serial, cfg, baseline_iat=baseline if force else 0)
    if not fresh:
        raise RuntimeError(
            "Falha ao obter App Check do aparelho (Play Integrity). "
            "Use S22 físico com Minute aberto/logado e root."
        )
    return fresh
