"""Intake -> Parse -> Chunk -> Index -> Quality gate -> Ready. One source at a time; every failure becomes
a readable message on the source row (docs/decision.md D-033 to D-037)."""
from __future__ import annotations

import asyncio
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
        return await asyncio.to_thread(parsers.parse_html, await fetch_public_html(src["url"]))
    if t == "file":
        try:
            data = await supa.download("knowledge", src["storage_path"])
        except FileNotFoundError as e:
            raise ParseError("The uploaded file could not be found. Upload it again.") from e
        if len(data) > MAX_FILE_BYTES:
            raise ParseError("This file is larger than 15 MB. Split it or upload a smaller copy.")
        # CPU-heavy (a large PDF takes seconds): run it in a thread so the health page and the test worker keep going.
        return await asyncio.to_thread(parsers.parse_file, src["file_kind"] or "", data, src["name"])
    raise ParseError("Unknown source type.")


async def process(src: dict) -> None:
    sid = src["id"]
    try:
        parsed = await load_and_parse(src)
        await index(src, parsed)
    except ParseError as e:
        await _status(sid, "failed", error=str(e))
    except Exception:
        log.exception("ingestion failed for %s", sid)
        await _status(sid, "failed", error="Something went wrong while processing this source. Try again, and contact support if it keeps happening.")


def content_hash(parsed: Parsed) -> str:
    return hashlib.sha256((parsed.markdown + json.dumps([t.rows for t in parsed.tables], default=str)).encode()).hexdigest()


async def index(src: dict, parsed: Parsed, live: bool = False) -> None:
    """Chunk, embed, store and test a parsed source. live=True is a refresh of a source agents are already using
    (D-108): the status stays "ready" until the end instead of passing through indexing/testing, so calls keep the
    source, and everything that can fail (chunking, embedding) happens before the old sections are removed."""
    sid, tenant = src["id"], src["tenant_id"]
    chash = content_hash(parsed)
    if not live:
        await _status(sid, "indexing", parsed_md=parsed.markdown[:200_000], content_hash=chash)

    chunks = chunk_markdown(parsed.markdown, doc_title=src["name"])
    if len(chunks) > MAX_CHUNKS:
        raise ParseError(f"This is very large ({len(chunks)} sections). Split it into smaller documents.")
    if not chunks and not parsed.tables:
        raise ParseError("Nothing readable was found in this source.")
    vecs = await embeddings.embed([c.content for c in chunks]) if chunks else []

    # Rebuild from scratch: indexing is idempotent, so a retry never duplicates chunks.
    await supa.delete("kb_chunks", {"source_id": sid})
    await supa.delete("kb_tables", {"source_id": sid})
    if chunks:
        rows = [{"tenant_id": tenant, "source_id": sid, "idx": c.idx, "section": c.section, "content": c.content,
                 "tokens": c.tokens, "embedding": embeddings.to_pg(v)} for c, v in zip(chunks, vecs)]
        for i in range(0, len(rows), 100):
            await supa.insert("kb_chunks", rows[i : i + 100])
    if parsed.tables:
        await supa.insert("kb_tables", [{"tenant_id": tenant, "source_id": sid, "name": t.name,
                                         "columns": t.columns, "rows": t.rows} for t in parsed.tables])

    stats = {"chunks": len(chunks), "tokens": sum(c.tokens for c in chunks),
             "tables": [{"name": t.name, "rows": len(t.rows)} for t in parsed.tables]}
    if live:
        now = datetime.now(timezone.utc).isoformat()
        stats.update(checked_at=now, refreshed_at=now)
    else:
        await _status(sid, "testing", stats=stats)
    quality = await quality_gate(tenant, sid, chunks, faq=parsed.kind == "faq")
    stats["quality"] = quality
    ok = quality["tested"] == 0 or quality["hit_rate"] >= HIT_RATE_MIN
    extra = {"parsed_md": parsed.markdown[:200_000], "content_hash": chash} if live else {}
    problem = ("The website changed and some questions about the new content did not find the right passage. Review the parsed text."
               if live else "Some questions about this content did not find the right passage. Review the parsed text and make it clearer.")
    await _status(sid, "ready" if ok else "needs_review", stats=stats, error=None if ok else problem, **extra)
    log.info("source %s -> %s (%d chunks, hit rate %s)%s", sid, "ready" if ok else "needs_review", len(chunks),
             quality.get("hit_rate"), " after a website change" if live else "")


# ------------------------------------------------------------------ website refresh
REFRESH_DAYS = int(os.getenv("WEBSITE_REFRESH_DAYS", "7"))


def _days_since(iso: str | None) -> float:
    if not iso:
        return 1e9
    return (datetime.now(timezone.utc) - datetime.fromisoformat(iso.replace("Z", "+00:00"))).total_seconds() / 86400


async def refresh_websites() -> int:
    """Re-read website sources not checked for REFRESH_DAYS (D-108). Unchanged: only the check time is saved. Changed:
    re-indexed in place (see index(live=True)); agents' saved test questions follow automatically, because they are
    tied to a fingerprint of the knowledge. Site unreachable or unreadable: the old content stays and the problem is
    noted. Returns how many sources changed."""
    rows = await supa.select("knowledge_sources", select="id,tenant_id,name,source_type,url,content_hash,stats,updated_at",
                             source_type="eq.url", status="eq.ready")
    changed = 0
    for src in rows:
        stats = src.get("stats") or {}
        if _days_since(stats.get("checked_at") or src["updated_at"]) < REFRESH_DAYS:
            continue
        now = datetime.now(timezone.utc).isoformat()
        try:
            parsed = await load_and_parse(src)
            if content_hash(parsed) == src.get("content_hash"):
                await supa.update("knowledge_sources", {"id": src["id"]}, {"stats": {**stats, "checked_at": now, "check_error": None}})
                continue
            await index(src, parsed, live=True)
            changed += 1
        except Exception as e:
            msg = str(e) if isinstance(e, ParseError) else "The website could not be read this time."
            log.info("website refresh skipped for %s: %s", src["id"], str(e)[:120])
            await supa.update("knowledge_sources", {"id": src["id"]}, {"stats": {**stats, "checked_at": now, "check_error": msg}})
    return changed


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
