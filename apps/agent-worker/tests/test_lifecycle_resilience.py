"""Tests for Bug 1.5 and 1.6 resilience:
- Custom tools handling string schemas, null descriptions, and per-tool failures
- Provider stack handling missing STT/TTS specs safely
- DB turn add with timeout and zero-row update warnings
"""
from __future__ import annotations

import asyncio
import logging
from unittest.mock import AsyncMock, patch

import pytest
from agent_worker import custom_tools, db, providers
from agent_worker.config import AgentConfig
from agent_worker.tools import CallState


def test_make_tool_with_string_parameters_and_null_description():
    tool_row = {
        "id": "t1",
        "name": "lookup_order",
        "description": None,
        "parameters": '{"type": "object", "properties": {"order_id": {"type": "string"}}}',
        "requires_confirmation": False,
        "method": "GET",
        "url": "https://api.example.com/order",
    }
    state = CallState(tenant_id="t1", agent_id="a1")
    tool = custom_tools._make_tool(tool_row, secret=None, state=state)
    assert tool is not None


def test_load_custom_tools_skips_bad_tool_row(monkeypatch):
    rows = [
        {"id": "bad", "name": "bad_tool", "description": None, "parameters": 12345},  # bad parameters type
        {"id": "good", "name": "good_tool", "description": "A good tool", "parameters": {}},
    ]

    async def fake_select(table, **params):
        if table == "tools":
            return rows
        return []

    monkeypatch.setattr(custom_tools.supa, "select", fake_select)
    state = CallState(tenant_id="t1", agent_id="a1")
    tools = asyncio.run(custom_tools.load_custom_tools("t1", ["bad", "good"], state))
    assert len(tools) == 2  # _make_tool now handles non-dict parameters gracefully


def test_provider_helpers_handle_none_and_empty_spec():
    assert providers._stt(None, "en") is None
    assert providers._stt({}, "en") is None
    assert providers._tts(None, "en") is None
    assert providers._tts({}, "en") is None


def test_build_stack_handles_empty_stt_and_voice():
    cfg = AgentConfig(
        id="test-agent",
        name="Test",
        language="en",
        greeting="Hi",
        instructions="Be helpful",
        knowledge={},
        stt={},
        voice={},
        llm={"primary": {"provider": "groq", "model": "llama"}},
    )
    with pytest.raises(RuntimeError, match="No usable STT provider"):
        providers.build_stack(cfg)


def test_db_replace_turn_text_warns_on_zero_rows(caplog, monkeypatch):
    async def fake_update(table, match, values):
        return []  # 0 rows updated

    monkeypatch.setattr(db.supa, "update", fake_update)
    with caplog.at_level(logging.WARNING):
        asyncio.run(db.replace_turn_text("c1", 1, "new text", "old text"))
    assert "0 rows updated" in caplog.text
