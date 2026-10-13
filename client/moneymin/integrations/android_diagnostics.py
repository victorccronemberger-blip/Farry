"""Bounded, public Android diagnostics through the local ADB executable.

Only the USB inventory, four public properties, ``id`` and ``which su`` are
queried. Finding ``su`` does not execute it or grant any app a permission.
This module never reads app data, credentials, caches or tokens.
"""
from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import re
import shutil
import subprocess
import time


_DEADLINE_SECONDS = 8.0
_WINDOWS = os.name == "nt"
_PROPERTIES = (
    ("model", "ro.product.model"),
    ("manufacturer", "ro.product.manufacturer"),
    ("android_version", "ro.build.version.release"),
    ("sdk", "ro.build.version.sdk"),
)
_SERIAL = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:\-\[\]]{0,255}\Z")
_UID = re.compile(r"(?:^|\s)uid=(\d+)(?:\D|$)")


def _find_adb() -> str | None:
    """Check explicit tools locations, without scanning private settings."""
    name = "adb.exe" if _WINDOWS else "adb"
    configured = os.environ.get("QMONEY_ADB_PATH", "").strip()
    if configured:
        candidate = Path(configured).expanduser()
        if candidate.is_dir():
            candidate /= name
        if candidate.is_file():
            return str(candidate)

    located = shutil.which("adb")
    if located:
        return located

    roots: list[Path] = []
    for variable in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(variable, "").strip()
        if value:
            roots.append(Path(value).expanduser())
    local_app_data = os.environ.get("LOCALAPPDATA", "").strip()
    if local_app_data:
        roots.append(Path(local_app_data) / "Android" / "Sdk")
    home = Path.home()
    roots.extend((home / "AppData" / "Local" / "Android" / "Sdk",
                  home / "Android" / "Sdk", home / "Library" / "Android" / "sdk"))
    for root in roots:
        candidate = root / "platform-tools" / name
        if candidate.is_file():
            return str(candidate)
    return None


def _text(value: str) -> str:
    """Keep display fields short and free of terminal control characters."""
    return " ".join("".join(char for char in value if char.isprintable()).split())[:200]


def _inventory(output: str) -> list[dict[str, str]]:
    devices = []
    seen: set[str] = set()
    for line in output.splitlines():
        parts = line.split()
        if len(parts) < 2 or parts[1] not in {"device", "unauthorized", "offline"}:
            continue
        serial, state = parts[:2]
        if serial in seen:
            continue
        seen.add(serial)
        model = next((token[6:] for token in parts[2:] if token.startswith("model:")), "")
        devices.append({"serial": serial, "state": state,
                        "model": _text(model.replace("_", " "))})
    return devices


def _connection_failure(output: str) -> str | None:
    """Classify transport failures privately; raw ADB errors never leave here."""
    value = output.lower()
    if "unauthorized" in value:
        return "unauthorized"
    if "device offline" in value or "device is offline" in value:
        return "offline"
    if ("no devices/emulators found" in value or "no devices found" in value
            or "device disconnected" in value or re.search(r"device[^\n]*not found", value)):
        return "disconnected"
    if "more than one device" in value or "more than one emulator" in value:
        return "multiple"
    return None


_MESSAGES = {
    "adb_missing": "ADB não encontrado. Instale Android SDK Platform-Tools ou configure QMONEY_ADB_PATH.",
    "disconnected": "Nenhum aparelho disponível. Conecte o cabo USB e habilite a depuração USB no Android.",
    "unauthorized": "Autorize a depuração USB no diálogo do aparelho e atualize o diagnóstico.",
    "offline": "O aparelho está offline no ADB. Reconecte o cabo USB e atualize o diagnóstico.",
    "multiple": "Há mais de um aparelho disponível. Selecione o dispositivo para consultar.",
    "error": "Não foi possível consultar o ADB. Confira o cabo USB e a instalação do Platform-Tools e tente novamente.",
}


class _QueryFailure(Exception):
    def __init__(self, state: str, message: str):
        self.state = state
        self.message = message


