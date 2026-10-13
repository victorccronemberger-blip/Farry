"""Optional App Check debug provider for an administrator-authorized Firebase app.

No token capture, attestation bypass, or persistent credential cache. Missing
configuration sends no header; a server rejection must remain a rejection.
"""
from __future__ import annotations

import hashlib
import json
import logging
import math
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import contextmanager
from math import ceil
from pathlib import Path

from . import config, tls

logger = logging.getLogger(__name__)
_lock = threading.RLock()
_identity = None
_token = None
_expires = 0.0
_retry_at = 0.0
# Sanitized mint outcome only: never store secrets, URLs, or response bodies.
_last_failure: str | None = None
_last_diagnostic: dict | None = None

_FAILURE_NOT_CONFIGURED = "not_configured"
_FAILURE_ATTESTATION = "attestation_failed"
_FAILURE_PERMISSION = "permission_denied"
_FAILURE_QUOTA = "quota_exhausted"
_FAILURE_INVALID = "invalid_response"
_FAILURE_EXCHANGE = "exchange_failed"
_ATTESTATION_COOLDOWN_S = 3600.0
_QUOTA_COOLDOWN_S = 70.0
_NON_RETRYABLE_FAILURES = {_FAILURE_ATTESTATION, _FAILURE_PERMISSION}
_FAILURE_MESSAGES = {
    _FAILURE_NOT_CONFIGURED: "App Check não está configurado.",
    _FAILURE_ATTESTATION: "Firebase recusou a atestação na troca de App Check.",
    _FAILURE_PERMISSION: "Firebase negou permissão na troca de App Check.",
    _FAILURE_QUOTA: "A cota de troca de App Check foi excedida.",
    _FAILURE_INVALID: "A configuração ou resposta de App Check é inválida.",
    _FAILURE_EXCHANGE: "Não foi possível concluir a troca de App Check.",
}
_FIREBASE_STATUSES = {
    "CANCELLED", "UNKNOWN", "INVALID_ARGUMENT", "DEADLINE_EXCEEDED",
    "NOT_FOUND", "ALREADY_EXISTS", "PERMISSION_DENIED", "RESOURCE_EXHAUSTED",
    "FAILED_PRECONDITION", "ABORTED", "OUT_OF_RANGE", "UNAUTHENTICATED",
    "INTERNAL", "UNAVAILABLE", "DATA_LOSS",
}


class AppCheckExchangeError(RuntimeError):
    """Safe, structured Firebase exchange failure without a response body."""

    def __init__(self, category: str, *, http_status: int | None = None,
                 firebase_status: str | None = None):
        if (not isinstance(category, str) or category not in _FAILURE_MESSAGES
                or category == _FAILURE_NOT_CONFIGURED):
            category = _FAILURE_EXCHANGE
        if type(http_status) is not int or not 100 <= http_status <= 599:
            http_status = None
        if not isinstance(firebase_status, str) or firebase_status not in _FIREBASE_STATUSES:
            firebase_status = None
        self.category = category
        self.http_status = http_status
        self.firebase_status = firebase_status
        super().__init__(category)


def _settings():
    return tuple(os.environ.get(key, "").strip() for key in (
        "FIREBASE_APP_CHECK_PROJECT_ID", "FIREBASE_APP_CHECK_APP_ID",
        "FIREBASE_APP_CHECK_API_KEY", "FIREBASE_APP_CHECK_DEBUG_TOKEN"))


def _configured_bearer() -> str:
    """Optional administrator-supplied App Check JWT (not a debug secret)."""
    return os.environ.get("FIREBASE_APP_CHECK_BEARER", "").strip()


def _bearer_still_valid(token: str) -> bool:
    """Accept only compact JWTs with a future exp; signature is server-verified."""
    parts = token.split(".")
    if len(parts) != 3 or not all(parts):
        return False
    if any(ord(c) <= 32 or ord(c) >= 127 for c in token) or len(token) > 16384:
        return False
    try:
        import base64
        pad = "=" * (-len(parts[1]) % 4)
        payload = json.loads(base64.urlsafe_b64decode(parts[1] + pad))
    except (ValueError, TypeError, json.JSONDecodeError):
        return False
    if not isinstance(payload, dict):
        return False
    exp = payload.get("exp")
    if type(exp) not in (int, float):
        return False
    # Small skew margin; server still enforces exact expiry.
    try:
        expiry = float(exp)
    except (OverflowError, ValueError):
        return False
    return math.isfinite(expiry) and expiry > time.time() + 30


