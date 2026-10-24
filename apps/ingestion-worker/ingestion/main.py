"""Polls knowledge_sources for queued items and processes them.

    uv run python -m ingestion.main
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[3] / ".env")

from vp_core import heartbeat, supa  # noqa: E402

from .pipeline import claim_next, process  # noqa: E402

log = logging.getLogger("ingest")


INTERRUPTED = ("Processing stopped part-way because the document reader restarted. Upload it again; "
               "if it stops again, split the file into smaller parts.")


async def reset_stuck() -> None:
    """A previous run that died mid-way left sources in a working state. Retrying them automatically can crash the
    worker on the same file after every restart, so they are closed as failed with a reason instead."""
    async with supa.client() as c:
        r = await c.patch("/rest/v1/knowledge_sources", params={"status": "in.(parsing,indexing,testing)"},
                          json={"status": "failed", "error": INTERRUPTED})
        if r.status_code < 300 and r.json():
            log.info("closed %d sources interrupted by a restart", len(r.json()))


async def purge_recordings() -> int:
    """Delete audio files older than each workspace's retention window (same window as transcripts), then forget the
    path. The database function cannot remove storage files, so this part lives here (docs/decision.md D-068)."""
    from datetime import datetime, timedelta, timezone
    settings = {r["tenant_id"]: r["retention_days"] for r in await supa.select("tenant_settings", select="tenant_id,retention_days")}
    rows = await supa.select("calls", select="id,tenant_id,recording_path,started_at", recording_path="not.is.null", limit="500")
    now, gone = datetime.now(timezone.utc), 0
    by_tenant: dict[str, list[dict]] = {}
    for r in rows:
        days = settings.get(r["tenant_id"], 90)
        if datetime.fromisoformat(r["started_at"]) < now - timedelta(days=days):
            by_tenant.setdefault(r["tenant_id"], []).append(r)
    for rs in by_tenant.values():
        await supa.remove("recordings", [r["recording_path"] for r in rs])
        for r in rs:
            await supa.update("calls", {"id": r["id"]}, {"recording_path": None})
            gone += 1
    return gone


async def purge_loop() -> None:
    """Hourly: delete transcripts older than each workspace's retention window (DPDP storage limitation)."""
    while True:
        try:
            out = await supa.rpc("purge_expired", {})
            log.info("retention purge: %s", out)
            n = await purge_recordings()
            if n:
                log.info("retention purge removed %d recordings", n)
        except Exception as e:  # the function arrives with migration 0005; until then there is nothing to do
            log.info("retention purge skipped: %s", str(e)[:80])
        await asyncio.sleep(3600)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    await reset_stuck()
    asyncio.create_task(purge_loop())
    log.info("ingestion worker waiting for sources")
    while True:
        heartbeat.beat("ingestion")
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
