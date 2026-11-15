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

from .pipeline import claim_next, process, refresh_websites  # noqa: E402

log = logging.getLogger("ingest")


INTERRUPTED = ("Processing stopped part-way because the document reader restarted. Upload it again; "
               "if it stops again, split the file into smaller parts.")


async def reset_stuck() -> None:
    """A previous run that died mid-way left sources in a working state. Retrying them automatically can crash the
    worker on the same file after every restart, so they are closed as failed with a reason instead.
    Only reset rows whose updated_at is older than 5 minutes so overlapping deploys do not kill active processing."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(minutes=5)).isoformat()
    async with supa.client() as c:
        r = await c.patch("/rest/v1/knowledge_sources", params={"status": "in.(parsing,indexing,testing)", "updated_at": f"lt.{cutoff}"},
                          json={"status": "failed", "error": INTERRUPTED})
        if r.status_code < 300 and r.json():
            log.info("closed %d sources interrupted by a restart", len(r.json()))


async def purge_recordings() -> int:
    """Delete audio files older than each workspace's retention window (same window as transcripts), then forget the
    path. The database function cannot remove storage files, so this part lives here (docs/decision.md D-068)."""
    from datetime import datetime, timedelta, timezone
    now = datetime.now(timezone.utc)
    try:
        settings_rows = await supa.select("tenant_settings", select="tenant_id,retention_days")
    except Exception as e:
        log.warning("could not fetch tenant_settings for purge: %s", e)
        return 0

    settings = {r["tenant_id"]: r.get("retention_days") or 90 for r in settings_rows}
    gone = 0

    for tenant_id, days in settings.items():
        cutoff = (now - timedelta(days=days)).isoformat()
        try:
            rows = await supa.select(
                "calls",
                select="id,recording_path,started_at",
                tenant_id=f"eq.{tenant_id}",
                recording_path="not.is.null",
                started_at=f"lt.{cutoff}",
                order="started_at.asc",
                limit="500",
            )
            if not rows:
                continue

            paths = [r["recording_path"] for r in rows if r.get("recording_path")]
            if paths:
                try:
                    await supa.remove("recordings", paths)
                except Exception as e:
                    log.warning("tenant %s: could not remove %d recordings from storage: %s", tenant_id, len(paths), e)
                    continue

                for r in rows:
                    try:
                        await supa.update("calls", {"id": r["id"]}, {"recording_path": None})
                        gone += 1
                    except Exception as e:
                        log.warning("could not clear recording_path for call %s: %s", r["id"], e)
        except Exception as e:
            log.warning("purge failed for tenant %s: %s", tenant_id, e)
            continue

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
        except Exception as e:  # noqa: BLE001  try again next hour
            log.warning("retention purge failed: %s", str(e)[:200])
        await asyncio.sleep(3600)


async def refresh_loop() -> None:
    """Hourly: re-read website sources that have not been checked for a week (D-108)."""
    while True:
        try:
            n = await refresh_websites()
            if n:
                log.info("website refresh: %d sources changed and were re-indexed", n)
        except Exception as e:
            log.info("website refresh skipped: %s", str(e)[:120])
        await asyncio.sleep(3600)


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    await reset_stuck()
    asyncio.create_task(purge_loop())
    asyncio.create_task(refresh_loop())
    log.info("ingestion worker waiting for sources")
    while True:
        try:
            src = await claim_next()
            heartbeat.beat("ingestion")
        except Exception as e:  # database unreachable or tables missing: wait and retry
            log.warning("poll failed: %s", e)
            await asyncio.sleep(5)
            continue
        if src:
            log.info("processing %s (%s)", src["name"], src["source_type"])
            try:
                await asyncio.wait_for(process(src), timeout=300.0)
            except asyncio.TimeoutError:
                log.warning("processing %s timed out after 300s", src["id"])
            except Exception as e:
                log.exception("failed to process %s: %s", src["id"], e)
        else:
            await asyncio.sleep(2)


if __name__ == "__main__":
    asyncio.run(main())
