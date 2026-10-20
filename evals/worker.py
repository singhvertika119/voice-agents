"""Runs queued test conversations (eval_runs) started from the dashboard.

    uv run python -m evals.worker
"""
from __future__ import annotations

import asyncio
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/agent-worker"), str(ROOT / "packages/core"), str(ROOT)]
load_dotenv(ROOT / ".env", override=True)

from agent_worker import db, workspace  # noqa: E402
from agent_worker.config import from_dict  # noqa: E402
from agent_worker.knowledge import load_knowledge  # noqa: E402
from vp_core import supa  # noqa: E402

from evals.runner import scenarios as sc  # noqa: E402
from evals.runner.suite import run_suite  # noqa: E402

log = logging.getLogger("evals")
MAX_REPLY_MS = 3000


async def claim() -> dict | None:
    rows = await supa.select("eval_runs", select="*", status="eq.queued", order="created_at.asc", limit="1")
    if not rows:
        return None
    async with supa.client() as c:   # atomic: only one worker flips queued -> running
        r = await c.patch("/rest/v1/eval_runs", params={"id": f"eq.{rows[0]['id']}", "status": "eq.queued"}, json={"status": "running"})
        r.raise_for_status()
        return r.json()[0] if r.json() else None


async def run_job(job: dict) -> None:
    tenant, agent_id = job["tenant_id"], job["agent_id"]
    try:
        pub = await db.fetch_version(agent_id, job["agent_version"])
        cfg = from_dict(agent_id, pub["agent"]["name"], pub["config"])
        kb = await load_knowledge(cfg.knowledge_sources, tenant)
        ktext = (cfg.knowledge + "\n" + kb.prompt_text).strip()
        if kb.mode == "search":   # big knowledge bases are not in the prompt: sample passages so the judge has the facts
            chunks = await supa.select("kb_chunks", select="content", source_id=f"in.({','.join(kb.source_ids)})", tenant_id=f"eq.{tenant}", limit="40")
            ktext += "\n" + "\n".join(c["content"] for c in chunks)
        settings = await workspace.get_settings(tenant)

        scenarios = sc.load_standard()
        try:
            custom = await supa.select("eval_scenarios", select="*", tenant_id=f"eq.{tenant}", enabled="eq.true")
            scenarios += [sc.from_dashboard(r) for r in custom if r["agent_id"] in (None, agent_id)]
        except Exception:
            pass
        scenarios += await sc.from_knowledge(ktext, 4)

        report = await run_suite(cfg, kb, scenarios, ktext, runs=job["runs_per_scenario"], settings=settings, max_reply_ms=MAX_REPLY_MS)
        # Keep the stored report small: full transcripts only for runs that failed.
        for s in report["scenarios"]:
            for r in s["results"]:
                if r["passed"]:
                    r["transcript"] = r["transcript"][:0]
        await supa.update("eval_runs", {"id": job["id"]}, {
            "status": "done", "passed": report["passed"], "pass_rate": report["pass_rate"], "p95_reply_ms": report["p95_reply_ms"],
            "results": json.loads(json.dumps(report, default=str)), "finished_at": datetime.now(timezone.utc).isoformat()})
        log.info("run %s: %s (%s/%s scenarios, p95 %s ms)", job["id"], "PASSED" if report["passed"] else "FAILED",
                 report["scenarios_passed"], report["scenarios_total"], report["p95_reply_ms"])
    except Exception as e:
        log.exception("test run failed")
        await supa.update("eval_runs", {"id": job["id"]}, {"status": "failed", "error": f"{type(e).__name__}: {e}"[:500],
                                                             "finished_at": datetime.now(timezone.utc).isoformat()})


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    async with supa.client() as c:   # a crash mid-run must not leave a run "running" forever
        await c.patch("/rest/v1/eval_runs", params={"status": "eq.running"}, json={"status": "queued"})
    log.info("test worker waiting for runs")
    while True:
        try:
            job = await claim()
        except Exception as e:
            log.warning("poll failed: %s", e)
            await asyncio.sleep(5)
            continue
        if job:
            log.info("running tests for agent %s v%s", job["agent_id"], job["agent_version"])
            await run_job(job)
        else:
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
