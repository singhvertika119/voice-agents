"""Tests for Phase 4 Custom Tools resilience (Bug 2.13)."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest
from agent_worker import custom_tools
from agent_worker.tools import CallState


def test_404_does_not_trip_circuit_breaker(monkeypatch):
    monkeypatch.setattr(custom_tools, "assert_public_url", lambda url, **kwargs: None)
    tool = {
        "tenant_id": "t1",
        "name": "check_order",
        "endpoint": "https://api.example.com/orders",
        "method": "GET",
        "timeout_ms": 2000,
    }
    breaker_key = f"{tool['tenant_id']}:{tool['endpoint']}"

    # Reset circuit breaker state for testing
    custom_tools._fails.clear()
    custom_tools._open_until.clear()

    mock_resp = MagicMock()
    mock_resp.status_code = 404
    mock_resp.text = '{"error": "order not found"}'

    async def fake_get(*args, **kwargs):
        return mock_resp

    fake_client = AsyncMock()
    fake_client.get = fake_get

    # Call 4 times with 404s
    for i in range(4):
        ok, res = asyncio.run(custom_tools.call_endpoint(tool, None, {"id": f"ord_{i}"}, f"idem_{i}", client=fake_client))
        assert ok is False
        assert "the system answered with an error (404)" in res

    # Breaker should NOT be open
    assert not custom_tools._breaker_open(breaker_key)


def test_500_and_timeouts_trip_circuit_breaker(monkeypatch):
    monkeypatch.setattr(custom_tools, "assert_public_url", lambda url, **kwargs: None)
    tool = {
        "tenant_id": "t2",
        "name": "check_inventory",
        "endpoint": "https://api.example.com/inventory",
        "method": "GET",
        "timeout_ms": 2000,
    }
    breaker_key = f"{tool['tenant_id']}:{tool['endpoint']}"

    custom_tools._fails.clear()
    custom_tools._open_until.clear()

    fake_client = AsyncMock()
    fake_client.get.side_effect = httpx.TimeoutException("timed out")

    for i in range(3):
        ok, res = asyncio.run(custom_tools.call_endpoint(tool, None, {"item": "sku1"}, f"idem_{i}", client=fake_client))
        assert ok is False

    # Breaker should be open after 3 timeouts
    assert custom_tools._breaker_open(breaker_key)
