"""Question embeddings in the agent's shared model process (D-122).

Each call runs in its own process, and in production a few spare processes are kept ready. Loading the 0.3 GB
embedding model in each would multiply that memory, so it is loaded once, in the process LiveKit already runs for the
turn-detection model, and calls send their question there. This uses LiveKit's inference-runner hook, which the
turn detector uses but LiveKit still marks as private: if an upgrade changes it, the tests in
tests/test_embed_runner.py fail and the agent falls back to keyword search rather than breaking calls.
"""
from __future__ import annotations

import logging

import numpy as np
from livekit.agents import Plugin
from livekit.agents.inference_runner import _InferenceRunner
from livekit.agents.job import get_job_context

from vp_core import embeddings

log = logging.getLogger("agent.embed")
METHOD = "vp_embed_query"


class EmbedRunner(_InferenceRunner):
    INFERENCE_METHOD = METHOD

    def initialize(self) -> None:
        # Must not raise: a failure here would stop the shared process and the turn detector with it.
        try:
            self._enc: embeddings.Encoder | None = embeddings.Encoder(threads=1)
            self._enc.encode(["namaste"], "query")   # the first run is slower; pay for it at start-up
        except Exception:
            log.exception("embedding model failed to load; knowledge search will use keywords only")
            self._enc = None

    def run(self, data: bytes) -> bytes | None:
        if self._enc is None:
            return None
        return self._enc.encode([data.decode("utf-8")], "query")[0].tobytes()


async def _remote_query(text: str) -> list[float]:
    out = await get_job_context().inference_executor.do_inference(METHOD, text.encode("utf-8"))
    if not out:
        raise RuntimeError("embedding model not available")
    return np.frombuffer(out, dtype=np.float32).tolist()


def use_in_this_call() -> None:
    """Called at the start of each call (job process): send question embeddings to the shared process."""
    if METHOD in _InferenceRunner.registered_runners:
        embeddings.use_remote(_remote_query)


class _EmbedPlugin(Plugin):
    """Only so that `python -m agent_worker.agent download-files` (run in the Dockerfile) also fetches this model."""

    def __init__(self) -> None:
        super().__init__("vp-embeddings", "1", __name__, log)

    def download_files(self) -> None:
        embeddings.download()


def register() -> None:
    """At import of the agent module, on the main thread, like LiveKit's own plugins."""
    try:
        if METHOD not in _InferenceRunner.registered_runners:
            _InferenceRunner.register_runner(EmbedRunner)
            Plugin.register_plugin(_EmbedPlugin())
    except Exception as e:   # e.g. imported from a non-main thread by a test harness: calls then embed in-process
        log.warning("embedding runner not registered: %s", e)
