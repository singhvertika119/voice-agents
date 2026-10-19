"""Polls knowledge_sources for queued items and processes them.

    uv run python -m ingestion.main
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from vp_core import supa  # noqa: E402

from .pipeline import claim_next, process  # noqa: E402

log = logging.getLogger("ingest")


async def reset_stuck() -> None:
    """A previous run that died mid-way left sources in a working state. Put them back in the queue."""
    async with supa.client() as c:
        r = await c.patch("/rest/v1/knowledge_sources", params={"status": "in.(parsing,indexing,testing)"},
                          json={"status": "queued"})
        if r.status_code < 300 and r.json():
            log.info("re-queued %d interrupted sources", len(r.json()))


async def purge_loop() -> None:
    """Hourly: delete transcripts older than each workspace's retention window (DPDP storage limitation)."""
    while True:
        try:
            out = await supa.rpc("purge_expired", {})
            log.info("retention purge: %s", out)
        except Exception as e:  # the function arrives with migration 0005; until then there is nothing to do
            log.info("retention purge skipped: %s", str(e)[:80])
        await asyncio.sleep(3600)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    await reset_stuck()
    asyncio.create_task(purge_loop())
    log.info("ingestion worker waiting for sources")
    while True:
        try:
            src = await claim_next()
        except Exception as e:  # database unreachable or tables missing: wait and retry
            log.warning("poll failed: %s", e)
            await asyncio.sleep(5)
            continue
        if src:
            log.info("processing %s (%s)", src["name"], src["source_type"])
            await process(src)
        else:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
