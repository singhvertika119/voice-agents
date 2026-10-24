"""Runs the document reader, the test worker and the hourly cleanup in one process, with a small web page.

Why a web page: free hosts only offer "web services", and they want something answering HTTP. `/healthz` answers that;
an uptime monitor calling it every few minutes also keeps a free host from putting the service to sleep.

    python deploy/run_background.py
"""
import asyncio
import logging
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/agent-worker"), str(ROOT / "apps/ingestion-worker"), str(ROOT / "packages/core"), str(ROOT)]

from aiohttp import web  # noqa: E402  (installed with the LiveKit packages)
from vp_core import heartbeat  # noqa: E402

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
    app.add_routes([web.get("/", health), web.get("/healthz", health)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("health page on port %s", port)
    workers = [supervise("ingestion", ingestion_main)]
    if RUN_TESTS:
        from evals.worker import main as tests_main   # imported only when used: the import alone is about 140 MB
        workers.append(supervise("tests", tests_main))
    else:
        STATE["tests"] = "off on this server (run scripts/run-evals.ps1 locally)"
    await asyncio.gather(*workers)


if __name__ == "__main__":
    asyncio.run(main())
