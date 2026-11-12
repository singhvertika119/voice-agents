"""The worker's database helpers: which version a call gets, and that call-path writes never raise."""
from __future__ import annotations

import asyncio

import pytest
from agent_worker import db

A = "22222222-2222-2222-2222-222222222222"
AGENT = {"id": A, "name": "Clinic", "tenant_id": "t1", "published_version": 3}
VERSIONS = {1: {"greeting": "v1"}, 3: {"greeting": "v3"}, 4: {"greeting": "draft"}}


@pytest.fixture
def fake_db(monkeypatch):
    seen: list[tuple[str, dict]] = []

    async def select(table, **params):
        seen.append((table, params))
        if table == "agents":
            return [AGENT] if params["id"] == f"eq.{A}" else []
        if "version" in params:
            v = int(params["version"].removeprefix("eq."))
            return [{"version": v, "config": VERSIONS[v]}] if v in VERSIONS else []
        top = max(VERSIONS)
        return [{"version": top, "config": VERSIONS[top]}]
    monkeypatch.setattr(db.supa, "select", select)
    return seen


def test_published_latest_and_specific_versions(fake_db):
    assert asyncio.run(db.fetch_published(A))["config"] == {"greeting": "v3"}
    latest = asyncio.run(db.fetch_latest(A))
    assert latest["version"] == 4 and latest["agent"]["name"] == "Clinic"
    assert asyncio.run(db.fetch_version(A, 1))["config"] == {"greeting": "v1"}


def test_missing_agent_or_version_says_so(fake_db, monkeypatch):
    with pytest.raises(RuntimeError, match="not found"):
        asyncio.run(db.fetch_published("33333333-3333-3333-3333-333333333333"))
    with pytest.raises(RuntimeError, match="Version 9 not found"):
        asyncio.run(db.fetch_version(A, 9))
    monkeypatch.setitem(AGENT, "published_version", None)
    with pytest.raises(RuntimeError, match="no published version"):
        asyncio.run(db.fetch_published(A))


def test_call_writes_never_raise(monkeypatch):
    async def down(*a, **k):
        raise RuntimeError("database unreachable")
    monkeypatch.setattr(db.supa, "insert", down)
    monkeypatch.setattr(db.supa, "update", down)
    assert asyncio.run(db.start_call("t1", A, 3, "live-x")) is None
    asyncio.run(db.finish_call("c1", {"outcome": "resolved"}))
    asyncio.run(db.add_turn("c1", "t1", {"seq": 0, "speaker": "agent", "text": "hi"}))
    asyncio.run(db.replace_turn_text("c1", 0, "new", "old"))


def test_writes_carry_the_right_fields(monkeypatch):
    out: list[tuple] = []

    async def insert(table, row):
        out.append(("insert", table, row))
        return [{"id": "c1"}]

    async def update(table, match, values):
        out.append(("update", table, match, values))
        return []
    monkeypatch.setattr(db.supa, "insert", insert)
    monkeypatch.setattr(db.supa, "update", update)
    assert asyncio.run(db.start_call("t1", A, 3, "live-x", "+919812345678", {"notice": "x"})) == "c1"
    assert out[0][2]["channel"] == "phone" and out[0][2]["tenant_id"] == "t1"
    asyncio.run(db.finish_call(None, {"outcome": "resolved"}))   # no call row: nothing written
    asyncio.run(db.finish_call("c1", {"outcome": "resolved"}))
    asyncio.run(db.replace_turn_text("c1", 2, "new", "old"))
    assert out[1:] == [("update", "calls", {"id": "c1"}, {"outcome": "resolved"}),
                       ("update", "call_turns", {"call_id": "c1", "seq": 2}, {"text": "new", "text_live": "old"})]