def _settings_digest(values: tuple[str, ...]) -> str:
    bearer = _configured_bearer()
    return hashlib.sha256(
        json.dumps((str(config.ROOT), values, bool(bearer))).encode()
    ).hexdigest()[:24]


def _state_path() -> Path:
    return Path(config.DATA_DIR) / "appcheck_mint_state.json"


def _lock_path() -> Path:
    return Path(config.DATA_DIR) / "appcheck_exchange.lock"


def _load_persisted_state(digest: str) -> dict | None:
    path = _state_path()
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(raw, dict):
        return None
    if raw.get("settings_digest") != digest:
        return None
    failure = raw.get("failure")
    retry_after = raw.get("retry_after_unix")
    if not isinstance(failure, str) or failure not in {
        _FAILURE_ATTESTATION, _FAILURE_PERMISSION, _FAILURE_QUOTA, _FAILURE_EXCHANGE, _FAILURE_INVALID,
    }:
        return None
    if type(retry_after) not in (int, float):
        return None
    try:
        retry_after = float(retry_after)
    except (OverflowError, ValueError):
        return None
    if (not math.isfinite(retry_after) or retry_after < 0
            or retry_after - time.time() > _ATTESTATION_COOLDOWN_S + 60):
        return None
    http_status = raw.get("http_status")
    if type(http_status) is not int or not 100 <= http_status <= 599:
        http_status = None
    firebase_status = raw.get("firebase_status")
    if not isinstance(firebase_status, str) or firebase_status not in _FIREBASE_STATUSES:
        firebase_status = None
    # Old files have only failure/retry_after_unix. Never trust or surface a
    # message copied from disk; the public text is selected from our own map.
    return {
        "failure": failure,
        "retry_after_unix": retry_after,
        "http_status": http_status,
        "firebase_status": firebase_status,
        "message": _FAILURE_MESSAGES[failure],
    }


