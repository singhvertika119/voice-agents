"""Knowledge at call time: small knowledge bases go straight into the prompt, large ones are searched per turn,
and spreadsheets are answered by an exact-lookup tool (docs/decision.md D-038)."""
from __future__ import annotations

import asyncio
import difflib
import logging
import os
import re
import time
from dataclasses import dataclass, field

from livekit.agents import RunContext, function_tool
from vp_core import embeddings, supa

log = logging.getLogger("knowledge")
# At or below this, put everything in the prompt: no search, no extra latency. But every reply then resends the whole
# text (about 4,700 tokens per request for the Front desk agent), which is what exhausts free-tier per-minute limits.
PROMPT_TOKEN_LIMIT = int(os.getenv("KNOWLEDGE_PROMPT_TOKENS", "6000"))
RETRIEVE_TIMEOUT_S = 2.0
TOP_K = 4
# Key facts (D-111): in search mode the business's contact/about/location sections and the website's shared menu and
# footer are put in the prompt anyway, so the most asked questions (address, phone, hours, what do you sell) never
# depend on a search. Kept small so every reply does not resend much.
CORE_TOKENS = int(os.getenv("KNOWLEDGE_CORE_TOKENS", "1200"))
# A page whose address has a path segment that is (or starts with "<word>-") one of these words: "/contact-us",
# "/about", "/locations/jaipur"; not "/glossary/contactless-biometrics".
CORE_SECTION = re.compile(r"\((?:/[^)/]*)*/(?:contact|about|locations?|offices?|timings?|hours|branch(?:es)?|reach)"
                          r"(?:[-/][^)]*)?\)|^On every page of the website", re.I)

# Small talk needs no documents: searching for "okay" or "thank you" only delays the reply (D-111).
_SMALL_TALK = set("""ok okay okk haan han ha haa hmm hmmm ji ha-ji theek thik thikhai hai acha accha achha sahi
yes no nahi nope sure fine great cool right hello hi hey helo bye goodbye alvida thanks thank you thankyou shukriya
dhanyavaad dhanyawad please sorry wait ruko main mein mai bas namaste got it understood samajh gaya gayi
ठीक है हाँ हां हा जी अच्छा सही नहीं ना हेलो हलो बाय धन्यवाद शुक्रिया नमस्ते ओके हम्म बस समझ गया गई""".split())


def is_small_talk(text: str) -> bool:
    """A short acknowledgement or greeting, such as "okay", "haan ji", "thank you", "ठीक है"."""
    words = re.findall(r"[\wऀ-ॣ०-ॿ]+", text.lower())   # Devanagari letters, not the "।" stop
    return 0 < len(words) <= 4 and all(w in _SMALL_TALK for w in words)


@dataclass
class KnowledgeBase:
    mode: str = "none"                     # none | prompt | search
    tenant_id: str = ""
    source_ids: list[str] = field(default_factory=list)
    prompt_text: str = ""                  # filled in "prompt" mode
    core_text: str = ""                    # key facts, always in the prompt in "search" mode (D-111)
    tables: list[dict] = field(default_factory=list)
    retrieval_ms: list[int] = field(default_factory=list)
    _pending: dict = field(default_factory=dict)   # query text -> in-flight/finished search task
    _last_prefetch: float = 0.0

    def prompt_addition(self) -> str:
        parts = []
        if self.mode == "prompt" and self.prompt_text:
            parts.append("Knowledge from documents:\n" + self.prompt_text)
        if self.mode == "search" and self.core_text:
            parts.append("Key facts from the business's documents (contact details and overview; more passages are "
                         "added for each question):\n" + self.core_text)
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
        if (self.mode != "search" or len(text) < 12 or text in self._pending or now - self._last_prefetch < 0.5
                or is_small_talk(text)):
            return
        self._last_prefetch = now
        if len(self._pending) > 6:
            self._pending.pop(next(iter(self._pending)))
        self._pending[text] = asyncio.ensure_future(self._search(text))

    async def _search(self, query: str) -> str | None:
        t0 = time.perf_counter()
        try:
            vec = await embeddings.embed_query(query)
        except Exception as e:
            # Embeddings come from OpenAI; when that account is out of credit, keyword search still finds passages.
            log.warning("embedding failed (%s); using keyword search only", str(e)[:120])
            return await self._keyword_search(query, t0)
        try:
            rows = await supa.rpc("match_chunks", {"p_sources": self.source_ids, "p_embedding": embeddings.to_pg(vec),
                                                   "p_query": query, "p_k": TOP_K, "p_tenant": self.tenant_id},
                                  timeout=RETRIEVE_TIMEOUT_S * 3)
        except Exception as e:
            log.warning("retrieval failed (%s); answering without documents", e)
            return None
        self.retrieval_ms.append(int((time.perf_counter() - t0) * 1000))
        return "\n\n".join(r["content"] for r in rows) if rows else ""

    async def _keyword_search(self, query: str, t0: float) -> str | None:
        terms = keyword_terms(query)
        if not terms:
            return ""
        try:
            rows = await supa.select("kb_chunks", select="content", source_id=f"in.({','.join(self.source_ids)})",
                                     tenant_id=f"eq.{self.tenant_id}", fts=f"fts(simple).{' | '.join(terms)}", limit=str(TOP_K))
        except Exception as e:
            log.warning("keyword search failed (%s); answering without documents", e)
            return None
        self.retrieval_ms.append(int((time.perf_counter() - t0) * 1000))
        return "\n\n".join(r["content"] for r in rows) if rows else ""

    async def retrieve(self, query: str) -> str | None:
        """Top passages for the final caller question, or None. Never raises, and never holds the reply for
        longer than RETRIEVE_TIMEOUT_S: a slow search must not stop the call."""
        text = query.strip()
        if self.mode != "search" or len(text) < 3 or is_small_talk(text):
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


