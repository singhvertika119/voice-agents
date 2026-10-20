"""Scoring: fixed checks (exact, cheap, repeatable) plus a written-rubric judge for tone, language and grounding."""
from __future__ import annotations

from . import llm


def agent_text(convo: dict) -> list[str]:
    return [t["text"] for t in convo["transcript"] if t["speaker"] == "agent" and not t.get("greeting") and t["text"]]


from agent_worker.language import style  # noqa: E402


def language_follows(convo: dict) -> bool:
    """English callers must get English replies. Hindi callers may get Roman or Devanagari Hindi (both are Hindi to
    the voice), and code-switching Hinglish is not judged. The greeting is not counted."""
    last = None
    for t in convo["transcript"]:
        if t.get("greeting"):
            continue
        if t["speaker"] == "caller":
            last = style(t["text"])
        elif last == "english" and t["text"] and style(t["text"]) != "english":
            return False
    return True


_YES = ("haan", "han ", "yes", "ji ", "sahi", "correct", "theek", "thik", "ok", "right", "bilkul", "confirm", "हाँ", "हां", "सही", "ठीक")


def booked_after_yes(convo: dict) -> bool:
    """If a callback was actually booked, the caller message right before the turn that booked it must be a clear yes.
    Done in code because a model judge kept misreading the order of events (D-048). A refused attempt (the tool
    says "not confirmed") books nothing and is fine."""
    if not convo.get("backend", {}).get("callbacks"):
        return True
    prev, ok = "", False
    for t in convo["transcript"]:
        if t["speaker"] == "caller":
            prev = t["text"].casefold() + " "
        elif "schedule_callback" in (t.get("tools") or []):
            ok = any(y in prev for y in _YES)   # the last attempt that could have booked decides
    return ok


def fixed_checks(convo: dict, checks: dict) -> dict[str, bool]:
    said = agent_text(convo)
    blob = " ".join(said).casefold()
    called = [c["name"] for c in convo["tool_calls"]]
    out: dict[str, bool] = {"no_error": convo["error"] is None, "agent_replied": bool(said)}
    if checks.get("must_say_any"):
        out["says_expected_words"] = any(w.casefold() in blob for w in checks["must_say_any"])
    if checks.get("must_not_say"):
        out["avoids_forbidden_words"] = not any(w.casefold() in blob for w in checks["must_not_say"])
    if checks.get("must_not_match"):   # regular expressions, for example any 10-digit number the agent made up
        import re
        out["no_forbidden_pattern"] = not any(re.search(rx, blob) for rx in checks["must_not_match"])
    if checks.get("asks_question"):
        out["asks_a_question"] = "?" in " ".join(said)
    for t in checks.get("tools_called", []):
        out[f"called_{t}"] = t in called
    for t in checks.get("tools_not_called", []):
        out[f"did_not_call_{t}"] = t not in called
    out["replies_in_callers_language"] = language_follows(convo)
    if convo.get("backend", {}).get("callbacks") or "schedule_callback" in called:
        out["booked_only_after_a_yes"] = booked_after_yes(convo)
    cap = checks.get("max_words_per_turn")
    if cap:
        out["short_enough_for_voice"] = all(len(s.split()) <= cap for s in said)
    return out


async def judge(convo: dict, scenario: dict, knowledge_text: str) -> dict:
    # The opening greeting is left out (it is fixed text, not a reply). Tool use is shown where it happened.
    lines = "\n".join(
        f"{'CALLER' if t['speaker'] == 'caller' else 'AGENT'}: {t['text']}"
        + (f"  [agent used tool: {', '.join(t['tools'])}]" if t.get("tools") else "")
        for t in convo["transcript"] if not t.get("greeting"))
    tools = ", ".join(f"{c['name']}({c['arguments']})" for c in convo["tool_calls"]) or "none"
    prompt = (
        "You are a strict quality reviewer of a phone agent for a business. Review the conversation.\n\n"
        f"What the caller wanted: {scenario['goal']}\n"
        f"Rubric for this test: {scenario.get('judge') or 'The agent helps correctly, briefly and politely.'}\n\n"
        f"The ONLY facts the agent is allowed to state (its knowledge):\n{knowledge_text[:30000] or '(none given)'}\n\n"
        f"Conversation:\n{lines}\n\nTools the agent used: {tools}\n\n"
        'Return JSON: {"meets_rubric": bool, "grounded": bool (no invented facts beyond the knowledge; greetings and '
        'offers of help are fine), "tone": 1-5, '
        '"reason": "one short sentence"}'
    )
    try:
        j = await llm.chat_json([{"role": "user", "content": prompt}], temperature=0, max_tokens=250, model=llm.JUDGE_MODEL)
    except Exception as e:
        return {"meets_rubric": False, "grounded": False, "tone": 0, "reason": f"judge failed: {e}"}
    j["tone"] = int(j.get("tone", 0) or 0)
    return j


def run_passed(fixed: dict[str, bool], j: dict) -> bool:
    return (all(fixed.values()) and bool(j.get("meets_rubric")) and bool(j.get("grounded"))
            and j.get("tone", 0) >= 3)
