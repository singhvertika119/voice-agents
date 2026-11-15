"""Intake -> Parse -> Chunk -> Index -> Quality gate -> Ready. One source at a time; every failure becomes
a readable message on the source row (docs/decision.md D-033 to D-037)."""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import random
from datetime import datetime, timezone

from vp_core import embeddings, llm_chat, supa, tenant_keys

from . import parsers, site
from .chunking import Chunk, chunk_markdown
from .parsers import ParseError, Parsed

log = logging.getLogger("ingest")
HIT_RATE_MIN = 0.6       # below this a source needs review instead of going live
# A whole website has many pages that answer the same broad question, so a question written from one product page is
# often answered from another (D-110). Measured on nialabs.in: 50% to 67% between runs, with the misses landing on
# pages that also answer them. The check is there to catch unreadable text, so websites get a lower bar.
HIT_RATE_MIN_WEBSITE = 0.4
MAX_TEST_CHUNKS = 12
MAX_CHUNKS = 1000        # per-source cap (plan: per-tenant limits); 600 was too few for a whole website (D-110)
MAX_FILE_BYTES = 15_000_000


async def _status(source_id: str, status: str, expected_status: str | None = None, **extra):
    match = {"id": source_id}
    if expected_status:
        match["status"] = expected_status
    await supa.update("knowledge_sources", match, {"status": status, "updated_at": datetime.now(timezone.utc).isoformat(), **extra})


async def claim_next() -> dict | None:
    rows = await supa.select("knowledge_sources", select="*", status="eq.queued", order="created_at.asc", limit="1")
    if not rows:
        return None
    # Atomic claim: only one worker flips queued -> parsing (the update matches only while the status is still queued).
    claimed = await supa.update("knowledge_sources", {"id": rows[0]["id"], "status": "queued"}, {"status": "parsing", "error": None})
    return claimed[0] if claimed else None


async def load_and_parse(src: dict) -> Parsed:
    t = src["source_type"]
    if t == "text":
        return parsers.parse_text(src["raw_text"] or "")
    if t == "faq":
        return parsers.parse_faq(src["raw_text"] or "")
    if t == "url":   # the whole site, or the page and the pages under it (D-110)
        pages = await site.crawl(src["url"])
        try:
            return await asyncio.wait_for(asyncio.to_thread(site.extract_site, pages), timeout=60.0)
        except asyncio.TimeoutError:
            raise ParseError("Extracting website content timed out after 60 seconds.")
    if t == "file":
        try:
            data = await supa.download("knowledge", src["storage_path"])
        except FileNotFoundError as e:
            raise ParseError("The uploaded file could not be found. Upload it again.") from e
        if len(data) > MAX_FILE_BYTES:
            raise ParseError("This file is larger than 15 MB. Split it or upload a smaller copy.")
        # CPU-heavy (a large PDF takes seconds): run it in a thread so the health page and the test worker keep going.
        try:
            return await asyncio.wait_for(
                asyncio.to_thread(parsers.parse_file, src["file_kind"] or "", data, src["name"]),
                timeout=120.0,
            )
        except asyncio.TimeoutError:
            raise ParseError("Reading this file timed out after 2 minutes. Try converting it to plain text or a smaller document.")
    raise ParseError("Unknown source type.")


async def process(src: dict) -> None:
    sid = src["id"]
    try:
        await asyncio.wait_for(_process_inner(src), timeout=300.0)
    except asyncio.TimeoutError:
        log.warning("processing source %s timed out after 300s", sid)
        await _status(sid, "failed", error="Processing timed out after 5 minutes. Try splitting into smaller parts.")
    except ParseError as e:
        await _status(sid, "failed", error=str(e))
    except Exception:
        log.exception("ingestion failed for %s", sid)
        await _status(sid, "failed", error="Something went wrong while processing this source. Try again, and contact support if it keeps happening.")


async def _process_inner(src: dict) -> None:
    parsed = await load_and_parse(src)
    await index(src, parsed)


def _clean(val: str | None) -> str | None:
    return val.replace("\x00", "") if val else val


def content_hash(parsed: Parsed) -> str:
    return hashlib.sha256((parsed.markdown + json.dumps([t.rows for t in parsed.tables], default=str)).encode()).hexdigest()


