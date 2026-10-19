"""End-to-end check of the core features against the real database (needs migration 0005 applied).

    uv run python db/tests/e2e_core.py

Creates throwaway users and data, exercises: publish gate and override, handoff and callback records, settings,
capacity count, agent kill switch, caller memory, erasure, retention purge, post-call summary, custom tool loading
and a full database-queued test run. Deletes everything it made.
"""
import asyncio
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "packages/core"), str(ROOT / "apps/agent-worker"), str(ROOT)]
load_dotenv(ROOT / ".env", override=True)

from agent_worker import db, postcall, workspace  # noqa: E402
from agent_worker.custom_tools import load_custom_tools  # noqa: E402
from agent_worker.tools import CallState  # noqa: E402
from vp_core import secrets, supa  # noqa: E402

URL, ANON, SVC = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_ANON_KEY"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
T = 60
ADMIN = {"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"}
bad: list[str] = []


def check(name, ok, extra=""):
    print("PASS" if ok else "FAIL", name, extra)
    if not ok:
        bad.append(name)


def make_user(tag):
    email = f"core-{tag}-{uuid.uuid4().hex[:6]}@example.com"
    uid = httpx.post(f"{URL}/auth/v1/admin/users", headers=ADMIN, timeout=T, json={"email": email, "password": "Test-pass-123", "email_confirm": True}).json()["id"]
    tok = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, timeout=T, json={"email": email, "password": "Test-pass-123"}).json()["access_token"]
    return uid, {"apikey": ANON, "Authorization": f"Bearer {tok}", "Content-Type": "application/json", "Prefer": "return=representation"}


def rest(method, path, h, **kw):
    return httpx.request(method, f"{URL}/rest/v1/{path}", headers=h, timeout=T, **kw)


