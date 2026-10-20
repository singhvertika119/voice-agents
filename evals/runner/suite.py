"""Run many scenarios several times each and summarise: pass rate per scenario, overall verdict, speed."""
from __future__ import annotations

import asyncio
import math
import time

from agent_worker.config import AgentConfig
from agent_worker.knowledge import KnowledgeBase

from .harness import run_conversation
from .scoring import fixed_checks, judge, run_passed


def p95(xs: list[int]) -> int | None:
    if not xs:
        return None
    s = sorted(xs)
    return s[min(len(s) - 1, math.ceil(0.95 * len(s)) - 1)]


async def run_suite(cfg: AgentConfig, kb: KnowledgeBase, scenarios: list[dict], knowledge_text: str, *,
                    runs: int | None = None, settings: dict | None = None, concurrency: int = 3,
                    max_reply_ms: int = 3000, progress=None) -> dict:
    sem = asyncio.Semaphore(concurrency)
    all_reply_ms: list[int] = []
    jobs = [(s, i) for s in scenarios for i in range(runs or s["runs"])]
    done = 0

    async def one(s: dict, i: int) -> dict:
        nonlocal done
        async with sem:
            try:
                convo = await run_conversation(cfg, kb, s, settings)
                fixed = fixed_checks(convo, s["checks"])
                j = await judge(convo, s, knowledge_text)
                res = {"run": i + 1, "passed": run_passed(fixed, j), "fixed": fixed, "judge": j, **convo}
            except Exception as e:
                res = {"run": i + 1, "passed": False, "fixed": {"no_error": False}, "judge": {"reason": str(e)}, "transcript": [],
                       "tool_calls": [], "reply_ms": [], "error": f"{type(e).__name__}: {e}"}
        all_reply_ms.extend(res["reply_ms"])
        done += 1
        if progress:
            await progress(done, len(jobs))
        return res

    t0 = time.time()
    results = await asyncio.gather(*(one(s, i) for s, i in jobs))
    by: dict[str, list[dict]] = {}
    for (s, _), r in zip(jobs, results):
        by.setdefault(s["name"], []).append(r)
    report = []
    for s in scenarios:
        rs = by.get(s["name"], [])
        rate = sum(r["passed"] for r in rs) / len(rs) if rs else 0.0
        report.append({"name": s["name"], "source": s.get("source", "standard"), "runs": len(rs), "pass_rate": round(rate, 2),
                       "required": s["pass_rate"], "passed": rate >= s["pass_rate"], "results": rs})
    speed = p95(all_reply_ms)
    n_pass = sum(r["passed"] for r in report)
    return {
        "scenarios": report, "scenarios_passed": n_pass, "scenarios_total": len(report),
        "pass_rate": round(n_pass / len(report), 2) if report else 0.0,
        "passed": bool(report) and n_pass == len(report) and (speed is None or speed <= max_reply_ms),
        "p95_reply_ms": speed, "p50_reply_ms": sorted(all_reply_ms)[len(all_reply_ms) // 2] if all_reply_ms else None,
        "reply_limit_ms": max_reply_ms, "seconds": round(time.time() - t0, 1),
        "note": "Text test: speed covers the model and document search only. In a live call add about 0.6 s of end-of-speech "
                "wait and 0.4 s for the voice to start.",
    }
