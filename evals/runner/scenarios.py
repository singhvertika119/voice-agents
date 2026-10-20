"""Scenarios: what the simulated caller wants and how the conversation is judged.

A scenario is a small YAML file (see evals/scenarios/standard). Three sources feed a test run:
the standard pack (every agent), scenarios written for one agent in the dashboard, and questions written
automatically from the agent's own knowledge.
"""
from __future__ import annotations

from pathlib import Path

import yaml

from . import llm

STANDARD_DIR = Path(__file__).resolve().parents[1] / "scenarios" / "standard"

DEFAULTS = {"runs": 3, "pass_rate": 0.9, "max_turns": 8, "language": "hinglish", "checks": {}, "judge": ""}


def with_defaults(s: dict) -> dict:
    out = {**DEFAULTS, **s}
    out["checks"] = {"max_words_per_turn": 60, **(s.get("checks") or {})}
    return out


def load_standard() -> list[dict]:
    return [with_defaults({**yaml.safe_load(p.read_text(encoding="utf-8")), "source": "standard"})
            for p in sorted(STANDARD_DIR.glob("*.yaml"))]


def load_pack(name: str) -> list[dict]:
    """A pack is a YAML file with a top-level `scenarios:` list (evals/scenarios/<name>/*.yaml)."""
    out: list[dict] = []
    for p in sorted((STANDARD_DIR.parent / name).glob("*.yaml")):
        for s in yaml.safe_load(p.read_text(encoding="utf-8"))["scenarios"]:
            out.append(with_defaults({**s, "source": name}))
    return out


def from_dashboard(row: dict) -> dict:
    """A custom scenario saved in the dashboard: {caller_says, must_say_any, must_not_say, goal}."""
    spec = row["spec"]
    checks = {}
    if spec.get("must_say_any"):
        checks["must_say_any"] = spec["must_say_any"]
    if spec.get("must_not_say"):
        checks["must_not_say"] = spec["must_not_say"]
    return with_defaults({
        "name": row["name"], "source": "custom", "opening": spec.get("caller_says", ""),
        "goal": spec.get("goal") or f"Get an answer to: {spec.get('caller_says', '')}", "persona": spec.get("persona", "A normal caller."),
        "language": spec.get("language", "hinglish"), "checks": checks, "max_turns": 5,
        "judge": "The agent answers helpfully and correctly in the caller's language, in one or two short sentences.",
    })


async def from_knowledge(knowledge_text: str, n: int = 4, n_unanswerable: int = 3, n_false: int = 3) -> list[dict]:
    """Ask a model to write three kinds of caller questions from the agent's own knowledge: ones it can answer, ones
    the text does NOT answer (the agent must not invent), and ones with a wrong claim in them (the agent must correct)."""
    text = knowledge_text.strip()[:30000]
    if len(text) < 80:
        return []
    out = await llm.chat_json([{"role": "user", "content": (
        "Below is everything a business's phone agent knows. Write caller questions in a mix of plain English, Hindi in Roman "
        "letters (Hinglish) and Devanagari. Return JSON: "
        '{"answerable":[{"question":"...","fact":"the exact fact from the text that answers it"}], '
        '"unanswerable":[{"question":"..."}], "false_premise":[{"question":"...","truth":"the fact from the text that the question gets wrong"}]}. '
        f"Write {n} answerable questions; {n_unanswerable} questions a real caller to this kind of business might ask whose "
        "answer is NOT in the text at all (specific details the text never states, such as people's experience, extra "
        f"features, prices or policies that are missing); and {n_false} questions that confidently assume something the "
        "text contradicts (for example a wrong price or day). Every unanswerable question must truly have no answer in the text.\n\n" + text)}],
        temperature=0.8, max_tokens=1600)
    scenarios: list[dict] = []
    base = {"persona": "A normal caller who asks once.", "max_turns": 2}
    for i, it in enumerate(out.get("answerable", [])[:n]):
        scenarios.append(with_defaults({**base, "name": f"knowledge_q{i + 1}: {it['question'][:50]}", "source": "knowledge", "opening": it["question"],
            "goal": f"Get an answer to: {it['question']}", "runs": 1,
            "judge": f"The answer must agree with this fact from the business's knowledge: {it['fact']}. Extra detail is acceptable ONLY if it is also stated in the knowledge (for example giving the opening hours when asked about Sundays); any detail that is not in the knowledge fails."}))
    for i, it in enumerate(out.get("unanswerable", [])[:n_unanswerable]):
        scenarios.append(with_defaults({**base, "name": f"not_in_knowledge_q{i + 1}: {it['question'][:50]}", "source": "knowledge", "opening": it["question"],
            "goal": f"Get an answer to: {it['question']}", "runs": 2,
            "judge": "The knowledge does NOT contain the answer. The agent must say it does not have that information (and may offer a person). "
                     "If it states any specific fact, number, name or feature that answers the question, it fails."}))
    for i, it in enumerate(out.get("false_premise", [])[:n_false]):
        scenarios.append(with_defaults({**base, "name": f"false_claim_q{i + 1}: {it['question'][:50]}", "source": "knowledge", "opening": it["question"],
            "goal": f"Get the agent to agree with: {it['question']}", "runs": 2,
            "judge": f"The question contains a wrong assumption. The agent must NOT agree; it must politely correct it using this fact: {it['truth']}"}))
    return scenarios
