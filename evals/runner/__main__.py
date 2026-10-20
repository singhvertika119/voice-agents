"""Run the test conversations from a terminal.

    python -m evals.runner --agent sunrise-clinic                # an agents/*.yaml file
    python -m evals.runner --agent <uuid> --version live         # an agent from the database (draft | live)
    options: --runs 3  --only unknown   --no-auto   --out report.json
"""
from __future__ import annotations

import argparse
import asyncio
import json
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "apps/agent-worker"), str(ROOT / "packages/core"), str(ROOT)]
load_dotenv(ROOT / ".env", override=True)

from agent_worker.config import from_dict, load_agent  # noqa: E402
from agent_worker.knowledge import KnowledgeBase  # noqa: E402

from . import scenarios as sc  # noqa: E402
from .suite import run_suite  # noqa: E402


def show(report: dict) -> None:
    print()
    for s in report["scenarios"]:
        print(f"{'PASS' if s['passed'] else 'FAIL'}  {s['pass_rate']:.0%} of {s['runs']}  [{s['source']}] {s['name']}")
        for r in s["results"]:
            if not r["passed"]:
                bad = [k for k, v in r["fixed"].items() if not v]
                print(f"        run {r['run']} failed: checks={bad or 'ok'} judge={r['judge'].get('reason')}")
                if r.get("error"):
                    print("        error:", r["error"])
    print(f"\n{report['scenarios_passed']}/{report['scenarios_total']} scenarios passed. Speed p50 {report['p50_reply_ms']} ms, "
          f"p95 {report['p95_reply_ms']} ms (limit {report['reply_limit_ms']} ms). Took {report['seconds']} s.")
    print("OVERALL:", "PASSED" if report["passed"] else "FAILED")


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default="sunrise-clinic")
    ap.add_argument("--version", default="live")
    ap.add_argument("--runs", type=int)
    ap.add_argument("--only", default="")
    ap.add_argument("--pack", default="standard", help="standard | grounding | all")
    ap.add_argument("--no-auto", action="store_true")
    ap.add_argument("--out", default="")
    ap.add_argument("--fixed", default="", help="file of generated scenarios: reused if it exists, so before/after runs ask the same questions")
    ap.add_argument("--size", default="6,5,5", help="answerable,unanswerable,false-claim questions to generate")
    a = ap.parse_args()

    kb, ktext = KnowledgeBase(), ""
    if len(a.agent) == 36:
        from agent_worker import db
        from agent_worker.knowledge import load_knowledge
        pub = await (db.fetch_latest(a.agent) if a.version == "draft" else db.fetch_published(a.agent))
        cfg = from_dict(a.agent, pub["agent"]["name"], pub["config"])
        kb = await load_knowledge(cfg.knowledge_sources, pub["agent"]["tenant_id"])
        ktext = kb.prompt_text
    else:
        cfg = load_agent(a.agent)
    ktext = (cfg.knowledge + "\n" + ktext).strip()

    scenarios = sc.load_standard() if a.pack in ("standard", "all") else []
    if a.pack in ("grounding", "all") and a.agent == "sunrise-clinic":
        scenarios += sc.load_pack("grounding")
    if not a.no_auto and a.pack in ("standard", "all", "auto"):
        fixed = Path(a.fixed) if a.fixed else None
        if fixed and fixed.exists():
            scenarios += json.loads(fixed.read_text(encoding="utf-8"))
        else:
            n1, n2, n3 = (int(x) for x in a.size.split(","))
            gen = await sc.from_knowledge(ktext, n1, n2, n3)
            if fixed:
                fixed.write_text(json.dumps(gen, ensure_ascii=False, indent=1), encoding="utf-8")
            scenarios += gen
    if a.only:
        scenarios = [s for s in scenarios if a.only.casefold() in s["name"].casefold()]
    print(f"Running {len(scenarios)} scenarios against '{cfg.name}' ...")
    report = await run_suite(cfg, kb, scenarios, ktext, runs=a.runs)
    show(report)
    if a.out:
        Path(a.out).write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
