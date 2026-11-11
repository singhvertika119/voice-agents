"""One chat-completion helper for background work: call summaries, the knowledge quality check, test conversations.

Uses the workspace's own OpenAI key when it has a working one and the owner chose to use it for everything (D-124,
D-125); by default the key is kept for live calls and this work runs on the free Groq model. If OpenAI
refuses the key (no credits, invalid), that is saved on the key and the same request goes to Groq, so the work
still gets done. Live-call replies do not come through here: they use the LiveKit model chain in providers.py.
"""
from __future__ import annotations

import asyncio
import logging
import os

import httpx

from . import tenant_keys
from .tenant_keys import TenantKey

log = logging.getLogger("llm_chat")

OPENAI_URL = "https://api.openai.com/v1/chat/completions"
GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"
# Free tier on this key: 1,000 requests a day, 8,000 tokens a minute (measured 2026-11-11).
FREE_MODEL = os.getenv("FREE_LLM_MODEL", "openai/gpt-oss-120b")
REASONING_ROOM = 400   # gpt-oss thinks before it answers and that counts against max tokens
_UNSET = object()


class KeyRefused(Exception):
    pass


async def _post(url: str, auth: str, body: dict, timeout: float, check_key: bool = False) -> str:
    async with httpx.AsyncClient(timeout=timeout) as c:
        for attempt in range(4):
            r = await c.post(url, headers={"Authorization": f"Bearer {auth}"}, json=body)
            if r.status_code == 200:
                return r.json()["choices"][0]["message"]["content"] or ""
            if check_key and (verdict := tenant_keys.classify(r.status_code, r.text)):
                raise KeyRefused(verdict)
            if r.status_code in (429, 500, 502, 503) and attempt < 3:
                wait = r.headers.get("retry-after")
                await asyncio.sleep(min(float(wait), 20) if wait and wait.replace(".", "").isdigit() else 2 ** attempt)
                continue
            r.raise_for_status()
    raise RuntimeError("unreachable")


async def verify(key: TenantKey) -> str | None:
    """Ask OpenAI once (a 1-token reply) whether the key still works, and save the answer: ok, no_credits or invalid.
    None when OpenAI could not be reached. Used after a live call saw the key fail (D-125)."""
    try:
        async with httpx.AsyncClient(timeout=15) as c:
            r = await c.post(OPENAI_URL, headers={"Authorization": f"Bearer {key.value}"},
                             json={"model": "gpt-4o-mini", "max_tokens": 1, "messages": [{"role": "user", "content": "ok"}]})
    except Exception:  # noqa: BLE001
        return None
    status = "ok" if r.status_code == 200 else tenant_keys.classify(r.status_code, r.text)
    if status:
        await tenant_keys.record(key, status)
    return status


async def chat(messages: list[dict], *, model: str = "gpt-4.1-mini", temperature: float = 0.7, json_mode: bool = False,
               max_tokens: int = 400, timeout: float = 60, key: TenantKey | None | object = _UNSET) -> str:
    """The reply text. key defaults to the current job's workspace key (tenant_keys.use)."""
    k = tenant_keys.current() if key is _UNSET else key
    fmt = {"response_format": {"type": "json_object"}} if json_mode else {}
    if isinstance(k, TenantKey) and k.for_background():
        try:
            out = await _post(OPENAI_URL, k.value, {"model": model, "messages": messages, "temperature": temperature,
                                                    "max_tokens": max_tokens, **fmt}, timeout, check_key=True)
            if k.status != "ok":
                await tenant_keys.record(k, "ok")
            return out
        except KeyRefused as e:
            await tenant_keys.record(k, str(e))
        except Exception as e:  # noqa: BLE001
            log.warning("OpenAI request failed (%s); using the free model", str(e)[:120])
    groq = os.environ.get("GROQ_API_KEY")
    if not groq:
        raise RuntimeError("No model available: the workspace has no working OpenAI key and GROQ_API_KEY is not set")
    return await _post(GROQ_URL, groq, {"model": FREE_MODEL, "messages": messages, "temperature": temperature,
                                        "max_completion_tokens": max_tokens + REASONING_ROOM,
                                        "reasoning_effort": "low", **fmt}, timeout)