def keyword_terms(query: str) -> list[str]:
    """Words worth matching, joined with OR: a spoken question rarely contains every word of the passage it needs."""
    words = re.findall(r"[0-9A-Za-z\u0900-\u097F]{3,}", query.lower())
    return list(dict.fromkeys(words))[:12]


async def _core_facts(source_ids: list[str], tenant_id: str) -> str:
    """Contact/about/location sections and the website's shared section, up to CORE_TOKENS, contact first (D-111)."""
    try:
        rows = await supa.select(
            "kb_chunks", select="section,content,tokens,idx", source_id=f"in.({','.join(source_ids)})",
            tenant_id=f"eq.{tenant_id}", order="idx.asc",
            **{"or": "(section.ilike.*contact*,section.ilike.*about*,section.ilike.*location*,section.ilike.*office*,"
                     "section.ilike.*timing*,section.ilike.*hours*,section.ilike.*branch*,section.ilike.*reach*,"
                     "section.ilike.On every page*)"})
    except Exception as e:
        log.info("key facts not loaded: %s", e)
        return ""

    def rank(r: dict) -> tuple:
        s = (r["section"] or "").lower()
        # Contact details, then the site-wide menu and footer (it lists every product and service, which answers
        # "do you offer X?"), then about/location pages.
        return (0 if "contact" in s else 1 if s.startswith("on every page") else 2, r["idx"])

    out, used, seen = [], 0, set()
    for r in sorted((r for r in rows if CORE_SECTION.search(r["section"] or "")), key=rank):
        n = int(r["tokens"] or 0)
        if r["content"] in seen or used + n > CORE_TOKENS:
            continue
        seen.add(r["content"])
        out.append(r["content"])
        used += n
    return "\n".join(out)


async def _warm() -> None:
    try:
        await embeddings.embed_query("namaste")
    except Exception:
        pass


async def load_knowledge(source_ids: list[str], tenant_id: str, mode: str = "auto") -> KnowledgeBase:
    """Only sources that belong to the agent's own workspace and are 'ready' are ever used.
    mode: "auto" (in the prompt if small, searched if large), or "prompt" / "search" to force one for an agent."""
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
        elif mode == "prompt" or (mode != "search" and total <= PROMPT_TOKEN_LIMIT):
            chunks = await supa.select("kb_chunks", select="content,source_id,idx", source_id=f"in.({','.join(ok_ids)})",
                                       tenant_id=f"eq.{tenant_id}", order="source_id.asc,idx.asc")
            kb.mode, kb.prompt_text = "prompt", "\n\n".join(c["content"] for c in chunks)
        else:
            kb.mode = "search"
            kb.core_text = await _core_facts(ok_ids, tenant_id)
            # Open the connection to the embedding service while the greeting plays, so the caller's first question
            # does not pay for it (about 1 s, D-110). The connection is then reused for the rest of the call.
            asyncio.ensure_future(_warm())
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
