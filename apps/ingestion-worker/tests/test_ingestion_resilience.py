"""Unit tests for Phase 3 Ingestion fixes (Bugs 2.2, 2.3, 2.4, 2.6)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from ingestion import main, pipeline
from ingestion.parsers import Parsed


def test_reset_stuck_filters_by_updated_at(monkeypatch):
    calls = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def patch(self, path, params, json):
            calls.append((path, params, json))
            mock_resp = MagicMock()
            mock_resp.status_code = 200
            mock_resp.json.return_value = []
            return mock_resp

    monkeypatch.setattr(main.supa, "client", lambda: FakeClient())
    asyncio.run(main.reset_stuck())

    assert len(calls) == 1
    path, params, json = calls[0]
    assert path == "/rest/v1/knowledge_sources"
    assert "updated_at" in params
    assert params["updated_at"].startswith("lt.")
    assert params["status"] == "in.(parsing,indexing,testing)"


def test_purge_recordings_filters_per_tenant(monkeypatch):
    settings = [{"tenant_id": "t1", "retention_days": 30}, {"tenant_id": "t2", "retention_days": 60}]
    select_calls = []
    removed = []

    async def fake_select(table, **kwargs):
        if table == "tenant_settings":
            return settings
        if table == "calls":
            select_calls.append((table, kwargs))
            return [{"id": "c1", "recording_path": "t1/c1.m4a"}]
        return []

    async def fake_remove(bucket, paths):
        removed.append((bucket, paths))

    async def fake_update(table, match, values):
        pass

    monkeypatch.setattr(main.supa, "select", fake_select)
    monkeypatch.setattr(main.supa, "remove", fake_remove)
    monkeypatch.setattr(main.supa, "update", fake_update)

    gone = asyncio.run(main.purge_recordings())
    assert len(select_calls) == 2
    # Verify tenant filter and age filter are present in select calls
    for _, kwargs in select_calls:
        assert "tenant_id" in kwargs
        assert "started_at" in kwargs
        assert kwargs["started_at"].startswith("lt.")
        assert kwargs.get("order") == "started_at.asc"


def test_refresh_websites_selects_ready_and_needs_review(monkeypatch):
    queries = []

    async def fake_select(table, **kwargs):
        queries.append((table, kwargs))
        return []

    monkeypatch.setattr(pipeline.supa, "select", fake_select)
    asyncio.run(pipeline.refresh_websites())

    assert len(queries) == 1
    _, kwargs = queries[0]
    assert kwargs.get("status") == "in.(ready,needs_review)"


def test_quality_gate_skipped_on_generation_failure(monkeypatch):
    async def fake_chat(*args, **kwargs):
        raise RuntimeError("Groq 429 rate limit exceeded")

    monkeypatch.setattr(pipeline.llm_chat, "chat", fake_chat)
    chunks = [pipeline.Chunk(idx=0, section="About", content="We are open daily.")]

    res = asyncio.run(pipeline.quality_gate("t1", "s1", chunks, faq=False))
    assert res.get("skipped") is True
    assert res.get("hit_rate") == 0.0
    assert "model unavailable" in res.get("error", "")
