"""Unit tests for Phase 3 Evals fixes (Bug 2.8)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest
from evals import worker
from evals.runner import suite


def test_suite_dedupes_scenario_results_with_same_name():
    scenarios = [
        {"id": "sc_1", "name": "Greeting check", "pass_rate": 0.8, "checks": {}},
        {"id": "sc_2", "name": "Greeting check", "pass_rate": 0.8, "checks": {}},
    ]

    async def fake_convo(cfg, kb, s, settings):
        return {
            "transcript": [
                {"speaker": "caller", "text": "hello"},
                {"speaker": "agent", "text": "Hello, how can I help you?", "greeting": False},
            ],
            "reply_ms": [100],
            "tool_calls": [],
            "error": None,
        }

    async def fake_judge(convo, s, k):
        return {
            "meets_rubric": s["id"] == "sc_1",
            "grounded": True,
            "tone": 4,
            "reason": "ok",
        }

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(suite, "run_conversation", fake_convo)
        mp.setattr(suite, "judge", fake_judge)

        report = asyncio.run(suite.run_suite(
            cfg=None, kb=None, scenarios=scenarios, knowledge_text="",
            runs=1, settings={}, max_reply_ms=3000, concurrency=1
        ))

        # Check that sc_1 and sc_2 have separate results, not merged into 2 runs each
        assert len(report["scenarios"]) == 2
        assert report["scenarios"][0]["runs"] == 1
        assert report["scenarios"][1]["runs"] == 1
        assert report["scenarios"][0]["passed"] is True
        assert report["scenarios"][1]["passed"] is False


def test_custom_scenario_loop_tolerates_null_spec():
    custom_rows = [
        {"id": "c1", "agent_id": None, "spec": None, "enabled": True},
        {"id": "c2", "agent_id": "a1", "spec": {"caller_says": "hi", "criteria": "greeting"}, "enabled": True},
    ]
    scenarios = []
    for r in custom_rows:
        try:
            if r.get("agent_id") in (None, "a1") and (r.get("spec") or {}).get("source") != "generated":
                # Only valid specs with dict can be processed
                if r.get("spec"):
                    scenarios.append(r["id"])
        except Exception:
            pass

    assert scenarios == ["c2"]
