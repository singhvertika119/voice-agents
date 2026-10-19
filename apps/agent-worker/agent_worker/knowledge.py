"""Knowledge at call time: small knowledge bases go straight into the prompt, large ones are searched per turn,
and spreadsheets are answered by an exact-lookup tool (docs/decision.md D-038)."""
from __future__ import annotations

import asyncio
import difflib
import logging
import re
import time
from dataclasses import dataclass, field

from livekit.agents import RunContext, function_tool
from vp_core import embeddings, supa

log = logging.getLogger("knowledge")
PROMPT_TOKEN_LIMIT = 6000   # at or below this, put everything in the prompt: no search, no extra latency
RETRIEVE_TIMEOUT_S = 2.0
TOP_K = 4


@dataclass
class KnowledgeBase:
    mode: str = "none"                     # none | prompt | search
    tenant_id: str = ""
    source_ids: list[str] = field(default_factory=list)
    prompt_text: str = ""                  # filled in "prompt" mode
    tables: list[dict] = field(default_factory=list)
    retrieval_ms: list[int] = field(default_factory=list)
    _pending: dict = field(default_factory=dict)   # query text -> in-flight/finished search task
    _last_prefetch: float = 0.0

    def prompt_addition(self) -> str:
        parts = []
        if self.mode == "prompt" and self.prompt_text:
            parts.append("Knowledge from documents:\n" + self.prompt_text)
        if self.tables:
            desc = "; ".join(f"{t['name']} (columns: {', '.join(t['columns'])})" for t in self.tables)
            parts.append("Spreadsheets you can look up with the lookup_table tool for exact values such as prices, fees "
                         f"and timings: {desc}. Never guess a number that is in a spreadsheet; look it up.")
        return ("\n\n" + "\n\n".join(parts)) if parts else ""

    def prefetch(self, partial: str) -> None:
        """Start searching on the caller's interim words, so the answer is ready by the time the turn ends.
        This hides the embedding + search time behind end-of-turn detection (architecture: speculative retrieval)."""
        text = partial.strip()
        now = time.perf_counter()
        if self.mode != "search" or len(text) < 12 or text in self._pending or now - self._last_prefetch < 0.5:
            return
        self._last_prefetch = now
        if len(self._pending) > 6:
            self._pending.pop(next(iter(self._pending)))
        self._pending[text] = asyncio.ensure_future(self._search(text))

    async def _search(self, query: str) -> str | None:
        t0 = time.perf_counter()
        try:
            vec = await embeddings.embed_query(query)
            rows = await supa.rpc("match_chunks", {"p_sources": self.source_ids, "p_embedding": embeddings.to_pg(vec),
                                                   "p_query": query, "p_k": TOP_K, "p_tenant": self.tenant_id},
                                  timeout=RETRIEVE_TIMEOUT_S * 3)
        except Exception as e:
            log.warning("retrieval failed (%s); answering without documents", e)
            return None
        self.retrieval_ms.append(int((time.perf_counter() - t0) * 1000))
        return "\n\n".join(r["content"] for r in rows) if rows else ""

    async def retrieve(self, query: str) -> str | None:
        """Top passages for the final caller question, or None. Never raises, and never holds the reply for
        longer than RETRIEVE_TIMEOUT_S: a slow search must not stop the call."""
        text = query.strip()
        if self.mode != "search" or len(text) < 3:
            return None
        # Reuse a speculative search whose words are (nearly) the final words.
        task = self._pending.get(text) or next(
            (t for q, t in self._pending.items() if difflib.SequenceMatcher(None, q, text).ratio() > 0.85), None)
        if task is None:
            task = asyncio.ensure_future(self._search(text))
        try:
            return await asyncio.wait_for(asyncio.shield(task), RETRIEVE_TIMEOUT_S)
        except asyncio.TimeoutError:
            log.warning("retrieval too slow; answering without documents")
            return None


async def load_knowledge(source_ids: list[str], tenant_id: str) -> KnowledgeBase:
    """Only sources that belong to the agent's own workspace and are 'ready' are ever used."""
    if not source_ids:
        return KnowledgeBase()
    ids = ",".join(source_ids)
    try:
        ready = await supa.select("knowledge_sources", select="id,name,stats", id=f"in.({ids})",
                                  tenant_id=f"eq.{tenant_id}", status="eq.ready")
        if not ready:
            return KnowledgeBase()
        ok_ids = [r["id"] for r in ready]
        tables = await supa.select("kb_tables", select="name,columns,rows", source_id=f"in.({','.join(ok_ids)})",
                                   tenant_id=f"eq.{tenant_id}")
        total = sum(int((r.get("stats") or {}).get("tokens", 0)) for r in ready)
        kb = KnowledgeBase(tenant_id=tenant_id, source_ids=ok_ids, tables=tables)
        if total == 0:
            kb.mode = "none"
        elif total <= PROMPT_TOKEN_LIMIT:
            chunks = await supa.select("kb_chunks", select="content,source_id,idx", source_id=f"in.({','.join(ok_ids)})",
                                       tenant_id=f"eq.{tenant_id}", order="source_id.asc,idx.asc")
            kb.mode, kb.prompt_text = "prompt", "\n\n".join(c["content"] for c in chunks)
        else:
            kb.mode = "search"
        log.info("knowledge: %s mode, %d tokens, %d sources, %d tables", kb.mode, total, len(ok_ids), len(tables))
        return kb
    except Exception as e:
        log.warning("could not load knowledge (%s); continuing without it", e)
        return KnowledgeBase()


# ------------------------------------------------------------------ exact lookup over spreadsheets
def _words(s: str) -> set[str]:
    return set(re.findall(r"[\wऀ-ॿ]+", str(s).lower()))


def search_rows(tables: list[dict], table: str, search: str, limit: int = 3) -> list[dict]:
    """Rank rows by shared words, with a fuzzy fallback so 'x ray' still finds 'X-ray'."""
    pool = [t for t in tables if not table or table.lower() in t["name"].lower()] or tables
    q = _words(search)
    scored = []
    for t in pool:
        for row in t["rows"]:
            text = " ".join(str(v) for v in row.values())
            words = _words(text)
            overlap = len(q & words)
            fuzzy = difflib.SequenceMatcher(None, search.lower(), text.lower()).ratio() if not overlap else 0
            score = overlap + (fuzzy if fuzzy > 0.45 else 0)
            if score > 0:
                scored.append((score, t["name"], row))
    scored.sort(key=lambda x: -x[0])
    return [{"table": n, **r} for _, n, r in scored[:limit]]


def make_lookup_tool(kb: KnowledgeBase):
    @function_tool
    async def lookup_table(context: RunContext, table: str, search: str) -> str:
        """Look up exact values (prices, fees, timings, availability) in a spreadsheet the business uploaded.

        Args:
            table: Name of the spreadsheet to search, or empty to search all of them.
            search: The words that identify the row, for example the service or item name.
        """
        rows = search_rows(kb.tables, table, search)
        if not rows:
            return "No matching row was found. Say you do not have that information and offer to connect a person."
        return "\n".join(", ".join(f"{k}: {v}" for k, v in r.items() if k != "table" and v != "") for r in rows)

    return lookup_table
