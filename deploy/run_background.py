"""Runs the document reader, the test worker and the hourly cleanup in one process, with a small web page.

Why a web page: free hosts only offer "web services", and they want something answering HTTP. `/healthz` answers that;
an uptime monitor calling it every few minutes also keeps a free host from putting the service to sleep.

    python deploy/run_background.py
"""
import asyncio
import hashlib
import hmac
import json
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/agent-worker"), str(ROOT / "apps/ingestion-worker"), str(ROOT / "packages/core"), str(ROOT)]

from aiohttp import web  # noqa: E402  (installed with the LiveKit packages)
from vp_core import embeddings, heartbeat  # noqa: E402

log = logging.getLogger("background")
STARTED = time.time()
STATE = {"ingestion": "starting", "tests": "starting"}
# One test conversation holds about 450 MB (measured, docs/decision.md D-094), so the test worker cannot share a
# 512 MB free instance with the document reader. It is off on Render unless RUN_TEST_WORKER=1 (a bigger instance);
# test runs queued from the dashboard then wait for `scripts/run-evals.ps1` on a laptop.
RUN_TESTS = os.getenv("RUN_TEST_WORKER", "0" if os.getenv("RENDER") else "1") == "1"


async def supervise(name: str, fn):
    """Keep one worker alive. If it crashes, say why and start it again after a pause."""
    while True:
        try:
            STATE[name] = "running"
            await fn()
        except asyncio.CancelledError:
            raise
        except Exception:
            STATE[name] = "restarting"
            log.exception("%s worker crashed; restarting in 10 s", name)
            await asyncio.sleep(10)


async def health(_request: web.Request) -> web.Response:
    # Always 200 while the process is up: a long test run or document legitimately pauses the loop, and a failing
    # health check would make Render restart the service mid-job. "last_poll_s" shows how long since each worker looked
    # for work, and "memory_mb" how close the process is to the free instance's 512 MB.
    return web.json_response({"ok": True, "uptime_s": int(time.time() - STARTED), "workers": STATE,
                              "last_poll_s": heartbeat.ages(), "memory_mb": _memory_mb()})


async def embed(request: web.Request) -> web.Response:
    """Question vectors for the dashboard's knowledge chat (D-122): the embedding model runs here, not on Vercel.
    The dashboard signs each request with the service-role key both servers already hold (HMAC of time + body), so
    the key itself is never sent and an old request cannot be replayed after a minute."""
    body = await request.read()
    key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY", "")
    ts = request.headers.get("x-vp-time", "")
    sig = request.headers.get("x-vp-signature", "")
    want = hmac.new(key.encode(), f"{ts}.".encode() + body, hashlib.sha256).hexdigest()
    if not key or not ts.isdigit() or abs(time.time() - int(ts)) > 60 or not hmac.compare_digest(sig, want):
        return web.json_response({"error": "not allowed"}, status=401)
    try:
        texts = json.loads(body)["texts"]
        assert isinstance(texts, list) and 0 < len(texts) <= 8 and all(isinstance(t, str) for t in texts)
    except Exception:
        return web.json_response({"error": "send {\"texts\": [up to 8 strings]}"}, status=400)
    vecs = await embeddings.embed_queries([t[:2000] for t in texts])
    return web.json_response({"model": embeddings.MODEL, "vectors": [[round(x, 6) for x in v] for v in vecs]})


def _memory_mb() -> int | None:
    try:
        with open("/proc/self/status") as f:   # Linux (Render); absent on Windows, where it is simply left out
            for line in f:
                if line.startswith("VmRSS:"):
                    return int(line.split()[1]) // 1024
    except OSError:
        return None
    return None


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from ingestion.main import main as ingestion_main

    app = web.Application()
    app.add_routes([web.get("/", health), web.get("/healthz", health), web.post("/embed", embed)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("health page on port %s", port)
    # Load the embedding model now (about 0.3 GB, a second or two), not on the first chat question or document.
    asyncio.get_running_loop().run_in_executor(None, embeddings.encoder)
    workers = [supervise("ingestion", ingestion_main)]
    if RUN_TESTS:
        from evals.worker import main as tests_main   # imported only when used: the import alone is about 140 MB
        workers.append(supervise("tests", tests_main))
    else:
        STATE["tests"] = "off on this server (run scripts/run-evals.ps1 locally)"
    await asyncio.gather(*workers)


if __name__ == "__main__":
    asyncio.run(main())