async def main():
    a_id, A = make_user("a")
    b_id, B = make_user("b")
    tenant = rest("GET", "tenant_members?select=tenant_id", A).json()[0]["tenant_id"]
    tenant_b = rest("GET", "tenant_members?select=tenant_id", B).json()[0]["tenant_id"]
    cfg = yaml.safe_load((ROOT / "agents/sunrise_clinic.yaml").read_text(encoding="utf-8"))
    try:
        # ---- agent, versions, publish gate
        ag = rest("POST", "agents", A, json={"tenant_id": tenant, "name": "Core test"}).json()[0]
        rest("POST", "rpc/create_draft", A, json={"p_agent": ag["id"], "p_config": cfg})
        r = rest("POST", "rpc/publish_version", A, json={"p_agent": ag["id"], "p_version": 1})
        check("publish works when tests are not required", r.status_code in (200, 204), r.text[:100])
        rest("POST", "rpc/create_draft", A, json={"p_agent": ag["id"], "p_config": cfg})
        rest("POST", "tenant_settings", {**A, "Prefer": "resolution=merge-duplicates,return=representation"}, json={"tenant_id": tenant, "require_tests_to_publish": True})
        r = rest("POST", "rpc/publish_version", A, json={"p_agent": ag["id"], "p_version": 2})
        check("publish is blocked until tests pass", r.status_code >= 400 and "tests_required" in r.text, r.text[:80])
        r = rest("POST", "rpc/publish_version", A, json={"p_agent": ag["id"], "p_version": 2, "p_override": True})
        check("owner can publish anyway", r.status_code in (200, 204), r.text[:100])
        audit = rest("GET", f"audit_log?tenant_id=eq.{tenant}&action=eq.agent.publish_override", A).json()
        check("override is recorded in the audit log", len(audit) == 1)
        rest("POST", "eval_runs", A, json={"tenant_id": tenant, "agent_id": ag["id"], "agent_version": 1, "status": "done", "passed": True})
        check("a client cannot insert a finished test run", rest("GET", f"eval_runs?agent_id=eq.{ag['id']}&status=eq.done", A).json() == [])

        # ---- settings and kill switch
        s = await workspace.get_settings(tenant)
        check("settings read back (gate on)", s["require_tests_to_publish"] is True and s["max_concurrent_calls"] == 5)
        check("agent is enabled by default", await workspace.agent_enabled(ag["id"]) is True)
        rest("PATCH", f"agents?id=eq.{ag['id']}", A, json={"enabled": False})
        check("kill switch turns the agent off", await workspace.agent_enabled(ag["id"]) is False)
        check("another workspace cannot flip it", rest("PATCH", f"agents?id=eq.{ag['id']}", B, json={"enabled": True}).json() == [])

        # ---- calls, handoff, callback
        call = (await supa.insert("calls", {"tenant_id": tenant, "agent_id": ag["id"], "agent_version": 2, "caller_number": "+919876543210"}))[0]
        state = CallState(tenant_id=tenant, agent_id=ag["id"], call_id=call["id"], caller_number="+919876543210")
        be = workspace.DbBackend()
        await be.record_handoff(state, "wants a person", "callback_requested")
        await be.create_callback(state, "+919876543210", "kal subah", "complaint")
        check("callback is visible to its workspace", len(rest("GET", "callbacks?select=id", A).json()) == 1)
        check("handoff is visible to its workspace", len(rest("GET", "handoffs?select=id", A).json()) == 1)
        check("another workspace sees neither", rest("GET", "callbacks?select=id", B).json() == [] and rest("GET", "handoffs?select=id", B).json() == [])
        check("capacity counts open calls", await workspace.active_calls(tenant, None) == 1 and await workspace.active_calls(tenant, call["id"]) == 0)

        # ---- memory, summary
        cid = await workspace.ensure_contact(tenant, "+919876543210")
        check("contact created once", cid == await workspace.ensure_contact(tenant, "+919876543210"))
        turns = [{"seq": 0, "speaker": "caller", "text": "Mera refund order 4821 ka abhi tak nahi aaya. Mera aadhaar 2345 6789 0124 hai."},
                 {"seq": 1, "speaker": "agent", "text": "Mujhe khed hai. Main team se callback book kar deti hoon, woh 48 ghante mein bataenge."}]
        summ = await postcall.summarize(turns, "", {}, [{"tool": "schedule_callback"}])
        check("summary is produced", bool(summ and summ.get("summary") and summ.get("outcome") in ("resolved", "handed_off", "callback", "dropped")), str(summ)[:150])
        if summ:
            await workspace.save_memory(tenant, ag["id"], cid, summ.get("rolling_summary") or summ["summary"], summ.get("facts") or {}, summ.get("open_items") or [], "hi")
        _, block = await workspace.load_memory(tenant, "+919876543210", ag["id"], {"memory_enabled": True})
        check("memory block is built for the next call", "Caller context" in block and "refund" in block.lower(), block[:120].replace("\n", " "))
        check("memory never contains the Aadhaar number", "2345" not in block and "0124" not in block)
        _, none = await workspace.load_memory(tenant, "+919876543210", ag["id"], {"memory_enabled": False})
        check("memory off means nothing is injected", none == "")
        check("another workspace cannot read the memory", rest("GET", "contact_memory?select=*", B).json() == [])

        # ---- retention purge
        old = (await supa.insert("calls", {"tenant_id": tenant, "agent_id": ag["id"], "agent_version": 2, "started_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()}))[0]
        await supa.insert("call_turns", {"call_id": old["id"], "tenant_id": tenant, "seq": 0, "speaker": "caller", "text": "old words"})
        await supa.insert("call_turns", {"call_id": call["id"], "tenant_id": tenant, "seq": 0, "speaker": "caller", "text": "fresh words"})
        await supa.update("tenant_settings", {"tenant_id": tenant}, {"retention_days": 2})
        await supa.rpc("purge_expired", {})
        left = [t["text"] for t in await supa.select("call_turns", select="text", tenant_id=f"eq.{tenant}")]
        check("old transcripts are purged, fresh ones kept", left == ["fresh words"], str(left))
        check("clients cannot call the purge", rest("POST", "rpc/purge_expired", A, json={}).status_code >= 400)

        # ---- custom tool loading
        t = rest("POST", "tools", A, json={"tenant_id": tenant, "name": "check_order", "description": "Look up an order by number when the caller gives one.",
                 "endpoint": "https://api.example.com/status", "parameters": {"type": "object", "properties": {"order_id": {"type": "string"}}, "required": ["order_id"]},
                 "requires_confirmation": True, "auth_header": "Authorization"}).json()[0]
        await supa.insert("tool_secrets", {"tool_id": t["id"], "tenant_id": tenant, "secret_enc": secrets.encrypt("Bearer xyz")})
        check("clients cannot read tool credentials", rest("GET", "tool_secrets?select=*", A).json() == [])
        loaded = await load_custom_tools(tenant, [t["id"]], CallState())
        check("worker loads the tool with its credential", len(loaded) == 1)
        params = loaded[0].info.raw_schema["parameters"] if loaded else {}
        check("confirmation tools require an explicit yes flag", "confirmed" in params.get("required", []))
        check("other workspaces cannot load it", await load_custom_tools(str(uuid.uuid4()), [t["id"]], CallState()) == [])

        # ---- erasure
        er = rest("POST", "rpc/erase_caller", B, json={"p_tenant": tenant, "p_phone": "+919876543210"})
        check("another workspace cannot erase", er.status_code >= 400)
        er = rest("POST", "rpc/erase_caller", A, json={"p_tenant": tenant, "p_phone": "+919876543210"})
        out = er.json() if er.status_code == 200 else {}
        check("erasure removes calls, contact and callbacks", out.get("calls", 0) >= 1 and out.get("contacts") == 1 and out.get("callbacks") == 1, str(out))
        check("nothing about that caller remains", not await supa.select("contacts", select="id", tenant_id=f"eq.{tenant}")
              and not await supa.select("contact_memory", select="contact_id", tenant_id=f"eq.{tenant}")
              and not await supa.select("callbacks", select="id", tenant_id=f"eq.{tenant}")
              and not await supa.select("call_turns", select="id", call_id=f"eq.{call['id']}"))
        check("erasure is audited without the full number", any(x["target"] == "3210" for x in rest("GET", f"audit_log?tenant_id=eq.{tenant}&action=eq.privacy.erase_caller", A).json()))

        # ---- a database-queued test run, end to end
        rest("PATCH", f"agents?id=eq.{ag['id']}", A, json={"enabled": True})
        run = rest("POST", "eval_runs", A, json={"tenant_id": tenant, "agent_id": ag["id"], "agent_version": 2, "status": "queued", "runs_per_scenario": 1}).json()[0]
        from evals import worker as ew
        job = await ew.claim()
        check("test run is claimed from the queue", job is not None and job["id"] == run["id"])
        if job:
            await ew.run_job(job)
            done = rest("GET", f"eval_runs?id=eq.{run['id']}&select=status,passed,pass_rate,p95_reply_ms,results,error", A).json()[0]
            check("test run finished and stored a report", done["status"] == "done" and bool(done["results"]), f"{done['status']} {done.get('error') or ''} pass_rate={done['pass_rate']} p95={done['p95_reply_ms']}")
    finally:
        for uid in (a_id, b_id):
            httpx.delete(f"{URL}/auth/v1/admin/users/{uid}", headers=ADMIN, timeout=T)
        httpx.delete(f"{URL}/rest/v1/tenants?id=eq.{tenant}", headers=ADMIN, timeout=T)
        for tid in (tenant_b,):
            httpx.delete(f"{URL}/rest/v1/tenants?id=eq.{tid}", headers=ADMIN, timeout=T)
    print("\nAll core feature checks passed." if not bad else f"\n{len(bad)} FAILED: {bad}")
    sys.exit(1 if bad else 0)


asyncio.run(main())
