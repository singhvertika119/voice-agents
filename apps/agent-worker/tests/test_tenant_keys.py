"""Bring your own OpenAI key (D-124): which key is used, and the free model takes over when the key fails."""
from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta, timezone

import httpx
import pytest
from vp_core import llm_chat, secrets, tenant_keys
from vp_core.tenant_keys import TenantKey

T = "11111111-1111-1111-1111-111111111111"


@pytest.fixture(autouse=True)
def env(monkeypatch):
    monkeypatch.setenv("TOOL_SECRET_KEY", secrets.new_key())
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    tenant_keys._cache.clear()
    tenant_keys.use(None)
    saved: list[dict] = []

    async def update(table, match, values):
        saved.append({"table": table, **match, **values})
        return []
    monkeypatch.setattr(tenant_keys.supa, "update", update)
    return saved


def fake_http(monkeypatch, handler):
    calls: list[httpx.Request] = []

    def wrapped(req: httpx.Request) -> httpx.Response:
        calls.append(req)
        return handler(req)
    real = httpx.AsyncClient
    monkeypatch.setattr(llm_chat.httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(wrapped), **kw))
    monkeypatch.setattr(llm_chat.asyncio, "sleep", lambda *_: asyncio.sleep(0))
    return calls


def reply(text: str) -> httpx.Response:
    return httpx.Response(200, json={"choices": [{"message": {"content": text}}]})


NO_CREDITS = httpx.Response(429, json={"error": {"type": "insufficient_quota", "code": "credit_balance_exhausted"}})


def test_load_decrypts_and_caches(monkeypatch):
    n = 0

    async def select(table, **params):
        nonlocal n
        n += 1
        assert table == "tenant_api_keys" and params["tenant_id"] == f"eq.{T}"
        return [{"secret_enc": secrets.encrypt("sk-abc"), "status": "ok", "checked_at": None}]
    monkeypatch.setattr(tenant_keys.supa, "select", select)
    k = asyncio.run(tenant_keys.load(T))
    assert k.value == "sk-abc" and k.live_ok()
    asyncio.run(tenant_keys.load(T))
    assert n == 1


def test_load_never_raises(monkeypatch):
    async def broken(*a, **kw):
        raise RuntimeError("relation tenant_api_keys does not exist")
    monkeypatch.setattr(tenant_keys.supa, "select", broken)
    assert asyncio.run(tenant_keys.load(T)) is None
    assert asyncio.run(tenant_keys.load(None)) is None


def test_which_keys_are_used():
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    assert TenantKey(T, "k", "unchecked").live_ok()
    assert not TenantKey(T, "k", "no_credits", datetime.now(timezone.utc)).live_ok()
    assert not TenantKey(T, "k", "no_credits", datetime.now(timezone.utc)).worth_trying()
    assert TenantKey(T, "k", "no_credits", old).worth_trying()     # credits may have been added
    assert not TenantKey(T, "k", "invalid", old).worth_trying()


def test_classify():
    assert tenant_keys.classify(401, "") == "invalid"
    assert tenant_keys.classify(429, NO_CREDITS.text) == "no_credits"
    assert tenant_keys.classify(429, '{"error":{"type":"rate_limit_exceeded"}}') is None
    assert tenant_keys.classify(500, "") is None


def test_working_key_uses_openai(monkeypatch):
    calls = fake_http(monkeypatch, lambda r: reply("hello"))
    out = asyncio.run(llm_chat.chat([{"role": "user", "content": "hi"}], key=TenantKey(T, "sk-own", "ok")))
    assert out == "hello" and len(calls) == 1
    assert calls[0].url.host == "api.openai.com" and calls[0].headers["authorization"] == "Bearer sk-own"


def test_no_key_uses_free_model(monkeypatch):
    calls = fake_http(monkeypatch, lambda r: reply("namaste"))
    assert asyncio.run(llm_chat.chat([{"role": "user", "content": "hi"}], key=None)) == "namaste"
    assert calls[0].url.host == "api.groq.com"
    assert json.loads(calls[0].content)["model"] == llm_chat.FREE_MODEL


def test_out_of_credits_falls_back_and_is_recorded(monkeypatch, env):
    calls = fake_http(monkeypatch, lambda r: NO_CREDITS if r.url.host == "api.openai.com" else reply("ok"))
    key = TenantKey(T, "sk-own", "ok")
    tenant_keys.use(key)
    assert asyncio.run(llm_chat.chat([{"role": "user", "content": "hi"}])) == "ok"
    assert [c.url.host for c in calls] == ["api.openai.com", "api.groq.com"]   # no retries on a refused key
    assert env[-1]["status"] == "no_credits" and env[-1]["tenant_id"] == T


def test_recovered_key_is_marked_ok(monkeypatch, env):
    fake_http(monkeypatch, lambda r: reply("ok"))
    old = datetime.now(timezone.utc) - timedelta(hours=2)
    asyncio.run(llm_chat.chat([{"role": "user", "content": "hi"}], key=TenantKey(T, "sk-own", "no_credits", old)))
    assert env[-1]["status"] == "ok"


def test_live_chain_skips_a_failing_key(monkeypatch):
    from agent_worker import providers
    monkeypatch.setenv("GROQ_API_KEY", "gsk_test")
    spec = {"provider": "openai", "model": "gpt-4o-mini"}
    tenant_keys.use(None)
    assert providers._llm(spec, 100) is None
    tenant_keys.use(TenantKey(T, "sk-own", "no_credits", datetime.now(timezone.utc)))
    assert providers._llm(spec, 100) is None
    tenant_keys.use(TenantKey(T, "sk-own", "ok"))
    assert providers._llm(spec, 100) is not None
