"""Runs queued test conversations (eval_runs) started from the dashboard.

    uv run python -m evals.worker
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "apps/agent-worker"), str(ROOT / "packages/core"), str(ROOT)]
load_dotenv(ROOT / ".env", override=True)

from agent_worker import db, workspace  # noqa: E402
from agent_worker.config import from_dict  # noqa: E402
from agent_worker.knowledge import load_knowledge  # noqa: E402
from vp_core import heartbeat, supa  # noqa: E402

from evals.runner import scenarios as sc  # noqa: E402
from evals.runner.suite import run_suite  # noqa: E402

log = logging.getLogger("evals")
MAX_REPLY_MS = 3000
# Conversations run at the same time. Each one holds an agent session in memory; three together peaked at about
# 506 MB on a 3-minute run, which is over the 512 MB free Render instance (docs/decision.md D-094). Render sets RENDER.
CONCURRENCY = int(os.getenv("EVAL_CONCURRENCY", "1" if os.getenv("RENDER") else "3"))
STALLED = ("This run stopped making progress (the test runner was restarted or ran out of memory while running it). "
           "Run the tests again.")
STALE_MIN = 10        # no saved progress for this long means nobody is working on a "running" run (D-105)
CURRENT: dict = {}    # the run this worker is on, so a shutdown can hand it back


async def claim() -> dict | None:
    rows = await supa.select("eval_runs", select="*", status="eq.queued", order="created_at.asc", limit="1")
    if not rows:
        return None
    async with supa.client() as c:   # atomic: only one worker flips queued -> running
        r = await c.patch("/rest/v1/eval_runs", params={"id": f"eq.{rows[0]['id']}", "status": "eq.queued"}, json={"status": "running"})
        r.raise_for_status()
        return r.json()[0] if r.json() else None


async def report_progress(run_id: str, stage: str, done: int = 0, total: int = 0, passed: int = 0) -> None:
    """Live progress for the Tests tab while a run is going (D-105): which stage, conversations finished, how many of
    those passed, and when it last moved, so a stalled run can be told apart from a slow one. The final report
    replaces it. Never raises."""
    try:
        await supa.update("eval_runs", {"id": run_id}, {"results": {"progress": {
            "stage": stage, "done": done, "total": total, "passed": passed,
            "updated_at": datetime.now(timezone.utc).isoformat()}}})
    except Exception as e:
        log.info("progress not saved: %s", e)


async def knowledge_questions(tenant: str, agent_id: str, ktext: str) -> list[dict]:
    """The agent's saved knowledge questions, written once and reused while its knowledge is unchanged (D-107).
    Before this every run asked newly written questions, so the same version scored 67% to 89% from run to run and a
    score could not show whether a change helped. They are rewritten when the knowledge changes, or when the owner
    clears them in the Tests tab. Questions the owner removed one by one stay removed."""
    key = sc.knowledge_key(ktext)
    rows = await supa.select("eval_scenarios", select="id,name,spec,enabled", agent_id=f"eq.{agent_id}",
                             tenant_id=f"eq.{tenant}", **{"spec->>source": "eq.generated"}, order="created_at.asc")
    if rows and all((r["spec"] or {}).get("knowledge_key") == key for r in rows):
        return [r["spec"] for r in rows if r["enabled"]]
    items = await sc.write_knowledge_questions(ktext)
    async with supa.client() as c:
        if rows:   # the knowledge changed: questions written from the old text may no longer be right
            r = await c.delete("/rest/v1/eval_scenarios", params={"agent_id": f"eq.{agent_id}", "spec->>source": "eq.generated"})
            r.raise_for_status()
        if items:
            r = await c.post("/rest/v1/eval_scenarios", json=[
                {"tenant_id": tenant, "agent_id": agent_id, "name": it["question"][:80],
                 "spec": {**it, "source": "generated", "knowledge_key": key}} for it in items])
            r.raise_for_status()
    log.info("wrote %d knowledge questions for agent %s", len(items), agent_id)
    return items


async def run_job(job: dict) -> None:
    tenant, agent_id = job["tenant_id"], job["agent_id"]
    await report_progress(job["id"], "preparing")
    try:
        pub = await db.fetch_version(agent_id, job["agent_version"])
        cfg = from_dict(agent_id, pub["agent"]["name"], pub["config"])
        kb = await load_knowledge(cfg.knowledge_sources, tenant, cfg.knowledge_mode)
        ktext = (cfg.knowledge + "\n" + kb.prompt_text).strip()
        if kb.mode == "search":   # big knowledge bases are not in the prompt: sample passages so the judge has the facts
            chunks = await supa.select("kb_chunks", select="content", source_id=f"in.({','.join(kb.source_ids)})", tenant_id=f"eq.{tenant}", limit="40")
            ktext += "\n" + "\n".join(c["content"] for c in chunks)
        settings = await workspace.get_settings(tenant)

        scenarios = sc.load_standard()
        try:
            custom = await supa.select("eval_scenarios", select="*", tenant_id=f"eq.{tenant}", enabled="eq.true")
            scenarios += [sc.from_dashboard(r) for r in custom
                          if r["agent_id"] in (None, agent_id) and (r.get("spec") or {}).get("source") != "generated"]
        except Exception:
            pass
        scenarios += sc.knowledge_scenarios(await knowledge_questions(tenant, agent_id, ktext))

        total = len(scenarios) * job["runs_per_scenario"]
        await report_progress(job["id"], "talking", 0, total)

        async def progress(done: int, total: int, passed: int) -> None:
            heartbeat.beat("tests")
            await report_progress(job["id"], "talking", done, total, passed)

        report = await run_suite(cfg, kb, scenarios, ktext, runs=job["runs_per_scenario"], settings=settings,
                                 max_reply_ms=MAX_REPLY_MS, concurrency=CONCURRENCY, progress=progress)
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


def _minutes_since(iso: str | None) -> float:
    if not iso:
        return 1e9
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 60


async def close_stalled() -> None:
    """Close "running" runs nobody is working on (D-105). A deploy starts the new server before stopping the old one,
    so a run can be claimed by the old one and then lost; a crash leaves one behind too. Progress is saved after
    every conversation, so 10 minutes without any means it is dead. It is closed as failed, not re-queued: re-queuing
    a run that crashed the worker made it crash again after every restart (the October crash loop)."""
    rows = await supa.select("eval_runs", select="id,created_at,results", status="eq.running")
    for r in rows:
        if r["id"] == CURRENT.get("id"):
            continue
        last = ((r.get("results") or {}).get("progress") or {}).get("updated_at") or r["created_at"]
        if _minutes_since(last) >= STALE_MIN:
            async with supa.client() as c:
                await c.patch("/rest/v1/eval_runs", params={"id": f"eq.{r['id']}", "status": "eq.running"},
                              json={"status": "failed", "error": STALLED, "finished_at": datetime.now(timezone.utc).isoformat()})
            log.warning("closed stalled run %s", r["id"])


def _hand_back_on_shutdown() -> None:
    """On SIGTERM (Render stopping this server for a deploy or restart), put the run in progress back in the queue so
    the next server picks it up at once. An out-of-memory kill is SIGKILL and never reaches here, so a run that
    crashes the worker is not retried forever; close_stalled closes it instead."""
    def handler(signum, frame):
        run_id = CURRENT.get("id")
        if run_id:
            url, key = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_SERVICE_ROLE_KEY"]
            try:
                httpx.patch(f"{url}/rest/v1/eval_runs", params={"id": f"eq.{run_id}", "status": "eq.running"},
                            json={"status": "queued", "results": None}, timeout=5,
                            headers={"apikey": key, "Authorization": f"Bearer {key}"})
                log.info("shutting down: run %s handed back to the queue", run_id)
            except Exception as e:
                log.warning("shutting down: could not hand back run %s (%s)", run_id, e)
        os._exit(0)
    try:
        signal.signal(signal.SIGTERM, handler)
    except (ValueError, AttributeError):   # not the main thread, or a platform without SIGTERM: keep the default
        pass


async def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    _hand_back_on_shutdown()
    log.info("test worker waiting for runs")
    swept = 0.0
    while True:
        if asyncio.get_running_loop().time() - swept > 60:
            swept = asyncio.get_running_loop().time()
            try:
                await close_stalled()
            except Exception as e:
                log.info("stalled-run check failed: %s", e)
        try:
            job = await claim()
        except Exception as e:
            log.warning("poll failed: %s", e)
            await asyncio.sleep(5)
            continue
        heartbeat.beat("tests")
        if job:
            log.info("running tests for agent %s v%s", job["agent_id"], job["agent_version"])
            CURRENT["id"] = job["id"]
            try:
                await run_job(job)
            finally:
                CURRENT.pop("id", None)
        else:
            await asyncio.sleep(3)


if __name__ == "__main__":
    asyncio.run(main())
