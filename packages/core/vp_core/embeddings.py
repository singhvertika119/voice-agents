"""Text embeddings. OpenAI text-embedding-3-small (1536 dims): multilingual enough for Hinglish questions
against English or Hindi documents, and costs ~$0.02 per million tokens (docs/decision.md D-034)."""
from __future__ import annotations

import asyncio
import os
from collections import OrderedDict

import httpx

MODEL = "text-embedding-3-small"
DIMS = 1536
_cache: OrderedDict[str, list[float]] = OrderedDict()  # query embeddings repeat within a call; keep the last 256


async def embed(texts: list[str], timeout: float = 30) -> list[list[float]]:
    key = os.environ["OPENAI_API_KEY"]
    out: list[list[float]] = []
    async with httpx.AsyncClient(timeout=timeout) as c:
        for i in range(0, len(texts), 64):
            batch = [t[:8000] for t in texts[i : i + 64]]
            for attempt in range(4):
                r = await c.post("https://api.openai.com/v1/embeddings",
                                 headers={"Authorization": f"Bearer {key}"}, json={"model": MODEL, "input": batch})
                if r.status_code in (429, 500, 502, 503) and attempt < 3:
                    await asyncio.sleep(2 ** attempt)
                    continue
                r.raise_for_status()
                break
            out += [d["embedding"] for d in sorted(r.json()["data"], key=lambda d: d["index"])]
    return out


async def embed_query(text: str) -> list[float]:
    if text in _cache:
        _cache.move_to_end(text)
        return _cache[text]
    vec = (await embed([text], timeout=8))[0]
    _cache[text] = vec
    if len(_cache) > 256:
        _cache.popitem(last=False)
    return vec


def to_pg(vec: list[float]) -> str:
    """pgvector text format."""
    return "[" + ",".join(f"{x:.6f}" for x in vec) + "]"
