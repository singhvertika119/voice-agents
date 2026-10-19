"""End-to-end check of the knowledge pipeline against the real database (needs migration 0004 applied).

    uv run python db/tests/e2e_knowledge.py

Creates a throwaway user, adds a FAQ, a text policy and a price sheet, runs the ingestion pipeline on each,
asks Hinglish questions through hybrid search AS THAT USER (so row-level security applies), exercises the
agent worker's knowledge loader, proves a second user sees nothing, then deletes everything it made.
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "packages/core"), str(ROOT / "apps/ingestion-worker"), str(ROOT / "apps/agent-worker")]
load_dotenv(ROOT / ".env", override=True)

from ingestion.pipeline import process  # noqa: E402
from vp_core import embeddings, supa  # noqa: E402

URL, ANON, SVC = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_ANON_KEY"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
T = 60
ADMIN = {"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"}
bad: list[str] = []


def check(name, ok, extra=""):
    print("PASS" if ok else "FAIL", name, extra)
    if not ok:
        bad.append(name)


def make_user(tag):
    email = f"kb-{tag}-{uuid.uuid4().hex[:6]}@example.com"
    uid = httpx.post(f"{URL}/auth/v1/admin/users", headers=ADMIN, timeout=T,
                     json={"email": email, "password": "Test-pass-123", "email_confirm": True}).json()["id"]
    tok = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, timeout=T,
                     json={"email": email, "password": "Test-pass-123"}).json()["access_token"]
    return uid, {"apikey": ANON, "Authorization": f"Bearer {tok}", "Content-Type": "application/json", "Prefer": "return=representation"}


def rest(method, path, h, **kw):
    return httpx.request(method, f"{URL}/rest/v1/{path}", headers=h, timeout=T, **kw)


FAQ = """Q: Clinic kab khulta hai?
A: Clinic Monday se Saturday subah 9 baje se shaam 7 baje tak khulta hai. Sunday ko band rehta hai.

Q: Consultation ki fees kitni hai?
A: Consultation ki fees 600 rupaye hai aur 7 din ke andar follow-up 300 rupaye.

Q: Appointment cancel kaise karein?
A: Appointment se 4 ghante pehle tak cancel karna free hai. Phone par ya front desk par bata dijiye.

Q: Report kab milti hai?
A: Reports 24 ghante mein ready ho jaati hain. WhatsApp par link bhi mil sakta hai."""

POLICY = """# Refund policy

## Timelines
Refunds are processed within 5 to 7 working days after the request is approved. The amount returns to the original payment method.

## Eligibility
Only unused items in original packaging qualify for a refund. Customised items cannot be refunded.

# Delivery

## Charges
Delivery is free above 999 rupees. Below that, a flat charge of 49 rupees applies across India.
"""

PRICES = "Service,Price\nECG,400\nX-ray,700\nConsultation,600\nBlood test,350\n"


async def main():
    a_id, A = make_user("a")
    b_id, B = make_user("b")
    tenant = rest("GET", "tenant_members?select=tenant_id", A).json()[0]["tenant_id"]
    ids = {}
    try:
        for name, kind, body in [("faq", "faq", FAQ), ("policy", "text", POLICY), ("prices", "file", PRICES)]:
            row = {"tenant_id": tenant, "name": name, "source_type": kind, "status": "parsing"}
            if kind == "file":
                row.update(file_kind="csv", storage_path=f"{tenant}/test-{uuid.uuid4().hex[:6]}/prices.csv")
                async with supa.client(60) as c:
                    r = await c.post(f"/storage/v1/object/knowledge/{row['storage_path']}", content=body.encode(),
                                     headers={"Content-Type": "text/csv"})
                    check("upload to storage", r.status_code < 300, r.text[:80])
            else:
                row["raw_text"] = body
            src = rest("POST", "knowledge_sources", A, json=row).json()[0]
            ids[name] = src["id"]
            await process(src)
            got = rest("GET", f"knowledge_sources?id=eq.{src['id']}&select=status,error,stats", A).json()[0]
            check(f"{name} ingested", got["status"] == "ready", f"{got['status']} {got['error'] or ''} {got['stats'].get('quality', '')}")

        chunks = rest("GET", f"kb_chunks?tenant_id=eq.{tenant}&select=id", A).json()
        check("chunks are visible to their owner", len(chunks) >= 6, str(len(chunks)))
        tables = rest("GET", f"kb_tables?source_id=eq.{ids['prices']}&select=rows", A).json()
        check("price sheet stored as a lookup table, not chunks", tables and len(tables[0]["rows"]) == 4)

        async def ask(q, sources):
            vec = await embeddings.embed_query(q)
            r = rest("POST", "rpc/match_chunks", A, json={"p_sources": sources, "p_embedding": embeddings.to_pg(vec), "p_query": q, "p_k": 3})
            return r.json()

        cases = [
            ("consultation ki fees kitni hai", [ids["faq"]], "600"),
            ("Sunday ko clinic open hai?", [ids["faq"]], "Sunday"),
            ("how long does a refund take", [ids["policy"]], "5 to 7"),
            ("delivery charge kitna lagta hai", [ids["policy"]], "49"),
            ("appointment cancel karna hai paise lagenge", [ids["faq"]], "free"),
        ]
        for q, src, expect in cases:
            hits = await ask(q, src)
            check(f"search: {q!r}", bool(hits) and expect in hits[0]["content"], hits[0]["content"][:70] if hits else "no hits")

        check("other workspace cannot search my knowledge", (await ask_as(B, "consultation fees", list(ids.values()))) == [])
        check("other workspace cannot read my sources", rest("GET", "knowledge_sources?select=id", B).json() == [])

        from agent_worker import knowledge as kn
        kb = await kn.load_knowledge(list(ids.values()), tenant)
        check("worker loads small knowledge into the prompt", kb.mode == "prompt" and "600" in kb.prompt_text, kb.mode)
        check("worker sees the price table", len(kb.tables) == 1)
        check("worker lookup finds ECG", kn.search_rows(kb.tables, "", "ECG ka rate")[0]["Price"] == "400")
        other = await kn.load_knowledge(list(ids.values()), str(uuid.uuid4()))
        check("worker refuses sources from another workspace", other.mode == "none" and not other.tables)
        kb.mode = "search"  # force the search path used for big knowledge bases
        got = await kb.retrieve("consultation ki fees kitni hai")
        check("worker search path returns passages", bool(got) and "600" in got, str(kb.retrieval_ms))
    finally:
        for uid in (a_id, b_id):
            httpx.delete(f"{URL}/auth/v1/admin/users/{uid}", headers=ADMIN, timeout=T)
        httpx.delete(f"{URL}/rest/v1/tenants?id=eq.{tenant}", headers=ADMIN, timeout=T)
        async with supa.client(60) as c:
            await c.post("/storage/v1/object/list/knowledge", json={"prefix": tenant})
            await c.request("DELETE", "/storage/v1/object/knowledge", json={"prefixes": [f"{tenant}"]})
    print("\nAll knowledge checks passed." if not bad else f"\n{len(bad)} FAILED: {bad}")
    sys.exit(1 if bad else 0)


async def ask_as(h, q, sources):
    vec = await embeddings.embed_query(q)
    return httpx.post(f"{URL}/rest/v1/rpc/match_chunks", headers=h, timeout=T,
                      json={"p_sources": sources, "p_embedding": embeddings.to_pg(vec), "p_query": q, "p_k": 3}).json()


asyncio.run(main())