async def index(src: dict, parsed: Parsed, live: bool = False) -> None:
    """Chunk, embed, store and test a parsed source. live=True is a refresh of a source agents are already using
    (D-108): the status stays "ready" until the end instead of passing through indexing/testing, so calls keep the
    source, and everything that can fail (chunking, embedding) happens before the old sections are removed."""
    sid, tenant = src["id"], src["tenant_id"]
    chash = content_hash(parsed)
    if not live:
        await _status(sid, "indexing", parsed_md=_clean(parsed.markdown[:200_000]), content_hash=chash)

    chunks = chunk_markdown(parsed.markdown, doc_title=src["name"])
    if parsed.pages and len(chunks) > MAX_CHUNKS:
        # A website: its pages are in order of importance (site.crawl), so keep the first sections, not nothing.
        log.info("website %s: kept %d of %d sections", sid, MAX_CHUNKS, len(chunks))
        chunks = chunks[:MAX_CHUNKS]
    if len(chunks) > MAX_CHUNKS:
        raise ParseError(f"This is very large ({len(chunks)} sections). Split it into smaller documents.")
    if not chunks and not parsed.tables:
        raise ParseError("Nothing readable was found in this source.")
    vecs = await embeddings.embed([c.content for c in chunks]) if chunks else []

    old_chunks = []
    old_tables = []
    if live:
        old_chunks = await supa.select("kb_chunks", select="id", source_id=f"eq.{sid}")
        old_tables = await supa.select("kb_tables", select="id", source_id=f"eq.{sid}")
    else:
        await supa.delete("kb_chunks", {"source_id": sid})
        await supa.delete("kb_tables", {"source_id": sid})

    new_chunk_ids: list[str] = []
    if chunks:
        rows = [{"tenant_id": tenant, "source_id": sid, "idx": c.idx, "section": _clean(c.section), "content": _clean(c.content),
                 "tokens": c.tokens, "embedding_local": embeddings.to_pg(v)} for c, v in zip(chunks, vecs)]
        for i in range(0, len(rows), 100):
            res = await supa.insert("kb_chunks", rows[i : i + 100])
            new_chunk_ids.extend([r["id"] for r in res if "id" in r])

    new_table_ids: list[str] = []
    if parsed.tables:
        t_rows = [{"tenant_id": tenant, "source_id": sid, "name": _clean(t.name),
                   "columns": [_clean(col) for col in t.columns],
                   "rows": [[_clean(str(cell)) for cell in row] for row in t.rows]} for t in parsed.tables]
        res_t = await supa.insert("kb_tables", t_rows)
        new_table_ids.extend([r["id"] for r in res_t if "id" in r])

    stats = {"chunks": len(chunks), "tokens": sum(c.tokens for c in chunks),
             "tables": [{"name": t.name, "rows": len(t.rows)} for t in parsed.tables]}
    if parsed.pages:
        stats["pages"] = len(parsed.pages)
    if live:
        now = datetime.now(timezone.utc).isoformat()
        stats.update(checked_at=now, refreshed_at=now)
    else:
        await _status(sid, "testing", stats=stats)
    quality = await quality_gate(tenant, sid, chunks, faq=parsed.kind == "faq", website=bool(parsed.pages))
    stats["quality"] = quality
    skipped = bool(quality.get("skipped"))
    ok = (not skipped) and (quality["tested"] == 0 or quality["hit_rate"] >= (HIT_RATE_MIN_WEBSITE if parsed.pages else HIT_RATE_MIN))
    extra = {"parsed_md": _clean(parsed.markdown[:200_000]), "content_hash": chash} if live else {}
    if skipped:
        problem = quality.get("error") or "The quality check could not run (model unavailable). Review the parsed text."
    elif not ok:
        problem = ("The website changed and some questions about the new content did not find the right passage. Review the parsed text."
                   if live else "Some questions about this content did not find the right passage. Review the parsed text and make it clearer.")
    else:
        problem = None

    if live:
        if ok:
            # New content passed quality gate: delete old chunks and tables
            for i in range(0, len(old_chunks), 50):
                batch_ids = ",".join(r["id"] for r in old_chunks[i : i + 50])
                await supa.delete("kb_chunks", {"id": f"in.({batch_ids})"})
            for i in range(0, len(old_tables), 50):
                batch_ids = ",".join(r["id"] for r in old_tables[i : i + 50])
                await supa.delete("kb_tables", {"id": f"in.({batch_ids})"})
        else:
            # Score dropped or check failed: discard newly inserted chunks/tables, keep old ones intact
            for i in range(0, len(new_chunk_ids), 50):
                batch_ids = ",".join(new_chunk_ids[i : i + 50])
                await supa.delete("kb_chunks", {"id": f"in.({batch_ids})"})
            for i in range(0, len(new_table_ids), 50):
                batch_ids = ",".join(new_table_ids[i : i + 50])
                await supa.delete("kb_tables", {"id": f"in.({batch_ids})"})

    expected = None if live else "testing"
    await _status(sid, "ready" if ok else "needs_review", expected_status=expected, stats=stats, error=problem, **extra)
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
                             source_type="eq.url", status="in.(ready,needs_review)")
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
async def _questions_from_llm(chunks: list[Chunk], tenant: str) -> dict[int, str]:
    """One short caller-style question per chunk, keyed by chunk index so questions are not zipped out of order.
    Written by the workspace's own OpenAI model when it has a working key (D-124), otherwise by the free model."""
    passages = "\n".join(f"[{i}] {c.content[:600]}" for i, c in enumerate(chunks))
    prompt = (
        "For each numbered passage, write ONE short question a phone caller might ask that the passage answers. "
        "Do not copy sentences from the passage. Mix styles: plain English, Hindi in Roman letters (Hinglish), or Devanagari. "
        f'Return JSON: {{"questions": [{{"index": 0, "question": "..."}}, ...]}} with questions for all {len(chunks)} passages.\n\n{passages}'
    )
    text = await llm_chat.chat([{"role": "user", "content": prompt}], model="gpt-4.1-mini", temperature=0.7,
                               json_mode=True, max_tokens=80 * len(chunks) + 100, key=await tenant_keys.load(tenant))
    try:
        data = json.loads(text)
        items = data.get("questions", [])
        out: dict[int, str] = {}
        for it in items:
            if isinstance(it, dict) and "index" in it and "question" in it:
                try:
                    idx = int(it["index"])
                    if 0 <= idx < len(chunks):
                        out[idx] = str(it["question"]).strip()
                except (ValueError, TypeError):
                    pass
            elif isinstance(it, str) and len(out) < len(chunks):
                out[len(out)] = it.strip()
        return out
    except Exception:
        return {}


