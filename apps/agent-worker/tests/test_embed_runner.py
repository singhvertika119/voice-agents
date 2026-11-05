"""Local embeddings (D-122): the model, the agent's shared-process runner, and the dashboard's signed /embed endpoint.
Model tests need the model files (downloaded once into the Hugging Face cache); they are skipped without them."""
import asyncio
import hashlib
import hmac
import importlib.util
import json
import time
from pathlib import Path

import numpy as np
import pytest

from vp_core import embeddings

try:
    ENC = embeddings.Encoder(threads=1)
except Exception as e:  # no network and no cached model
    ENC = None
    REASON = f"embedding model not available: {e}"
needs_model = pytest.mark.skipif(ENC is None, reason="embedding model not available")


@needs_model
def test_vectors_are_768_unit_length_and_kind_matters():
    q = ENC.encode(["office kahan hai?"], "query")
    p = ENC.encode(["office kahan hai?"], "passage")
    assert q.shape == (1, embeddings.DIMS) and q.dtype == np.float32
    assert abs(float(np.linalg.norm(q[0])) - 1) < 1e-4
    assert not np.allclose(q, p)   # "query: " and "passage: " prefixes are applied


@needs_model
def test_hindi_question_finds_the_english_passage():
    passages = ENC.encode(["Contact us > Address: Our office is at 12 MG Road, Bengaluru. Open 10 am to 6 pm.",
                           "Fees > Annual fee is Rs 40,000, payable in two instalments."], "passage")
    for q in ["ऑफिस कहाँ है?", "office kahan hai", "Where is your office?"]:
        sims = passages @ ENC.encode([q], "query")[0]
        assert sims[0] > sims[1], q


@needs_model
def test_a_text_gets_the_same_vector_alone_or_with_others():
    texts = ["short", "a much longer sentence about school fees and the admission process"]
    both = ENC.encode(texts, "passage")
    one = np.vstack([ENC.encode([t], "passage") for t in texts])
    assert np.allclose(both, one, atol=1e-6)   # stored vectors must not depend on what was embedded alongside


@needs_model
def test_runner_returns_the_same_vector_as_the_model():
    from agent_worker.embed_runner import EmbedRunner
    r = EmbedRunner()
    r.initialize()
    out = np.frombuffer(r.run("fees kitni hai".encode()), dtype=np.float32)
    assert out.shape == (embeddings.DIMS,)
    assert np.allclose(out, ENC.encode(["fees kitni hai"], "query")[0], atol=1e-5)


def test_runner_failing_to_load_does_not_raise(monkeypatch):
    from agent_worker.embed_runner import EmbedRunner

    def broken(*a, **k):
        raise RuntimeError("no model")
    monkeypatch.setattr(embeddings, "Encoder", broken)
    r = EmbedRunner()
    r.initialize()          # must not raise: it would stop the shared process and the turn detector with it
    assert r.run(b"hello") is None


def test_livekit_private_hooks_still_exist():
    # The runner relies on LiveKit's (private) inference-runner API, as the turn detector does. Fails on an upgrade
    # that changes it, before a deploy does.
    from livekit.agents.inference_runner import _InferenceRunner
    from livekit.agents.ipc.inference_executor import InferenceExecutor
    assert callable(_InferenceRunner.register_runner) and hasattr(InferenceExecutor, "do_inference")
    from agent_worker import embed_runner
    embed_runner.register()
    embed_runner.register()   # a second call is harmless
    assert _InferenceRunner.registered_runners[embed_runner.METHOD] is embed_runner.EmbedRunner


def test_query_goes_to_the_shared_process_and_is_cached(monkeypatch):
    calls = []

    async def remote(text):
        calls.append(text)
        return [0.5] * embeddings.DIMS
    monkeypatch.setattr(embeddings, "_cache", type(embeddings._cache)())
    embeddings.use_remote(remote)
    try:
        v1 = asyncio.run(embeddings.embed_query("timing kya hai"))
        v2 = asyncio.run(embeddings.embed_query("timing kya hai"))
    finally:
        embeddings.use_remote(None)
    assert v1 == v2 == [0.5] * embeddings.DIMS and calls == ["timing kya hai"]


def _background():
    path = Path(__file__).resolve().parents[3] / "deploy" / "run_background.py"
    spec = importlib.util.spec_from_file_location("run_background", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_embed_endpoint_checks_the_signature(monkeypatch):
    from aiohttp import web
    from aiohttp.test_utils import TestClient, TestServer
    bg = _background()
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "test-key")

    async def fake(texts):
        return [[0.25] * 3 for _ in texts]
    monkeypatch.setattr(embeddings, "embed_queries", fake)

    def signed(body: bytes, key="test-key", ts=None):
        ts = str(int(time.time()) if ts is None else ts)
        return {"x-vp-time": ts, "x-vp-signature": hmac.new(key.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()}

    async def run():
        app = web.Application()
        app.add_routes([web.post("/embed", bg.embed)])
        async with TestClient(TestServer(app)) as c:
            body = json.dumps({"texts": ["fees?"]}).encode()
            ok = await c.post("/embed", data=body, headers=signed(body))
            assert ok.status == 200 and (await ok.json())["vectors"] == [[0.25] * 3]
            assert (await c.post("/embed", data=body, headers=signed(body, key="wrong"))).status == 401
            assert (await c.post("/embed", data=body, headers=signed(body, ts=int(time.time()) - 300))).status == 401
            assert (await c.post("/embed", data=body)).status == 401
            other = json.dumps({"texts": ["something else"]}).encode()
            assert (await c.post("/embed", data=other, headers=signed(body))).status == 401   # body changed
            many = json.dumps({"texts": ["x"] * 9}).encode()
            assert (await c.post("/embed", data=many, headers=signed(many))).status == 400
    asyncio.run(run())