def snapshot(serial: str | None = None) -> dict:
    """Return a stable public snapshot, with a shared eight-second deadline.

    A requested serial must be present in the fresh inventory before any shell
    command. With no selection, only one authorized device is selected. The
    inventory records the beginning of this query; transport failures during
    collection are reflected in ``connection_state`` and ``collection``.
    """
    started = time.monotonic()
    deadline = started + _DEADLINE_SECONDS
    result = {
        "adb_available": False,
        "connection_state": "adb_missing",
        "devices": [],
        "selected_serial": None,
        "device": {key: "" for key, _ in _PROPERTIES},
        "root": {"state": "unknown", "message": "Root não verificado. Isso não informa permissões de aplicativos."},
        "collection": {
            "state": "unavailable", "message": _MESSAGES["adb_missing"],
            "checked_at": datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z"),
            "elapsed_ms": 0,
        },
    }

    def finish(state: str, message: str, *, error: bool = False) -> dict:
        result["connection_state"] = state
        result["collection"].update(state="error" if error else "unavailable", message=message)
        result["collection"]["elapsed_ms"] = max(0, int((time.monotonic() - started) * 1000))
        return result

    def run(arguments: list[str], *, absent_ok: bool = False) -> subprocess.CompletedProcess:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise _QueryFailure("error", "Tempo limite do diagnóstico atingido. Confira a conexão USB e tente novamente.")
        options = dict(capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=remaining, shell=False)
        if _WINDOWS:
            options["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            completed = subprocess.run([adb, *arguments], **options)
        except subprocess.TimeoutExpired:
            raise _QueryFailure("error", "Tempo limite do diagnóstico atingido. Confira a conexão USB e tente novamente.") from None
        except FileNotFoundError:
            result["adb_available"] = False
            raise _QueryFailure("adb_missing", _MESSAGES["adb_missing"]) from None
        except OSError:
            raise _QueryFailure("error", _MESSAGES["error"]) from None
        if completed.returncode:
            failure = _connection_failure(f"{completed.stdout}\n{completed.stderr}")
            if failure:
                raise _QueryFailure(failure, _MESSAGES[failure])
            if not absent_ok:
                raise _QueryFailure("error", _MESSAGES["error"])
        return completed

    try:
        adb = _find_adb()
        if adb is None:
            return finish("adb_missing", _MESSAGES["adb_missing"])
        result["adb_available"] = True
        result["devices"] = _inventory(run(["devices", "-l"]).stdout)
        inventory = result["devices"]
        if serial is not None:
            if not isinstance(serial, str) or not _SERIAL.fullmatch(serial):
                return finish("error", "Seleção de aparelho inválida. Atualize a lista e selecione um dispositivo conectado.", error=True)
            selected = next((device for device in inventory if device["serial"] == serial), None)
            if selected is None:
                result["selected_serial"] = serial
                return finish("disconnected", "O aparelho selecionado não está no inventário ADB. Reconecte-o ou selecione outro dispositivo.")
        else:
            connected = [device for device in inventory if device["state"] == "device"]
            if len(connected) > 1 or (not connected and len(inventory) > 1):
                return finish("multiple", _MESSAGES["multiple"])
            selected = connected[0] if connected else inventory[0] if inventory else None
        if selected is None:
            return finish("disconnected", _MESSAGES["disconnected"])
        result["selected_serial"] = selected["serial"]
        state = selected["state"]
        if state != "device":
            return finish(state, _MESSAGES[state])
        if not _SERIAL.fullmatch(selected["serial"]):
            return finish("error", "Identificador ADB inválido. Atualize a lista de dispositivos.", error=True)
        prefix = ["-s", selected["serial"], "shell"]
        for field, prop in _PROPERTIES:
            result["device"][field] = _text(run([*prefix, "getprop", prop]).stdout)
        identity = run([*prefix, "id"]).stdout.strip()
        uid = _UID.search(identity)
        if uid and uid.group(1) == "0":
            result["root"] = {
                "state": "root_shell",
                "message": "O shell ADB informou uid=0. Isso não confirma permissões root de nenhum aplicativo.",
            }
        else:
            availability = run([*prefix, "which", "su"], absent_ok=True)
            su_available = availability.returncode == 0 and any(
                line.strip().startswith("/") and line.strip().endswith("/su")
                for line in availability.stdout.splitlines()
            )
            if su_available:
                result["root"] = {
                    "state": "su_available",
                    "message": "O executável su está disponível; ele não foi executado. Isso não confirma permissões root de aplicativos.",
                }
            elif uid and not availability.stderr.strip() and availability.returncode in (0, 1):
                result["root"] = {
                    "state": "not_detected",
                    "message": "A consulta pública não detectou shell root nem executável su. Isso não informa permissões de aplicativos.",
                }
        result["connection_state"] = "connected"
        result["collection"].update(state="done", message="Informações públicas do aparelho coletadas.")
        result["collection"]["elapsed_ms"] = max(0, int((time.monotonic() - started) * 1000))
        return result
    except _QueryFailure as failure:
        result["device"] = {key: "" for key, _ in _PROPERTIES}
        result["root"] = {"state": "unknown", "message": "Root não verificado. Isso não informa permissões de aplicativos."}
        return finish(failure.state, failure.message, error=True)
    except OSError:
        return finish("error", _MESSAGES["error"], error=True)
