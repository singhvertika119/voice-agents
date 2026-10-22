"""Writes the LiveKit SIP dispatch rule that sends phone calls to one of your agents.

    uv run python scripts/make_dispatch_rule.py <agent id> [--trunk TRUNK_ID]

The rule names our worker (explicit dispatch) and sets the room prefix to 'live-<agent id>-'. LiveKit then names each
call's room '<prefix><caller number>_<random>', and the worker reads the agent from that name, the same way it does for
the dashboard test panel. One rule per agent; the call is answered by the agent's published version.

It checks the agent exists and is published, writes deploy/dispatch-<agent id>.json and prints the next commands.
"""
import json
import os
import sys
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "apps" / "agent-worker"))
sys.path.insert(0, str(ROOT / "packages" / "core"))

import asyncio  # noqa: E402

from agent_worker import db  # noqa: E402


def main() -> None:
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    trunk = sys.argv[sys.argv.index("--trunk") + 1] if "--trunk" in sys.argv else None
    if trunk in args:
        args.remove(trunk)
    if len(args) != 1 or not db.is_agent_uuid(args[0]):
        raise SystemExit("Usage: make_dispatch_rule.py <agent id (uuid)> [--trunk TRUNK_ID]")
    agent_id = args[0]
    pub = asyncio.run(db.fetch_published(agent_id))   # stops with a clear message if the agent is missing or unpublished
    name = pub["agent"]["name"]
    agent_name = os.getenv("AGENT_NAME", "voice-platform")

    rule = {
        "dispatch_rule": {
            "name": f"{name} (phone)",
            "rule": {"dispatchRuleIndividual": {"roomPrefix": f"live-{agent_id}-"}},
            "roomConfig": {"agents": [{"agentName": agent_name}]},
        }
    }
    if trunk:
        rule["dispatch_rule"]["trunk_ids"] = [trunk]
    out = ROOT / "deploy" / f"dispatch-{agent_id}.json"
    out.write_text(json.dumps(rule, indent=2) + "\n", encoding="utf-8")
    print(f"Agent: {name} (published v{pub['version']}), worker name: {agent_name}")
    print(f"Wrote {out.relative_to(ROOT)}\n")
    print("Next:")
    print(f"  lk sip dispatch create {out.relative_to(ROOT)}")
    print("  lk sip dispatch list")
    print("Then attach the rule to your number (LiveKit dashboard: Telephony > Phone numbers > the number > dispatch rule).")


if __name__ == "__main__":
    main()
