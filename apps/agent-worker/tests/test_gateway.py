import asyncio
import hashlib
import hmac

import httpx

from agent_worker import custom_tools as ct


def tool(**kw):
    base = {"tenant_id": "t1", "name": "check_order", "endpoint": "https://api.example.com/status", "method": "POST",
            "timeout_ms": 1000, "auth_header": "Authorization", "idempotent": False}
    return {**base, **kw}


def run(coro):
    return asyncio.run(coro)


def reset():
    ct._fails.clear(); ct._open_until.clear(); ct._calls.clear()


def mock_client(handler):
    return httpx.AsyncClient(transport=httpx.MockTransport(handler))


def allow_public(monkeypatch):
    monkeypatch.setattr(ct, "assert_public_url", lambda url, https_only=False: None)


def test_success_returns_compact_data_and_signs_the_request(monkeypatch):
    reset(); allow_public(monkeypatch)
    seen = {}

    def handler(req: httpx.Request):
        seen["h"] = dict(req.headers); seen["body"] = req.content.decode()
        return httpx.Response(200, json={"status": "shipped", "eta": "2 days"})

    ok, text = run(ct.call_endpoint(tool(), "s3cret", {"order_id": "4821"}, "call1:0:check_order", client=mock_client(handler)))
    assert ok and "shipped" in text
    assert seen["h"]["idempotency-key"] == "call1:0:check_order"
    assert seen["h"]["authorization"] == "s3cret"
    expected = hmac.new(b"s3cret", f"{seen['h']['x-vp-timestamp']}.{seen['body']}".encode(), hashlib.sha256).hexdigest()
    assert seen["h"]["x-vp-signature"] == expected


def test_private_or_plain_http_addresses_are_refused_without_a_network_call():
    reset()
    def boom(req): raise AssertionError("must not be called")
    for url in ("http://example.com/x", "https://127.0.0.1/x", "https://169.254.169.254/latest/meta-data"):
        ok, text = run(ct.call_endpoint(tool(endpoint=url), None, {}, "k", client=mock_client(boom)))
        assert not ok and "not allowed" in text


def test_timeout_gives_a_safe_message_and_does_not_retry_actions(monkeypatch):
    reset(); allow_public(monkeypatch)
    calls = []

    def handler(req):
        calls.append(1)
        raise httpx.ReadTimeout("slow")

    ok, text = run(ct.call_endpoint(tool(), None, {}, "k", client=mock_client(handler)))
    assert not ok and "took too long" in text and "do not guess" in text and len(calls) == 1


def test_lookups_are_retried_once(monkeypatch):
    reset(); allow_public(monkeypatch)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(503) if len(calls) == 1 else httpx.Response(200, text="ok")

    ok, _ = run(ct.call_endpoint(tool(method="GET", idempotent=True), None, {}, "k", client=mock_client(handler)))
    assert ok and len(calls) == 2


def test_client_errors_are_not_retried(monkeypatch):
    reset(); allow_public(monkeypatch)
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(404)

    ok, text = run(ct.call_endpoint(tool(method="GET", idempotent=True), None, {}, "k", client=mock_client(handler)))
    assert not ok and len(calls) == 1 and "404" in text


def test_circuit_opens_after_repeated_failures(monkeypatch):
    reset(); allow_public(monkeypatch)
    n = []

    def handler(req):
        n.append(1)
        return httpx.Response(500)

    for _ in range(3):
        run(ct.call_endpoint(tool(), None, {}, "k", client=mock_client(handler)))
    before = len(n)
    ok, text = run(ct.call_endpoint(tool(), None, {}, "k", client=mock_client(handler)))
    assert not ok and "not responding" in text and len(n) == before


def test_long_results_are_shortened_for_the_model(monkeypatch):
    reset(); allow_public(monkeypatch)
    ok, text = run(ct.call_endpoint(tool(), None, {}, "k", client=mock_client(lambda r: httpx.Response(200, text="x" * 5000))))
    assert ok and len(text) < 1000 and "shortened" in text
