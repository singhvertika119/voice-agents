"""Each workspace's own OpenAI key (bring your own key, docs/decision.md D-124).

The dashboard saves the key encrypted in tenant_api_keys; this module reads and decrypts it for server code only.
A job (a call, a test run) loads its workspace's key once and sets it with use(); code further down reads current()
instead of an environment variable. No key, or a key that is out of credits or invalid, means the free Groq model
is used instead, so nothing stops working.
"""
from __future__ import annotations

import logging
import time
from contextvars import ContextVar
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone

from . import secrets, supa

log = logging.getLogger("tenant_keys")

CACHE_S = 60                     # a key saved in Settings is picked up within a minute
RETRY_AFTER = timedelta(hours=1)  # a key marked "no credits" is tried again after this, in work that is not a live call


@dataclass(frozen=True)
class TenantKey:
    tenant_id: str
    value: str
    status: str                    # ok | no_credits | invalid | unchecked
    checked_at: datetime | None = None
    use_for: str = "calls"         # calls | everything (D-125): background work uses the key only with "everything"

    def live_ok(self) -> bool:
        """Use it in a live call? Only when it is not known to fail: a failing first attempt would delay every reply."""
        return self.status in ("ok", "unchecked")

    def for_background(self) -> bool:
        """Use it for summaries, the test caller and reviewer, quality checks? Only when the owner chose "everything"."""
        return self.use_for == "everything" and self.worth_trying()

    def worth_trying(self) -> bool:
        """Use it in background work (summaries, tests)? Also retry a failed key now and then: credits may have been added."""
        if self.status == "invalid":   # only a new key fixes that, and saving one resets the status
            return False
        if self.live_ok():
            return True
        return self.checked_at is None or datetime.now(timezone.utc) - self.checked_at > RETRY_AFTER


_current: ContextVar[TenantKey | None] = ContextVar("tenant_openai_key", default=None)
_cache: dict[str, tuple[float, TenantKey | None]] = {}


def _parse_time(s: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(s) if s else None
    except ValueError:
        return None


async def load(tenant_id: str | None) -> TenantKey | None:
    """The workspace's OpenAI key, or None. Never raises: a missing table or a bad key just means no key."""
    if not tenant_id:
        return None
    hit = _cache.get(tenant_id)
    if hit and time.monotonic() - hit[0] < CACHE_S:
        return hit[1]
    key = None
    try:
        try:
            rows = await supa.select("tenant_api_keys", select="secret_enc,status,checked_at,use_for",
                                     tenant_id=f"eq.{tenant_id}", provider="eq.openai")
        except Exception:  # noqa: BLE001  database without 0012: the key still works for calls
            rows = await supa.select("tenant_api_keys", select="secret_enc,status,checked_at",
                                     tenant_id=f"eq.{tenant_id}", provider="eq.openai")
        if rows:
            r = rows[0]
            key = TenantKey(tenant_id, secrets.decrypt(r["secret_enc"]), r["status"], _parse_time(r.get("checked_at")),
                            r.get("use_for") or "calls")
    except Exception as e:  # noqa: BLE001
        log.warning("workspace %s: OpenAI key not loaded (%s); using the free model", tenant_id, str(e)[:120])
        key = None
    _cache[tenant_id] = (time.monotonic(), key)
    return key


def use(key: TenantKey | None) -> None:
    """Set the key for the rest of this job (and the tasks it starts)."""
    _current.set(key)


def current() -> TenantKey | None:
    return _current.get()


def classify(status_code: int, body: str) -> str | None:
    """What an OpenAI error says about the key: invalid, no_credits, or None when it is a passing problem."""
    if status_code == 401:
        return "invalid"
    if status_code == 429 and ("insufficient_quota" in body or "credit_balance" in body or "billing" in body):
        return "no_credits"
    return None


async def record(key: TenantKey, status: str) -> TenantKey:
    """Save what was learned about the key, so Settings can show it and live calls stop trying a failing key."""
    if status == key.status and status == "ok":
        return key
    now = datetime.now(timezone.utc)
    new = replace(key, status=status, checked_at=now)
    _cache[key.tenant_id] = (time.monotonic(), new)
    if _current.get() is key:
        _current.set(new)
    try:
        await supa.update("tenant_api_keys", {"tenant_id": key.tenant_id, "provider": "openai"},
                          {"status": status, "checked_at": now.isoformat()})
    except Exception as e:  # noqa: BLE001
        log.warning("could not save key status for %s: %s", key.tenant_id, str(e)[:120])
    if status != "ok":
        log.warning("workspace %s: OpenAI key is %s; using the free model", key.tenant_id, status)
    return new
