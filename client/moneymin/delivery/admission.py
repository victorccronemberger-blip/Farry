"""Local admission advice from explicit CREATE receipts, never from mint failure."""
from __future__ import annotations

from datetime import datetime
import re
from typing import Iterable

_CREATE_REJECTION = re.compile(
    r"POST /uploads falhou \((?:401|403|429)\):[^\n]*\[bloqueio: app_check\]"
)
_UPLOAD_ID = re.compile(r"[A-Za-z0-9_-]{1,160}")
_GUIDANCE = (
    "O último CREATE desta conta e organização foi recusado pelo Minute por App Check. "
    "Não há token App Check disponível; nenhum preparo ou envio foi iniciado. "
    "Use Integrações → Rechecar App Check após corrigir a autorização ou configuração. "
    "Os registros dos envios anteriores foram preservados."
)


def rejected_create_owners(accounts: Iterable, journals: Iterable[dict]) -> set[str]:
    """Scope historical evidence to owner/org; a later receipt clears that refusal."""
    owners = {(account.email.strip().casefold(), account.org_key) for account in accounts}
    latest: dict[tuple[str, str], tuple[float, bool]] = {}
    for row in journals:
        owner = row.get("account_email")
        if not isinstance(owner, str):
            continue
        key = (owner.strip().casefold(), row.get("org_key"))
        if key not in owners:
            continue
        upload_id = row.get("upload_id")
        accepted = isinstance(upload_id, str) and bool(_UPLOAD_ID.fullmatch(upload_id))
        rejected = (not upload_id and row.get("phase") == "create"
                    and row.get("state") == "failed"
                    and isinstance(row.get("error"), str)
                    and bool(_CREATE_REJECTION.search(row["error"])))
        if not accepted and not rejected:
            continue
        try:
            timestamp = datetime.fromisoformat(row["updated_at"].replace("Z", "+00:00"))
            if timestamp.tzinfo is None:
                continue
            when = timestamp.timestamp()
        except (KeyError, ValueError, TypeError, AttributeError, OverflowError):
            continue
        previous = latest.get(key)
        if previous is None or when > previous[0] or (when == previous[0] and rejected):
            latest[key] = when, bool(rejected)
    return {owner for (owner, _org), (_when, rejected) in latest.items() if rejected}


def campaign_create_blocker(accounts: Iterable) -> str | None:
    """Avoid repeating expensive preparation after a known remote refusal.

    Renews App Check first when remaining life is below the campaign floor so
    a stale local cache does not block start before per-video delivery runs.
    Only after that attempt fails does a prior CREATE App Check refusal block.
    No inferred organization policy, header mutation, or receipt deletion.
    Configuration alone never makes App Check mandatory.
    """
    from .. import appcheck, upload

    accounts = list(accounts)
    if not accounts:
        return None
    # Status-only reads never mint; renew here so admission can clear an
    # expired/near-expiry cache before consulting historical refusals.
    status = appcheck.ensure_app_check_fresh()
    if status.get("token_available"):
        return None
    if not _has_journal_files():
        return None
    rejected = rejected_create_owners(accounts, upload.list_sidecars())
    if rejected:
        return _GUIDANCE + " Contas afetadas: " + ", ".join(sorted(rejected))
    return None


def _has_journal_files() -> bool:
    """Read-only existence probe; an empty profile needs no migration or lease.

    A real receipt is still read by the authoritative, locked journal decoder.
    Only genuine absence is ignored; unreadable stores remain an admission error.
    """
    from .. import config

    for root in (config.DATA_DIR, config.MEDIA_DATA_DIR):
        try:
            if any(path.name.lower().endswith(".json") for path in (root / "sidecars").iterdir()):
                return True
        except FileNotFoundError:
            continue
    return False
