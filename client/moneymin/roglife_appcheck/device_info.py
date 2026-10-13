"""Identidade e props reais do aparelho via adb (sem forja)."""
from __future__ import annotations

import re
import time

from .adb import adb_shell, read_android_id


def _prop(serial: str, name: str) -> str:
    result = adb_shell(serial, f"getprop {name}")
    return (result.stdout or "").strip()


def _uptime_ns(serial: str) -> int | None:
    """Aproxima SystemClock.elapsedRealtimeNanos a partir de /proc/uptime."""
    result = adb_shell(serial, "cat /proc/uptime")
    text = (result.stdout or "").strip().split()
    if not text:
        return None
    try:
        seconds = float(text[0])
    except (TypeError, ValueError):
        return None
    if seconds < 0:
        return None
    return int(seconds * 1_000_000_000)


def _minute_version(serial: str, package: str) -> dict[str, str]:
    result = adb_shell(serial, f"dumpsys package {package}", timeout=60)
    text = result.stdout or ""
    version_name = ""
    version_code = ""
    for line in text.splitlines():
        line = line.strip()
        if line.startswith("versionName="):
            version_name = line.split("=", 1)[1].strip()
        elif line.startswith("versionCode="):
            # versionCode=1004038 minSdk=24 targetSdk=36
            match = re.match(r"versionCode=(\d+)", line)
            if match:
                version_code = match.group(1)
        if version_name and version_code:
            break
    out = {}
    if version_name:
        out["version_name"] = version_name
    if version_code:
        out["version_code"] = version_code
    return out


def collect_device_info(serial: str, *, package: str = "com.bakerdata.minute") -> dict:
    """Lê Build.* / SSAID / uptime / versão do Minute no aparelho físico."""
    device_id = read_android_id(serial)
    model = _prop(serial, "ro.product.model") or None
    manufacturer = _prop(serial, "ro.product.manufacturer") or None
    brand = _prop(serial, "ro.product.brand") or None
    device = _prop(serial, "ro.product.device") or None
    release = _prop(serial, "ro.build.version.release") or None
    sdk_raw = _prop(serial, "ro.build.version.sdk")
    try:
        sdk_int = int(sdk_raw) if sdk_raw else None
    except ValueError:
        sdk_int = None
    uptime_ns = _uptime_ns(serial)
    app = _minute_version(serial, package)
    info = {
        "serial": serial,
        "device_id": device_id,
        "model": model,
        "manufacturer": manufacturer,
        "brand": brand,
        "product_device": device,
        "system_name": "Android",
        "system_version": release,
        "sdk_int": sdk_int,
        "uptime_ns": uptime_ns,
        "app_version": app.get("version_name"),
        "app_version_code": app.get("version_code"),
        "collected_at_unix": int(time.time()),
        "source": "adb_getprop",
    }
    # Remove vazios para não sobrescrever cache com nulls acidentais.
    return {key: value for key, value in info.items() if value not in (None, "", [])}
