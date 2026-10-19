"""Intake -> Parse -> Chunk -> Index -> Quality gate -> Ready. One source at a time; every failure becomes
a readable message on the source row (docs/decision.md D-033 to D-037)."""
from __future__ import annotations

import hashlib
import json
import logging
import os
import random
import re
from datetime import datetime, timezone

import httpx
from vp_core import embeddings, supa

from . import parsers
from .chunking import Chunk, chunk_markdown
from .netsafe import fetch_public_html
from .parsers import ParseError, Parsed

log = logging.getLogger("ingest")
HIT_RATE_MIN = 0.6       # below this a source needs review instead of going live
MAX_TEST_CHUNKS = 12
MAX_CHUNKS = 600         # per-source cap (plan: per-tenant limits)
MAX_FILE_BYTES = 15_000_000


async def _status(source_id: str, status: str, **extra):
    await supa.update("knowledge_sources", {"id": source_id}, {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **extra})


async def claim_next() -> dict | None:
    rows = await supa.select("knowledge_sources", select="*", status="eq.queued", order="created_at.asc", limit="1")
    if not rows:
        return None
    # Atomic claim: only one worker flips queued -> parsing.
    async with supa.client() as c:
        r = await c.patch("/rest/v1/knowledge_sources", params={"id": f"eq.{rows[0]['id']}", "status": "eq.queued"},
                          json={"status": "parsing", "error": None})
        r.raise_for_status()
        claimed = r.json()
    return claimed[0] if claimed else None


async def load_and_parse(src: dict) -> Parsed:
    t = src["source_type"]
    if t == "text":
        return parsers.parse_text(src["raw_text"] or "")
    if t == "faq":
        return parsers.parse_faq(src["raw_text"] or "")
    if t == "url":
        return parsers.parse_html(await fetch_public_html(src["url"]))
    if t == "file":
        try:
            data = await supa.download("knowledge", src["storage_path"])
        except FileNotFoundError as e:
            raise ParseError("The uploaded file could not be found. Upload it again.") from e
        if len(data) > MAX_FILE_BYTES:
            raise ParseError("This file is larger than 15 MB. Split it or upload a smaller copy.")
        return parsers.parse_file(src["file_kind"] or "", data, src["name"])
    raise ParseError("Unknown source type.")


async def process(src: dict) -> None:
    sid, tenant = src["id"], src["tenant_id"]
    try:
        parsed = await load_and_parse(src)
        chash = hashlib.sha256((parsed.markdown + json.dumps([t.rows for t in parsed.tables], default=str)).encode()).hexdigest()
        await _status(sid, "indexing", parsed_md=parsed.markdown[:200_000], content_hash=chash)

        chunks = chunk_markdown(parsed.markdown, doc_title=src["name"])
        if len(chunks) > MAX_CHUNKS:
            raise ParseError(f"This is very large ({len(chunks)} sections). Split it into smaller documents.")
        if not chunks and not parsed.tables:
            raise ParseError("Nothing readable was found in this source.")

        # Rebuild from scratch: indexing is idempotent, so a retry never duplicates chunks.
        await supa.delete("kb_chunks", {"source_id": sid})
        await supa.delete("kb_tables", {"source_id": sid})
        rows = []
        if chunks:
            vecs = await embeddings.embed([c.content for c in chunks])
            rows = [{"tenant_id": tenant, "source_id": sid, "idx": c.idx, "section": c.section, "content": c.content,
                     "tokens": c.tokens, "embedding": embeddings.to_pg(v)} for c, v in zip(chunks, vecs)]
            for i in range(0, len(rows), 100):
                await supa.insert("kb_chunks", rows[i : i + 100])
        if parsed.tables:
            await supa.insert("kb_tables", [{"tenant_id": tenant, "source_id": sid, "name": t.name,
                                             "columns": t.columns, "rows": t.rows} for t in parsed.tables])

        stats = {"chunks": len(chunks), "tokens": sum(c.tokens for c in chunks),
                 "tables": [{"name": t.name, "rows": len(t.rows)} for t in parsed.tables]}
        await _status(sid, "testing", stats=stats)
        quality = await quality_gate(tenant, sid, chunks, faq=parsed.kind == "faq")
        stats["quality"] = quality
        ok = quality["tested"] == 0 or quality["hit_rate"] >= HIT_RATE_MIN
        await _status(sid, "ready" if ok else "needs_review", stats=stats,
                      error=None if ok else "Some questions about this content did not find the right passage. Review the parsed text and make it clearer.")
        log.info("source %s -> %s (%d chunks, hit rate %s)", sid, "ready" if ok else "needs_review", len(chunks), quality.get("hit_rate"))
    except ParseError as e:
        await _status(sid, "failed", error=str(e))
    except Exception:
        log.exception("ingestion failed for %s", sid)
        await _status(sid, "failed", error="Something went wrong while processing this source. Try again, and contact support if it keeps happening.")


# ------------------------------------------------------------------ quality gate
async def _questions_from_llm(chunks: list[Chunk]) -> list[str]:
    """One short caller-style question per chunk, in varied Hindi/English/Hinglish so the test is not trivial."""
    key = os.environ["OPENAI_API_KEY"]
    passages = "\n".join(f"{i + 1}. {c.content[:600]}" for i, c in enumerate(chunks))
    prompt = (
        "For each numbered passage, write ONE short question a phone caller might ask that the passage answers. "
        "Do not copy sentences from the passage. Mix styles: plain English, Hindi in Roman letters (Hinglish), or Devanagari. "
        f'Return JSON: {{"questions": ["...", ...]}} with exactly {len(chunks)} items in order.\n\n{passages}'
    )
    async with httpx.AsyncClient(timeout=60) as c:
        r = await c.post("https://api.openai.com/v1/chat/completions", headers={"Authorization": f"Bearer {key}"},
                         json={"model": "gpt-4.1-mini", "temperature": 0.7, "response_format": {"type": "json_object"},
                               "messages": [{"role": "user", "content": prompt}]})
        r.raise_for_status()
    qs = json.loads(r.json()["choices"][0]["message"]["content"]).get("questions", [])
    return [str(q) for q in qs][: len(chunks)]


async def quality_gate(tenant: str, source_id: str, chunks: list[Chunk], faq: bool) -> dict:
    if not chunks:
        return {"tested": 0, "hit_rate": 1.0, "failed": []}
    rnd = random.Random(source_id)
    sample = chunks if len(chunks) <= MAX_TEST_CHUNKS else rnd.sample(chunks, MAX_TEST_CHUNKS)
    if faq:  # the real question is the best test for an FAQ
        qs = [c.section for c in sample]
    else:
        try:
            qs = await _questions_from_llm(sample)
        except Exception:
            log.exception("question generation failed; skipping quality gate for %s", source_id)
            return {"tested": 0, "hit_rate": 1.0, "failed": [], "note": "Quality check was skipped."}
    pairs = [(c, q) for c, q in zip(sample, qs) if q.strip()]
    vecs = await embeddings.embed([q for _, q in pairs])
    hits, failed = 0, []
    for (chunk, q), vec in zip(pairs, vecs):
        found = await supa.rpc("match_chunks", {"p_sources": [source_id], "p_embedding": embeddings.to_pg(vec),
                                                "p_query": q, "p_k": 3, "p_tenant": tenant})
        if any(f["content"] == chunk.content for f in found):
            hits += 1
        else:
            failed.append({"question": q, "section": chunk.section, "passage": chunk.content[:160]})
    n = len(pairs)
    return {"tested": n, "hit_rate": round(hits / n, 2) if n else 1.0, "failed": failed[:5]}
