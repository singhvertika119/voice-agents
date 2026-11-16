"""The worker's reads and writes for agents, versions, calls and turns, through the shared Supabase client (vp_core.supa).
That client uses the service-role key, so it bypasses row-level security: every call here must set tenant_id explicitly.
DB mode is opt-in: it turns on only when AGENT_ID is a UUID or the room names an agent, so YAML agents and the benchmark
never touch a database (docs/decision.md D-014).

Writes on the call path never raise: a database problem must not stop a call (architecture: call path survives DB outage)."""
from __future__ import annotations

import logging
import re

from vp_core import supa

log = logging.getLogger("db")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def is_agent_uuid(value: str | None) -> bool:
    return bool(value and _UUID.match(value))


def parse_room(room: str) -> tuple[str, str] | None:
    """Rooms created by the dashboard test panel are named 'live-<uuid>-<rand>' (published version)
    or 'draft-<uuid>-<rand>' (latest version, even if unpublished). Returns (mode, agent_id).

    Phone calls use the same names: the SIP dispatch rule sets room_prefix to 'live-<uuid>-' and LiveKit appends the
    caller's number and a random suffix (scripts/make_dispatch_rule.py), so one rule per agent routes the call."""
    m = re.match(r"^(live|draft)-([0-9a-f-]{36})(?:-|$)", room, re.I)
    return (m.group(1).lower(), m.group(2)) if m else None


async def _agent(agent_id: str) -> dict:
    rows = await supa.select("agents", id=f"eq.{agent_id}", select="id,name,tenant_id,published_version")
    if not rows:
        raise RuntimeError(f"Agent {agent_id} not found")
    return rows[0]


async def _version(agent: dict, version: int | None) -> dict:
    """One version's config; version=None prefers an active draft, else published_version, else newest."""
    if version is not None:
        rows = await supa.select("agent_versions", agent_id=f"eq.{agent['id']}", select="version,config", version=f"eq.{version}")
    else:
        # Check for active draft first
        rows = await supa.select("agent_versions", agent_id=f"eq.{agent['id']}", select="version,config", status="eq.draft", order="version.desc", limit="1")
        if not rows and agent.get("published_version"):
            # If no draft, use the published version (even if newer archived versions exist)
            rows = await supa.select("agent_versions", agent_id=f"eq.{agent['id']}", select="version,config", version=f"eq.{agent['published_version']}", limit="1")
        if not rows:
            rows = await supa.select("agent_versions", agent_id=f"eq.{agent['id']}", select="version,config", order="version.desc", limit="1")
    if not rows:
        raise RuntimeError(f"Version {version} not found" if version is not None else f"Agent {agent['id']} has no versions")
    return {"agent": agent, "version": rows[0]["version"], "config": rows[0]["config"]}


async def fetch_latest(agent_id: str) -> dict:
    """Latest version (draft or not): what the 'Test the draft' panel talks to. Returns {agent, version, config}."""
    return await _version(await _agent(agent_id), None)


async def fetch_published(agent_id: str) -> dict:
    """The agent's published version. Returns {agent, version, config}."""
    agent = await _agent(agent_id)
    if not agent["published_version"]:
        raise RuntimeError(f"Agent {agent_id} has no published version. Publish one in the dashboard.")
    return await _version(agent, agent["published_version"])


async def fetch_version(agent_id: str, version: int) -> dict:
    """A specific version (used by test runs, which check the exact version a person is about to publish)."""
    return await _version(await _agent(agent_id), version)


async def start_call(tenant_id: str, agent_id: str, version: int, room: str, caller_number: str | None = None,
                     consent: dict | None = None) -> str | None:
    row = {"tenant_id": tenant_id, "agent_id": agent_id, "agent_version": version, "livekit_room": room,
           "caller_number": caller_number, "consent": consent, "channel": "phone" if caller_number else "web"}
    try:
        return (await supa.insert("calls", row))[0]["id"]
    except Exception as e:  # noqa: BLE001
        log.warning("could not record call start (%s)", e)
        return None


async def finish_call(call_id: str | None, fields: dict) -> None:
    if not call_id:
        return
    try:
        await supa.update("calls", {"id": call_id}, fields)
    except Exception as e:  # noqa: BLE001
        log.warning("could not save call %s (%s)", call_id, e)


async def add_turn(call_id: str | None, tenant_id: str, turn: dict) -> None:
    """Saved as each turn is committed (fire-and-forget), so a crash loses at most the last turn."""
    if not call_id:
        return
    try:
        await supa.insert("call_turns", {**turn, "call_id": call_id, "tenant_id": tenant_id}, timeout=10)
    except Exception as e:  # noqa: BLE001
        log.warning("could not save turn %s of call %s: %s", turn.get("seq"), call_id, e)


async def replace_turn_text(call_id: str | None, seq: int, text: str, live_text: str) -> None:
    """Swap in the re-transcribed text (D-097); what was heard live is kept in text_live."""
    if not call_id:
        return
    try:
        res = await supa.update("call_turns", {"call_id": call_id, "seq": seq}, {"text": text, "text_live": live_text})
        if not res:
            log.warning("replace_turn_text: 0 rows updated for call %s turn %s", call_id, seq)
    except Exception as e:  # noqa: BLE001
        log.info("turn %s of call %s: %s", seq, call_id, str(e)[:120])