def _page_of(text: str) -> str:
    """The page a website section belongs to: the first part of its section path, e.g. "Contact Nialabs (/contact-us)"."""
    return text.split(" > ")[0].split(": ")[0].strip().lower()


async def quality_gate(tenant: str, source_id: str, chunks: list[Chunk], faq: bool, website: bool = False) -> dict:
    """Do questions about a sample of sections find their section? For a website, finding another section of the
    same page also counts (D-110): a whole site has hundreds of sections and several sections of one page answer the
    same question; requiring the exact one failed nialabs.in at 50% while search was returning the right page."""
    if not chunks:
        return {"tested": 0, "hit_rate": 1.0, "failed": []}
    rnd = random.Random(source_id)
    sample = chunks if len(chunks) <= MAX_TEST_CHUNKS else rnd.sample(chunks, MAX_TEST_CHUNKS)
    if faq:  # the real question is the best test for an FAQ
        pairs = [(c, c.section) for c in sample if (c.section or "").strip()]
    else:
        try:
            q_map = await _questions_from_llm(sample, tenant)
            if not q_map:
                raise RuntimeError("No questions generated by LLM")
            pairs = [(sample[i], q_map[i]) for i in sorted(q_map.keys()) if q_map[i]]
        except Exception:
            log.exception("question generation failed; flagging needs_review for %s", source_id)
            return {"tested": 0, "hit_rate": 0.0, "failed": [], "skipped": True,
                    "error": "The quality check could not run (model unavailable). Review manually."}
    if not pairs:
        return {"tested": 0, "hit_rate": 1.0, "failed": []}
    vecs = await embeddings.embed_queries([q for _, q in pairs])
    hits, failed = 0, []
    for (chunk, q), vec in zip(pairs, vecs):
        found = await supa.rpc("match_chunks_local", {"p_sources": [source_id], "p_embedding": embeddings.to_pg(vec),
                                                "p_query": q, "p_k": 3, "p_tenant": tenant})
        if any(f["content"] == chunk.content or (website and _page_of(f["content"]) == _page_of(chunk.content)) for f in found):
            hits += 1
        else:
            failed.append({"question": q, "section": chunk.section, "passage": chunk.content[:160]})
    n = len(pairs)
    return {"tested": n, "hit_rate": round(hits / n, 2) if n else 1.0, "failed": failed[:5]}
