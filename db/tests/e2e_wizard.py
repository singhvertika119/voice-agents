"""Drives the setup wizard end to end over HTTP, the way a browser without JavaScript would (forms post to server
actions), as a brand-new user, then checks what landed in the database.

    (dashboard running on http://localhost:3000)   uv run python db/tests/e2e_wizard.py

Creates a throwaway user, walks business type > details > knowledge > voice > go live, then deletes everything.
"""
import base64
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.parse import unquote, urljoin, urlparse, parse_qs

import httpx
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
URL, ANON, SVC = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_ANON_KEY"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
APP = os.getenv("APP_URL", "http://localhost:3000")
ADMIN = {"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"}
T = 60
bad: list[str] = []


def check(name, ok, extra=""):
    print("PASS" if ok else "FAIL", name, extra)
    if not ok:
        bad.append(name)


def session_cookies(email, pw) -> dict[str, str]:
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, json={"email": email, "password": pw}, timeout=T)
    r.raise_for_status()
    value = "base64-" + base64.urlsafe_b64encode(json.dumps(r.json()).encode()).decode().rstrip("=")
    ref = urlparse(URL).hostname.split(".")[0]
    name, size = f"sb-{ref}-auth-token", 3000
    if len(value) <= size:
        return {name: value}
    return {f"{name}.{i}": value[i * size:(i + 1) * size] for i in range((len(value) + size - 1) // size)}


def hidden_fields(html: str, form_hint: str | None = None) -> list[tuple[str, str]]:
    """Hidden inputs of the form that contains form_hint (or the first form): they carry the server action id."""
    forms = re.findall(r"<form\b.*?</form>", html, re.S)
    form = next((f for f in forms if form_hint is None or form_hint in f), forms[0])
    out = []
    for m in re.finditer(r"<input\b[^>]*type=\"hidden\"[^>]*>", form):
        tag = m.group(0)
        n = re.search(r'name="([^"]*)"', tag)
        v = re.search(r'value="([^"]*)"', tag)
        if n:
            out.append((n.group(1), (v.group(1) if v else "").replace("&quot;", '"').replace("&amp;", "&")))
    return out


def step(client: httpx.Client, path: str, fields: dict, form_hint: str | None = None):
    page = client.get(APP + path)
    assert page.status_code == 200, f"GET {path} -> {page.status_code}"
    data = hidden_fields(page.text, form_hint)
    multi = [(k, str(v)) for k, vs in fields.items() for v in (vs if isinstance(vs, list) else [vs])]
    r = client.post(APP + path, files=[(k, (None, v)) for k, v in data + multi], follow_redirects=False)
    return page, r


def dest(r: httpx.Response) -> str:
    return r.headers.get("location", "") if r.status_code in (301, 302, 303, 307, 308) else f"<{r.status_code}>"


def main():
    email, pw = f"wiz-{uuid.uuid4().hex[:6]}@example.com", "Test-pass-123"
    uid = httpx.post(f"{URL}/auth/v1/admin/users", headers=ADMIN, timeout=T, json={"email": email, "password": pw, "email_confirm": True}).json()["id"]
    tenant = httpx.get(f"{URL}/rest/v1/tenant_members?select=tenant_id&user_id=eq.{uid}", headers=ADMIN, timeout=T).json()[0]["tenant_id"]
    client = httpx.Client(cookies=session_cookies(email, pw), timeout=T)
    agent = None
    try:
        r = client.get(APP + "/onboarding/business-type")
        check("wizard page loads for a signed-in user", r.status_code == 200 and "What kind of business" in r.text, str(r.status_code))
        check("all six templates are offered", all(x in r.text for x in ("Clinic or diagnostic lab", "Coaching institute", "Online store", "Real estate", "Service business", "Start from scratch")))
        anon = httpx.get(APP + "/onboarding/business-type", follow_redirects=False, timeout=T)
        check("a signed-out visitor is sent to login", anon.status_code in (302, 303, 307) and "/login" in anon.headers.get("location", ""), dest(anon))

        _, r = step(client, "/onboarding/business-type", {"type": "clinic"})
        loc = dest(r)
        check("step 1 creates an agent and moves to step 2", "/onboarding/details?agent=" in loc, loc)
        agent = parse_qs(urlparse(loc).query).get("agent", [None])[0]

        # bad input is refused with a plain message and nothing is half-saved
        _, r = step(client, f"/onboarding/details?agent={agent}", {"name": "Sunrise [Clinic]", "languages": ["hinglish"]})
        check("square brackets in answers are refused", "error=" in dest(r) and "brackets" in unquote(dest(r)), unquote(dest(r))[:100])
        _, r = step(client, f"/onboarding/details?agent={agent}", {"name": "Sunrise Clinic"})
        check("choosing no language is refused", "language" in unquote(dest(r)).lower(), unquote(dest(r))[:100])
        _, r = step(client, f"/onboarding/details?agent={agent}", {"name": "Sunrise Clinic", "languages": ["hinglish", "english"], "handoff_phone": "12345"})
        check("an invalid team number is refused", "10-digit" in unquote(dest(r)), unquote(dest(r))[:100])

        _, r = step(client, f"/onboarding/details?agent={agent}", {
            "name": "Sunrise Clinic", "address": "Sector 62, Noida", "hours": "Mon to Sat, 9 am to 7 pm. Sunday closed.",
            "reasons": "doctor timings, fees, reports", "languages": ["hinglish", "english"], "handoff_phone": "98765 43210"})
        check("step 2 saves and moves to knowledge", "/onboarding/knowledge?agent=" in dest(r), dest(r))

        _, r = step(client, f"/onboarding/knowledge?agent={agent}", {}, form_hint="Skip for now")
        check("step 3 can be skipped", "/onboarding/voice?agent=" in dest(r), dest(r))

        _, r = step(client, f"/onboarding/voice?agent={agent}", {"voice": "nope"})
        check("an unknown voice is refused", "error=" in dest(r))
        _, r = step(client, f"/onboarding/voice?agent={agent}", {"voice": "priya"})
        check("step 4 saves the voice", "/onboarding/test-call?agent=" in dest(r), dest(r))

        page = client.get(APP + f"/onboarding/test-call?agent={agent}")
        check("the test-call step shows the call panel and suggestions", "Try these on the call" in page.text and "Call from browser" in page.text)

        _, r = step(client, f"/onboarding/test-call?agent={agent}", {}, form_hint="Publish and go live")
        check("go live publishes and lands on the agent page", f"/agents/{agent}" in dest(r) and "live=1" in dest(r), dest(r))

        ag = httpx.get(f"{URL}/rest/v1/agents?id=eq.{agent}&select=name,published_version", headers=ADMIN, timeout=T).json()[0]
        ver = httpx.get(f"{URL}/rest/v1/agent_versions?agent_id=eq.{agent}&select=version,status,config&order=version.desc", headers=ADMIN, timeout=T).json()[0]
        cfg = ver["config"]
        check("the agent is named after the business and is live", ag["name"] == "Sunrise Clinic" and ag["published_version"] == ver["version"] and ver["status"] == "published", str(ag))
        check("greeting uses the name and says AI and recording", "Sunrise Clinic" in cfg["greeting"] and "AI assistant" in cfg["greeting"] and "record" in cfg["greeting"], cfg["greeting"][:90])
        check("instructions carry the clinic safety rules", "Never give medical advice" in cfg["instructions"] and "112" in cfg["instructions"])
        check("notes hold exactly what was typed", cfg["knowledge"] == "Business name: Sunrise Clinic\nAddress: Sector 62, Noida\nTimings: Mon to Sat, 9 am to 7 pm. Sunday closed.\nPeople usually call about: doctor timings, fees, reports", cfg["knowledge"][:120])
        check("the chosen voice is saved", cfg["voice"]["tts_primary"]["speaker"] == "priya")
        check("no [placeholder] text anywhere", not re.search(r"\[[^\]\n]{2,60}\]", cfg["greeting"] + cfg["instructions"] + cfg["knowledge"]))
        s = httpx.get(f"{URL}/rest/v1/tenant_settings?tenant_id=eq.{tenant}&select=handoff_phone", headers=ADMIN, timeout=T).json()
        check("the team number was stored in settings", bool(s) and s[0]["handoff_phone"] == "+919876543210", str(s))
        page = client.get(APP + f"/agents/{agent}?tab=versions&live=1")
        check("the agent page shows the live banner", "Your agent is live" in page.text)
    finally:
        client.close()
        httpx.delete(f"{URL}/auth/v1/admin/users/{uid}", headers=ADMIN, timeout=T)
        httpx.delete(f"{URL}/rest/v1/tenants?id=eq.{tenant}", headers=ADMIN, timeout=T)
    print("\nAll wizard checks passed." if not bad else f"\n{len(bad)} FAILED: {bad}")
    sys.exit(1 if bad else 0)


main()
