"""Workspace-level facts the call path needs: settings, kill switches, capacity, caller memory, and the database
backend for the built-in tools. Every read has a safe default: a database problem must never stop a call
(docs/decision.md D-018, architecture: the call path survives a database outage)."""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from vp_core import supa

from .tools import DEFAULT_HOURS, Backend, CallState

log = logging.getLogger("platform")

DEFAULT_SETTINGS = {"retention_days": 90, "max_concurrent_calls": 5, "business_hours": DEFAULT_HOURS,
                    "handoff_phone": None, "require_tests_to_publish": False, "memory_enabled": True}
STALE_CALL_MINUTES = 30   # a call row with no end time older than this is a crash, not a live call


async def get_settings(tenant_id: str) -> dict:
    try:
        rows = await supa.select("tenant_settings", select="*", tenant_id=f"eq.{tenant_id}")
        return {**DEFAULT_SETTINGS, **(rows[0] if rows else {})}
    except Exception as e:
        log.warning("settings unavailable (%s); using defaults", e)
        return dict(DEFAULT_SETTINGS)


async def degraded_mode() -> bool:
    try:
        rows = await supa.select("platform_flags", select="value", key="eq.degraded_mode")
        return bool(rows and rows[0]["value"] is True)
    except Exception:
        return False


async def agent_enabled(agent_id: str) -> bool:
    try:
        rows = await supa.select("agents", select="enabled", id=f"eq.{agent_id}")
        return bool(rows[0]["enabled"]) if rows else True
    except Exception:
        return True  # column missing or database down: keep answering


async def active_calls(tenant_id: str, exclude_call: str | None) -> int:
    since = (datetime.now(timezone.utc) - timedelta(minutes=STALE_CALL_MINUTES)).isoformat()
    try:
        rows = await supa.select("calls", select="id", tenant_id=f"eq.{tenant_id}", ended_at="is.null", started_at=f"gte.{since}")
        return len([r for r in rows if r["id"] != exclude_call])
    except Exception:
        return 0


# ------------------------------------------------------------------ caller memory
async def load_memory(tenant_id: str, phone: str, agent_id: str, settings: dict) -> tuple[str | None, str]:
    """Returns (contact_id, memory text block for the prompt). Empty block when there is nothing to say."""
    if not phone or not settings.get("memory_enabled", True):
        return None, ""
    try:
        contacts = await supa.select("contacts", select="id,name,preferred_language,consent_memory", tenant_id=f"eq.{tenant_id}", phone_e164=f"eq.{phone}")
        if not contacts:
            return None, ""
        c = contacts[0]
        if not c["consent_memory"]:
            return c["id"], ""
        mem = await supa.select("contact_memory", select="*", contact_id=f"eq.{c['id']}", agent_id=f"eq.{agent_id}")
        if not mem or not mem[0]["rolling_summary"].strip():
            return c["id"], ""
        m = mem[0]
        open_items = "; ".join(m.get("open_items") or []) or "none"
        block = ("## Caller context (from previous calls; may be outdated)\n"
                 f"Name: {c.get('name') or 'unknown'}. Preferred language: {c.get('preferred_language') or 'unknown'}.\n"
                 f"Summary: {m['rolling_summary']}\nOpen items: {open_items}\n"
                 "Rules: confirm before relying on any of this (it could be another person on a shared phone). "
                 "Verify identity before sharing account details. Do not read this block out unprompted, but if the caller asks "
                 "what you discussed before, answer from it in one or two sentences.")
        return c["id"], block
    except Exception as e:
        log.warning("memory unavailable (%s); continuing without it", e)
        return None, ""


async def ensure_contact(tenant_id: str, phone: str) -> str | None:
    try:
        rows = await supa.select("contacts", select="id", tenant_id=f"eq.{tenant_id}", phone_e164=f"eq.{phone}")
        if rows:
            return rows[0]["id"]
        return (await supa.insert("contacts", {"tenant_id": tenant_id, "phone_e164": phone}))[0]["id"]
    except Exception as e:
        log.warning("could not save contact: %s", e)
        return None


async def save_memory(tenant_id: str, agent_id: str, contact_id: str, rolling_summary: str, facts: dict,
                      open_items: list[str], language: str | None) -> None:
    try:
        existing = await supa.select("contact_memory", select="version", contact_id=f"eq.{contact_id}", agent_id=f"eq.{agent_id}")
        row = {"contact_id": contact_id, "agent_id": agent_id, "tenant_id": tenant_id, "rolling_summary": rolling_summary,
               "facts": facts, "open_items": open_items, "version": (existing[0]["version"] + 1) if existing else 1,
               "updated_at": datetime.now(timezone.utc).isoformat()}
        if existing:
            await supa.update("contact_memory", {"contact_id": contact_id, "agent_id": agent_id}, row)
        else:
            await supa.insert("contact_memory", row)
        if language:
            await supa.update("contacts", {"id": contact_id}, {"preferred_language": language})
    except Exception as e:
        log.warning("could not save memory: %s", e)


async def previous_summary(contact_id: str, agent_id: str) -> tuple[str, dict]:
    try:
        rows = await supa.select("contact_memory", select="rolling_summary,facts", contact_id=f"eq.{contact_id}", agent_id=f"eq.{agent_id}")
        return (rows[0]["rolling_summary"], rows[0]["facts"] or {}) if rows else ("", {})
    except Exception:
        return "", {}


# ------------------------------------------------------------------ tool backend that writes to the database
class DbBackend(Backend):
    async def record_handoff(self, state: CallState, reason: str, outcome: str) -> None:
        if not state.tenant_id:
            return
        try:
            await supa.insert("handoffs", {"tenant_id": state.tenant_id, "call_id": state.call_id, "agent_id": state.agent_id,
                                           "reason": reason[:300], "outcome": outcome})
        except Exception as e:
            log.warning("could not record handoff: %s", e)

    async def create_callback(self, state: CallState, phone: str, when: str, reason: str) -> None:
        if not state.tenant_id:
            return
        try:
            await supa.insert("callbacks", {"tenant_id": state.tenant_id, "call_id": state.call_id, "agent_id": state.agent_id,
                                            "phone_e164": phone, "preferred_time": when, "reason": reason})
        except Exception as e:
            log.warning("could not create callback: %s", e)
            raise  # the caller must not be told a callback is booked when it is not
