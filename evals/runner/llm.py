"""Model helper for the simulated caller, the judge and the scenario writer.

Runs on the workspace's own OpenAI key when the test job set one (tenant_keys.use, D-124), otherwise on the free
model. The free model is a weaker judge than gpt-4.1, so test results without a key can be a little less strict.
"""
from __future__ import annotations

import json
import os

from vp_core import llm_chat

MODEL = os.getenv("EVAL_MODEL", "gpt-4.1-mini")          # simulated caller and scenario writer
JUDGE_MODEL = os.getenv("EVAL_JUDGE_MODEL", "gpt-4.1")    # the reviewer is stricter and steadier with the larger model


async def chat(messages: list[dict], *, temperature: float = 0.7, json_mode: bool = False, max_tokens: int = 400,
               model: str | None = None) -> str:
    return await llm_chat.chat(messages, model=model or MODEL, temperature=temperature, json_mode=json_mode,
                               max_tokens=max_tokens)


async def chat_json(messages: list[dict], **kw) -> dict:
    return json.loads(await chat(messages, json_mode=True, **kw))
