"""Small OpenAI helper for the simulated caller, the judge and the scenario writer."""
from __future__ import annotations

import asyncio
import json
import os

import httpx

MODEL = os.getenv("EVAL_MODEL", "gpt-4.1-mini")          # simulated caller and scenario writer
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4.1")    # the reviewer is stricter and steadier with the larger model


async def chat(messages: list[dict], *, temperature: float = 0.7, json_mode: bool = False, max_tokens: int = 400,
               model: str | None = None) -> str:
    key = os.environ["OPENAI_API_KEY"]
    body = {"model": model or MODEL, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    async with httpx.AsyncClient(timeout=60) as c:
        for attempt in range(4):
            r = await c.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}"}, json=body)
            if r.status_code in (429, 500, 502, 503) and attempt < 3:
                await asyncio.sleep(2 ** attempt)
                continue
            r.raise_for_status()
            return r.json()["choices"][0]["message"]["content"]
    raise RuntimeError("unreachable")


async def chat_json(messages: list[dict], **kw) -> dict:
    return json.loads(await chat(messages, json_mode=True, **kw))
