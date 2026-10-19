"""After the call: one model call turns the redacted transcript into a summary, a structured record and an updated
caller memory. Runs after the caller has hung up, so it never touches reply time (docs/decision.md D-053)."""
from __future__ import annotations

import json
import logging
import os

import httpx

from .pii import redact

log = logging.getLogger("postcall")
MODEL = os.getenv("SUMMARY_MODEL", "gpt-4.1-mini")
MAX_TRANSCRIPT_CHARS = 12000


async def summarize(turns: list[dict], prior_summary: str = "", prior_facts: dict | None = None,
                    tool_log: list | None = None, with_memory: bool = True) -> dict | None:
    """Returns {summary, intent, outcome, commitments, open_items, language, name, rolling_summary, facts} or None."""
    lines = [f"{'CALLER' if t['speaker'] == 'caller' else 'AGENT'}: {redact(t['text'])}" for t in turns if t.get("text")]
    if not lines:
        return None
    transcript = "\n".join(lines)[-MAX_TRANSCRIPT_CHARS:]
    memory_part = (
        "Also update the long-term memory about this caller. Previous memory (may be empty):\n"
        f"{prior_summary or '(none)'}\nPrevious facts: {json.dumps(prior_facts or {}, ensure_ascii=False)}\n"
        'Add "rolling_summary" (English, at most 250 words, keep what still matters, drop what is resolved or outdated) '
        'and "facts" (small JSON object of stable facts such as name, family details the caller shared, preferences; '
        "never numbers like Aadhaar, PAN, card or account). Never record what the agent could or could not remember or "
        "access; only record what the caller wanted and what was done. "
    ) if with_memory else ""
    prompt = (
        "Summarise this phone call between a business's AI agent and a caller. The text is Hindi, English or Hinglish; "
        "write the summary in English.\n\n" + transcript + "\n\n"
        f"Tools the agent used: {', '.join(t['tool'] for t in (tool_log or [])) or 'none'}\n\n" + memory_part +
        'Return JSON with: "summary" (2-3 sentences), "intent" (what the caller wanted, a few words), '
        '"outcome" (one of resolved, handed_off, callback, dropped), "commitments" (list of things the business promised), '
        '"open_items" (list of things still unresolved), "language" (hindi, english or hinglish), "name" (caller name if '
        "they said it, else empty)."
    )
    try:
        async with httpx.AsyncClient(timeout=45) as c:
            r = await c.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {os.environ['OPENAI_API_KEY']}"},
                             json={"model": MODEL, "temperature": 0, "response_format": {"type": "json_object"},
                                   "messages": [{"role": "user", "content": prompt}], "max_tokens": 900})
            r.raise_for_status()
        out = json.loads(r.json()["choices"][0]["message"]["content"])
        if out.get("outcome") not in ("resolved", "handed_off", "callback", "dropped"):
            out["outcome"] = None
        return out
    except Exception as e:
        log.warning("summary failed: %s", e)
        return None