def _save_persisted_state(digest: str, failure: str | None, cooldown_s: float,
                          *, http_status: int | None = None,
                          firebase_status: str | None = None) -> None:
    path = _state_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        if failure is None:
            if path.exists():
                path.unlink()
            return
        if not isinstance(failure, str) or failure not in _FAILURE_MESSAGES or failure == _FAILURE_NOT_CONFIGURED:
            failure = _FAILURE_EXCHANGE
        if (type(http_status) is not int or not 100 <= http_status <= 599):
            http_status = None
        if not isinstance(firebase_status, str) or firebase_status not in _FIREBASE_STATUSES:
            firebase_status = None
        retry_after = time.time() + cooldown_s
        if not math.isfinite(retry_after) or retry_after < 0:
            return
        payload = {
            "settings_digest": digest,
            "failure": failure,
            "retry_after_unix": retry_after,
            "http_status": http_status,
            "firebase_status": firebase_status,
            "message": _FAILURE_MESSAGES[failure],
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
    except OSError:
        # Local coordination only; mint behavior remains correct in-process.
        pass


def clear_cache() -> None:
    """Forget process-local credentials. Never read or delete installation files."""
    global _identity, _token, _expires, _retry_at, _last_failure, _last_diagnostic
    with _lock:
        _identity, _token, _expires, _retry_at, _last_failure, _last_diagnostic = (
            None, None, 0.0, 0.0, None, None)
        try:
            path = _state_path()
            if path.exists():
                path.unlink()
        except OSError:
            pass


def is_app_check_configured() -> bool:
    try:
        from . import roglife_appcheck
        if roglife_appcheck.device_mode_enabled():
            return True
    except Exception:
        pass
    return bool(_configured_bearer()) or all(_settings())


@contextmanager
def _exchange_file_lock():
    """Serialize debug-token exchanges across local processes."""
    path = _lock_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    stream = open(path, "a+b")
    locked = False
    try:
        try:
            import msvcrt
            # Blocking lock: one exchange at a time on this machine.
            msvcrt.locking(stream.fileno(), msvcrt.LK_LOCK, 1)
            locked = True
        except ImportError:
            import fcntl
            fcntl.flock(stream.fileno(), fcntl.LOCK_EX)
            locked = True
        yield
    finally:
        if locked:
            try:
                import msvcrt
                msvcrt.locking(stream.fileno(), msvcrt.LK_UNLCK, 1)
            except ImportError:
                import fcntl
                fcntl.flock(stream.fileno(), fcntl.LOCK_UN)
            except OSError:
                pass
        stream.close()


def last_mint_failure() -> str | None:
    """Return a sanitized mint failure category, or None after a successful mint."""
    with _lock:
        return _last_failure


def _settings_identity(values: tuple[str, ...], bearer: str) -> bytes:
    return hashlib.sha256(json.dumps((str(config.ROOT), values, bearer)).encode()).digest()


def _select_identity(values: tuple[str, ...], bearer: str) -> None:
    global _identity, _token, _expires, _retry_at, _last_failure, _last_diagnostic
    identity = _settings_identity(values, bearer)
    if identity != _identity:
        _identity, _token, _expires = identity, None, 0.0
        _last_failure, _last_diagnostic, _retry_at = None, None, 0.0
        _restore_persisted_failure(_settings_digest(values))


def _restore_persisted_failure(digest: str, persisted: dict | None = None) -> None:
    """Restore only sanitized failure metadata; this helper never mints."""
    global _last_failure, _last_diagnostic, _retry_at
    if persisted is None:
        persisted = _load_persisted_state(digest)
    if persisted is None:
        _last_failure, _last_diagnostic, _retry_at = None, None, 0.0
        return
    _last_failure = persisted["failure"]
    _last_diagnostic = {
        "category": persisted["failure"],
        "http_status": persisted.get("http_status"),
        "firebase_status": persisted.get("firebase_status"),
        "message": persisted.get("message", _FAILURE_MESSAGES[persisted["failure"]]),
        "retry_after_unix": persisted["retry_after_unix"],
    }
    wait_s = max(0.0, persisted["retry_after_unix"] - time.time())
    _retry_at = time.monotonic() + wait_s


def _set_failure_diagnostic(category: str, *, http_status: int | None = None,
                            firebase_status: str | None = None,
                            retry_after_unix: float | None = None) -> None:
    global _last_failure, _last_diagnostic
    if (not isinstance(category, str) or category not in _FAILURE_MESSAGES
            or category == _FAILURE_NOT_CONFIGURED):
        category = _FAILURE_EXCHANGE
    if type(http_status) is not int or not 100 <= http_status <= 599:
        http_status = None
    if not isinstance(firebase_status, str) or firebase_status not in _FIREBASE_STATUSES:
        firebase_status = None
    _last_failure = category
    _last_diagnostic = {
        "category": category,
        "http_status": http_status,
        "firebase_status": firebase_status,
        "message": _FAILURE_MESSAGES[category],
        "retry_after_unix": retry_after_unix,
    }


def last_mint_diagnostic() -> dict | None:
    """Return the local sanitized mint diagnosis, restoring persisted state offline."""
    global _identity, _token, _expires, _retry_at, _last_failure, _last_diagnostic
    with _lock:
        values = _settings()
        bearer = _configured_bearer()
        _select_identity(values, bearer)
        if _last_diagnostic is None:
            return None
        result = dict(_last_diagnostic)
        if _retry_at:
            result["retry_after_seconds"] = max(
                0, int(ceil(_retry_at - time.monotonic())))
        else:
            result["retry_after_seconds"] = 0
        result["retry_requires_explicit"] = (
            result["category"] in _NON_RETRYABLE_FAILURES)
        return result


def _is_paused() -> bool:
    try:
        return (Path(config.DATA_DIR) / "appcheck_pause.flag").exists()
    except OSError:
        return False


def app_check_status() -> dict:
    """Return a local-only App Check snapshot without minting or network access."""
    values = _settings()
    bearer = _configured_bearer()
    device = {}
    try:
        from . import roglife_appcheck
        device = roglife_appcheck.status_snapshot()
    except Exception:
        device = {"enabled": False, "token_available": False}
    configured = bool(device.get("enabled")) or bool(bearer) or all(values)
    configuration_present = (
        bool(device.get("enabled")) or bool(bearer) or any(values)
    )
    paused = _is_paused()
    diagnostic = last_mint_diagnostic()
    token_available = False
    source = None
    if device.get("enabled") and device.get("token_available"):
        token_available = True
        source = "device"
    elif bearer:
        token_available = _bearer_still_valid(bearer)
        source = "bearer" if token_available else None
    elif all(values) and not paused:
        with _lock:
            token_available = bool(_token and time.monotonic() < _expires)
        source = "debug_exchange" if token_available else None
    retry_after_seconds = (
        diagnostic.get("retry_after_seconds") if diagnostic else 0)
    return {
        "configured": configured,
        "configuration_present": configuration_present,
        "configuration_pending": configuration_present and not configured,
        "token_available": token_available,
        "source": source,
        "device": device,
        "failure": diagnostic.get("category") if diagnostic else None,
        "diagnostic": diagnostic,
        "retry_after_seconds": int(retry_after_seconds or 0),
        "paused": paused,
    }


def _classify_exchange_http_error(exc: urllib.error.HTTPError) -> str:
    """Map Firebase exchange HTTP errors to stable local categories without bodies."""
    return _exchange_http_diagnostic(exc)["category"]


def _exchange_http_diagnostic(exc: urllib.error.HTTPError) -> dict:
    try:
        status = int(getattr(exc, "code", 0) or 0)
    except (TypeError, ValueError, OverflowError):
        status = None
    if status is None or not 100 <= status <= 599:
        status = None
    try:
        raw = exc.read(4096)
    except Exception:
        raw = b""
    message = ""
    firebase_status = ""
    try:
        payload = json.loads(raw.decode("utf-8", "replace")) if raw else {}
        error = payload.get("error") if isinstance(payload, dict) else None
        if isinstance(error, dict):
            message = str(error.get("message") or "")
            firebase_status = str(error.get("status") or "")
    except (ValueError, TypeError, UnicodeError):
        pass
    normalized = re.sub(r"[ _-]", "", f"{message} {firebase_status}").casefold()
    if status == 403 and "appattestationfailed" in normalized:
        category = _FAILURE_ATTESTATION
    elif status == 403:
        # Permission denial alone does not identify the failed authorization rule.
        category = _FAILURE_PERMISSION
    elif status == 429 or "resourceexhausted" in normalized or "quota" in normalized:
        category = _FAILURE_QUOTA
    else:
        category = _FAILURE_EXCHANGE
    return {
        "category": category,
        "http_status": status,
        "firebase_status": (firebase_status if isinstance(firebase_status, str)
                            and firebase_status in _FIREBASE_STATUSES else None),
    }


def _exchange(project, app, api_key, secret):
    path = '/'.join(urllib.parse.quote(part, safe='') for part in (project, app))
    project_path, app_path = path.split('/')
    url = (f"https://firebaseappcheck.googleapis.com/v1/projects/{project_path}"
           f"/apps/{app_path}:exchangeDebugToken?key={urllib.parse.quote(api_key, safe='')}")
    req = urllib.request.Request(url, method="POST",
        headers={"Content-Type": "application/json"},
        data=json.dumps({"debugToken": secret}).encode())
    try:
        with tls.urlopen(req, timeout=10) as response:
            if response.status != 200:
                raise ValueError("exchange failed")
            raw = response.read(65537)
            if len(raw) > 65536:
                raise ValueError("oversized response")
            data = json.loads(raw)
    except urllib.error.HTTPError as exc:
        raise AppCheckExchangeError(**_exchange_http_diagnostic(exc)) from None
    token, ttl = data.get("token"), data.get("ttl")
    if (not isinstance(token, str) or not token or len(token) > 16384
            or any(ord(c) <= 32 or ord(c) >= 127 for c in token)
            or not isinstance(ttl, str) or not re.fullmatch(r"[0-9]+(?:\.[0-9]{1,9})?s", ttl)):
        raise ValueError("invalid token response")
    seconds = float(ttl[:-1])
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("invalid lifetime")
    return token, seconds


def mint_app_check_token(force_refresh: bool = False) -> str | None:
    global _identity, _token, _expires, _retry_at, _last_failure, _last_diagnostic

    # 1) Preferência: Play Integrity do aparelho físico (RogLife).
    # Captura adb fica FORA do lock para não bloquear outros callers.
    # Em modo device, NÃO cair no debug exchange (CREATE de produção rejeita).
    try:
        from . import roglife_appcheck
        if roglife_appcheck.device_mode_enabled():
            device_error = None
            device_token = None

            # Device JWT is always streamed from the phone via ADB. Disk cache
            # never authorizes. force_refresh restarts Minute when prefs are stale.
            try:
                device_token = roglife_appcheck.obtain_token(force=force_refresh)
            except Exception as exc:
                device_error = exc
                logger.warning(
                    "App Check device indisponível (%s). Tentando renovar...",
                    type(exc).__name__,
                )

            if device_token and _bearer_still_valid(device_token):
                with _lock:
                    _last_failure, _last_diagnostic = None, None
                    left = 300.0
                    try:
                        import base64
                        pad = "=" * (-len(device_token.split(".")[1]) % 4)
                        payload = json.loads(
                            base64.urlsafe_b64decode(device_token.split(".")[1] + pad)
                        )
                        exp = float(payload.get("exp"))
                        left = max(30.0, exp - time.time() - 30.0)
                    except Exception:
                        pass
                    _token, _expires = device_token, time.monotonic() + min(left, 3600.0)
                return device_token
            # Bearer espelhado ainda pode servir se o JWT continuar válido.
            mirrored = _configured_bearer()
            if mirrored and _bearer_still_valid(mirrored):
                with _lock:
                    _last_failure, _last_diagnostic = None, None
                    _token, _expires = mirrored, time.monotonic() + 300.0
                return mirrored
            with _lock:
                _set_failure_diagnostic(_FAILURE_ATTESTATION)
                _token, _expires = None, 0.0
            if device_error is not None:
                logger.warning(
                    "Modo device ativo sem App Check utilizável (%s).",
                    type(device_error).__name__,
                )
            return None
    except Exception as exc:
        logger.warning(
            "App Check device provider falhou na carga (%s); tentando bearer/debug.",
            type(exc).__name__,
        )

    with _lock:
        values = _settings()
        bearer = _configured_bearer()
        _select_identity(values, bearer)
        digest = _settings_digest(values)

        # 2) Bearer administrativo explícito (env / espelho do device).
        if bearer:
            if _bearer_still_valid(bearer):
                _last_failure, _last_diagnostic = None, None
                _token, _expires = bearer, time.monotonic() + 300.0
                return bearer
            _set_failure_diagnostic(_FAILURE_INVALID)
            _token, _expires = None, 0.0
            return None
        if not all(values):
            # Optional integration: no warnings or network traffic when unconfigured.
            _last_failure = _FAILURE_NOT_CONFIGURED
            _last_diagnostic = {
                "category": _FAILURE_NOT_CONFIGURED,
                "http_status": None,
                "firebase_status": None,
                "message": _FAILURE_MESSAGES[_FAILURE_NOT_CONFIGURED],
                "retry_after_unix": None,
            }
            return None
        # Local operators can pause exchanges while Firebase debug-token quota
        # recovers (for example concurrent tools sharing the same project).
        if _is_paused():
            return None
        now = time.monotonic()
        if not force_refresh and _token and now < _expires:
            _last_failure, _last_diagnostic = None, None
            return _token
        # A denied attestation is not a transient network failure. Reusing the
        # same settings on every ordinary request cannot authorize that token.
        # A settings change resets this outcome above; an explicit refresh may
        # recheck external registration after the existing cooldown.
        if _last_failure in _NON_RETRYABLE_FAILURES and not force_refresh:
            return None
        if now < _retry_at:
            return None
        _token, _expires = None, 0.0
        try:
            with _exchange_file_lock():
                # Another process may have recorded a fresh cooldown since this
                # caller's local retry clock was last synchronized. Explicit
                # refresh permits rechecking only after that persisted cooldown.
                persisted = _load_persisted_state(digest)
                if persisted:
                    persisted_wait = persisted["retry_after_unix"] - time.time()
                    if persisted_wait > 0:
                        _restore_persisted_failure(digest, persisted)
                        return None
                    # Ordinary callers still cannot repeatedly retry permanent
                    # attestation/permission failures after the cooldown expires.
                    if (not force_refresh
                            and persisted["failure"] in _NON_RETRYABLE_FAILURES):
                        _restore_persisted_failure(digest, persisted)
                        return None
                token, ttl = _exchange(*values)
            # Measure from before the request; latency must not extend the TTL.
            expires = now + ttl - min(300.0, ttl * 0.1)
            if expires <= time.monotonic():
                raise ValueError("expired response")
            _token, _expires, _last_failure, _last_diagnostic = token, expires, None, None
            _save_persisted_state(digest, None, 0.0)
            return token
        except Exception as exc:
            # Do not log URLs, response bodies, exceptions or credential values.
            category = exc.category if isinstance(exc, AppCheckExchangeError) else (
                str(exc) if isinstance(exc, RuntimeError) and str(exc) in {
                _FAILURE_ATTESTATION, _FAILURE_PERMISSION, _FAILURE_QUOTA, _FAILURE_EXCHANGE,
                } else (
                _FAILURE_INVALID if isinstance(exc, ValueError) else _FAILURE_EXCHANGE
                )
            )
            http_status = exc.http_status if isinstance(exc, AppCheckExchangeError) else None
            firebase_status = exc.firebase_status if isinstance(exc, AppCheckExchangeError) else None
            cooldown = (
                _ATTESTATION_COOLDOWN_S if category in _NON_RETRYABLE_FAILURES
                else _QUOTA_COOLDOWN_S if category == _FAILURE_QUOTA
                else 60.0
            )
            _retry_at = time.monotonic() + cooldown
            retry_after_unix = time.time() + cooldown
            _set_failure_diagnostic(
                category, http_status=http_status, firebase_status=firebase_status,
                retry_after_unix=retry_after_unix)
            _save_persisted_state(
                digest, category, cooldown, http_status=http_status,
                firebase_status=firebase_status)
            if category in _NON_RETRYABLE_FAILURES:
                logger.warning(
                    "App Check indisponível (%s); repetição automática suspensa "
                    "para esta configuração. A política do servidor permanece válida.",
                    category,
                )
            else:
                logger.warning(
                    "App Check indisponível (%s); nova tentativa após %.0f segundos. "
                    "A política do servidor permanece válida.",
                    category,
                    cooldown,
                )
            return None


def get_app_check_header() -> dict[str, str]:
    token = mint_app_check_token()
    return {"X-Firebase-AppCheck": token} if token else {}


def ensure_app_check_fresh(*, min_left_s: int | None = None) -> dict:
    """Renew App Check when remaining life is below the campaign floor.

    Returns the post-check local status. Does not raise: callers keep the
    existing write-time App Check diagnosis when renewal cannot produce a token.
    """
    status = app_check_status()
    device = status.get("device") if isinstance(status.get("device"), dict) else {}
    try:
        floor = int(min_left_s if min_left_s is not None else device.get("min_left_s") or 600)
    except (TypeError, ValueError):
        floor = 600
    floor = max(60, floor)
    left_raw = device.get("left_s")
    try:
        left_s = float(left_raw) if left_raw is not None else None
    except (TypeError, ValueError):
        left_s = None
    if status.get("paused") or int(status.get("retry_after_seconds") or 0) > 0:
        return status
    needs_refresh = (
        not status.get("token_available")
        or left_s is None
        or left_s < floor
    )
    if not needs_refresh:
        return status
    if not (status.get("configured") or device.get("enabled")
            or status.get("configuration_present")):
        return status
    # Live ADB read; ensure_appcheck restarts Minute only when phone prefs are
    # below the floor. force=True here made every cold start wait minutes.
    mint_app_check_token(force_refresh=False)
    return app_check_status()


def is_app_check_rejection(text: str) -> bool:
    """Only explicit markers qualify; a generic 401/403 is not App Check evidence."""
    try:
        data = json.loads(text)
    except (ValueError, TypeError):
        return False
    if not isinstance(data, dict):
        return False
    detail = data.get("detail", data)
    if isinstance(detail, dict):
        detail = ' '.join(str(detail.get(k, '')) for k in ('error', 'code', 'message'))
    if not isinstance(detail, str):
        return False
    normalized = re.sub(r"[ _-]", "", detail).casefold()
    return 'appcheck' in normalized


def is_app_check_blocked_reason(value: object) -> bool:
    """True only for the explicit Minute ``X-Blocked-Reason: app_check`` marker."""
    return isinstance(value, str) and value.casefold() == "app_check"
