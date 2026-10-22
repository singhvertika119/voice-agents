"""Thin Supabase (PostgREST) client for the worker. Uses the service-role key, so it bypasses row-level
security: every call here must set tenant_id explicitly. DB mode is opt-in: it turns on only when AGENT_ID
is a UUID, so YAML agents and the benchmark never touch a database (docs/decision.md D-014)."""
from __future__ import annotations

import logging
import os
import re

import httpx

log = logging.getLogger("db")
_UUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$", re.I)


def is_agent_uuid(value: str | None) -> bool:
    return bool(value and _UUID.match(value))


def _client() -> httpx.AsyncClient:
    url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    return httpx.AsyncClient(base_url=f"{url}/rest/v1", timeout=10,
                             headers={"apikey": key, "Authorization": f"Bearer {key}", "Prefer": "return=representation"})


def parse_room(room: str) -> tuple[str, str] | None:
    """Rooms created by the dashboard test panel are named 'live-<uuid>-<rand>' (published version)
    or 'draft-<uuid>-<rand>' (latest version, even if unpublished). Returns (mode, agent_id).

    Phone calls use the same names: the SIP dispatch rule sets room_prefix to 'live-<uuid>-' and LiveKit appends the
    caller's number and a random suffix (scripts/make_dispatch_rule.py), so one rule per agent routes the call."""
    m = re.match(r"^(live|draft)-([0-9a-f-]{36})(?:-|$)", room, re.I)
    return (m.group(1).lower(), m.group(2)) if m else None


async def fetch_latest(agent_id: str) -> dict:
    """Latest version (draft or not): what the 'Test the draft' panel talks to."""
    async with _client() as c:
        r = await c.get("/agents", params={"id": f"eq.{agent_id}", "select": "id,name,tenant_id,published_version"})
        r.raise_for_status()
        if not r.json():
            raise RuntimeError(f"Agent {agent_id} not found")
        agent = r.json()[0]
        r = await c.get("/agent_versions", params={"agent_id": f"eq.{agent_id}", "select": "version,config",
                                                   "order": "version.desc", "limit": "1"})
        r.raise_for_status()
        v = r.json()[0]
        return {"agent": agent, "version": v["version"], "config": v["config"]}


async def fetch_published(agent_id: str) -> dict:
    """Returns {agent: {...}, version: int, config: {...}} for the agent's published version."""
    async with _client() as c:
        r = await c.get("/agents", params={"id": f"eq.{agent_id}", "select": "id,name,tenant_id,published_version"})
        r.raise_for_status()
        rows = r.json()
        if not rows or not rows[0]["published_version"]:
            raise RuntimeError(f"Agent {agent_id} has no published version. Publish one in the dashboard.")
        agent = rows[0]
        r = await c.get("/agent_versions", params={"agent_id": f"eq.{agent_id}",
                                                   "version": f"eq.{agent['published_version']}", "select": "config"})
        r.raise_for_status()
        return {"agent": agent, "version": agent["published_version"], "config": r.json()[0]["config"]}


async def start_call(tenant_id: str, agent_id: str, version: int, room: str, caller_number: str | None = None,
                     consent: dict | None = None) -> str | None:
    base = {"tenant_id": tenant_id, "agent_id": agent_id, "agent_version": version, "livekit_room": room}
    full = {**base, "caller_number": caller_number, "consent": consent, "channel": "phone" if caller_number else "web"}
    for row in (full, base):   # the second form works on a database that has not had the newest update applied yet
        try:
            async with _client() as c:
                r = await c.post("/calls", json=row)
                r.raise_for_status()
                return r.json()[0]["id"]
        except Exception as e:  # a database problem must never stop a call (architecture: call path survives DB outage)
            log.warning("could not record call start (%s)", e)
    return None


_OLD_COLUMNS = ("ended_at", "duration_s", "avg_reply_ms", "cost_usd", "cost_breakdown", "language", "outcome", "summary")
_RECORDING_COLUMNS = _OLD_COLUMNS + ("structured", "consent", "contact_id", "tool_calls")   # without the 0006 columns


async def finish_call(call_id: str | None, tenant_id: str, fields: dict, turns: list[dict]) -> None:
    if not call_id:
        return
    for payload in (fields, {k: v for k, v in fields.items() if k in _RECORDING_COLUMNS}, {k: v for k, v in fields.items() if k in _OLD_COLUMNS}):
        try:
            async with _client() as c:
                (await c.patch("/calls", params={"id": f"eq.{call_id}"}, json=payload)).raise_for_status()
                if turns:
                    rows = [{**t, "call_id": call_id, "tenant_id": tenant_id} for t in turns]
                    (await c.post("/call_turns", json=rows)).raise_for_status()
            return
        except Exception as e:
            log.warning("could not save call %s (%s)", call_id, e)


async def add_turn(call_id: str | None, tenant_id: str, turn: dict) -> None:
    """Saved as each turn is committed (fire-and-forget), so a crash loses at most the last turn."""
    if not call_id:
        return
    try:
        async with _client() as c:
            (await c.post("/call_turns", json={**turn, "call_id": call_id, "tenant_id": tenant_id})).raise_for_status()
    except Exception as e:
        log.warning("could not save turn %s of call %s: %s", turn.get("seq"), call_id, e)


async def fetch_version(agent_id: str, version: int) -> dict:
    """A specific version (used by test runs, which check the exact version a person is about to publish)."""
    async with _client() as c:
        r = await c.get("/agents", params={"id": f"eq.{agent_id}", "select": "id,name,tenant_id,published_version"})
        r.raise_for_status()
        if not r.json():
            raise RuntimeError(f"Agent {agent_id} not found")
        agent = r.json()[0]
        r = await c.get("/agent_versions", params={"agent_id": f"eq.{agent_id}", "version": f"eq.{version}", "select": "version,config"})
        r.raise_for_status()
        if not r.json():
            raise RuntimeError(f"Version {version} not found")
        return {"agent": agent, "version": version, "config": r.json()[0]["config"]}
