"""Proves tenant isolation (plan M2.1 "done when"): two tenants, neither can read the other's data.

Run AFTER applying db/migrations to the new Supabase project and putting its keys in .env:
    uv run python db/tests/test_rls.py
Creates two throwaway users, checks the rules below, then deletes them.
"""
import os
import sys
import uuid
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
URL, ANON, SERVICE = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_ANON_KEY"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
ADMIN = {"apikey": SERVICE, "Authorization": f"Bearer {SERVICE}", "Content-Type": "application/json"}
failures = []
T = 30  # Supabase free tier cold-starts can take several seconds


def check(name: str, ok: bool):
    print(("PASS" if ok else "FAIL"), name)
    if not ok:
        failures.append(name)


def make_user(tag: str):
    email, pw = f"rls-{tag}-{uuid.uuid4().hex[:6]}@example.com", "Test-pass-123"
    r = httpx.post(f"{URL}/auth/v1/admin/users", headers=ADMIN, json={"email": email, "password": pw, "email_confirm": True}, timeout=T)
    r.raise_for_status()
    uid = r.json()["id"]
    t = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, json={"email": email, "password": pw}, timeout=T)
    t.raise_for_status()
    return uid, {"apikey": ANON, "Authorization": f"Bearer {t.json()['access_token']}", "Content-Type": "application/json",
                 "Prefer": "return=representation"}


def rest(method, path, headers, **kw):
    return httpx.request(method, f"{URL}/rest/v1/{path}", headers=headers, timeout=T, **kw)


a_id, A = make_user("a")
b_id, B = make_user("b")
try:
    tenant_a = rest("GET", "tenant_members?select=tenant_id", A).json()[0]["tenant_id"]
    check("signup created a workspace for user A", bool(tenant_a))

    agent = rest("POST", "agents", A, json={"tenant_id": tenant_a, "name": "A agent"}).json()[0]
    check("A can create an agent", "id" in agent)
    v = rest("POST", "rpc/create_draft", A, json={"p_agent": agent["id"], "p_config": {"x": 1}})
    check("A can create a draft version", v.status_code == 200 and v.json() == 1)
    pub = rest("POST", "rpc/publish_version", A, json={"p_agent": agent["id"], "p_version": 1})
    check("A can publish", pub.status_code in (200, 204))

    check("B cannot read A's agents", rest("GET", f"agents?id=eq.{agent['id']}", B).json() == [])
    check("B cannot read A's versions", rest("GET", f"agent_versions?agent_id=eq.{agent['id']}", B).json() == [])
    check("B cannot read A's membership", rest("GET", f"tenant_members?tenant_id=eq.{tenant_a}", B).json() == [])
    check("B cannot read A's audit log", rest("GET", f"audit_log?tenant_id=eq.{tenant_a}", B).json() == [])
    forged = rest("POST", "agents", B, json={"tenant_id": tenant_a, "name": "forged"})
    check("B cannot insert into A's tenant", forged.status_code in (401, 403))
    check("B cannot publish A's agent", rest("POST", "rpc/publish_version", B, json={"p_agent": agent["id"], "p_version": 1}).status_code >= 400)
    check("B cannot edit A's agent", rest("PATCH", f"agents?id=eq.{agent['id']}", B, json={"name": "hacked"}).json() == [])
    check("A can read the audit log of own publish", len(rest("GET", f"audit_log?tenant_id=eq.{tenant_a}", A).json()) >= 1)
    check("A cannot delete audit rows", rest("DELETE", f"audit_log?tenant_id=eq.{tenant_a}", A).json() == [])
finally:
    for uid in (a_id, b_id):
        httpx.delete(f"{URL}/auth/v1/admin/users/{uid}", headers=ADMIN, timeout=T)

print("\nAll isolation checks passed." if not failures else f"\n{len(failures)} check(s) FAILED: {failures}")
sys.exit(1 if failures else 0)
