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

log = logging.getLogger("background")
STARTED = time.time()
STATE = {"ingestion": "starting", "tests": "starting"}


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
    return web.json_response({"ok": True, "uptime_s": int(time.time() - STARTED), "workers": STATE})


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    from evals.worker import main as tests_main
    from ingestion.main import main as ingestion_main

    app = web.Application()
    app.add_routes([web.get("/", health), web.get("/healthz", health)])
    runner = web.AppRunner(app)
    await runner.setup()
    port = int(os.getenv("PORT", "10000"))
    await web.TCPSite(runner, "0.0.0.0", port).start()
    log.info("health page on port %s", port)
    await asyncio.gather(supervise("ingestion", ingestion_main), supervise("tests", tests_main))


if __name__ == "__main__":
    asyncio.run(main())
