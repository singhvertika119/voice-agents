"""Opens every dashboard screen in a real (headless) Chrome at phone and tablet sizes, signed in as a throwaway user
with sample data, and reports sideways overflow, tiny tap targets and text that is cut off. Saves screenshots.

    (dashboard running on http://localhost:3000)   uv run python db/tests/mobile_check.py [base_url]

Screenshots go to logs/mobile/. Everything it creates (user, workspace, sample data) is deleted at the end.
"""
import asyncio
import base64
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from urllib.parse import urlparse

import aiohttp
import httpx
import yaml
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
URL, ANON, SVC = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_ANON_KEY"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
APP = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:3000"
ADMIN = {"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json", "Prefer": "return=representation"}
CHROME = next(p for p in (r"C:\Program Files\Google\Chrome\Application\chrome.exe", r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe") if Path(p).exists())
OUT = ROOT / "logs" / "mobile"
VIEWPORTS = {"phone-390": (390, 844, True), "tablet-768": (768, 1024, True)}


def rest(method, path, **kw):
    r = httpx.request(method, f"{URL}/rest/v1/{path}", headers=ADMIN, timeout=60, **kw)
    r.raise_for_status()
    return r.json() if r.text else None


def session_cookies(email, pw):
    r = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, json={"email": email, "password": pw}, timeout=60)
    r.raise_for_status()
    value = "base64-" + base64.urlsafe_b64encode(json.dumps(r.json()).encode()).decode().rstrip("=")
    name, size = f"sb-{urlparse(URL).hostname.split('.')[0]}-auth-token", 3000
    return [{"name": name if len(value) <= size else f"{name}.{i}", "value": value if len(value) <= size else value[i * size:(i + 1) * size]}
            for i in range(1 if len(value) <= size else (len(value) + size - 1) // size)]


def seed(uid):
    tenant = rest("GET", f"tenant_members?select=tenant_id&user_id=eq.{uid}")[0]["tenant_id"]
    cfg = yaml.safe_load((ROOT / "agents/sunrise_clinic.yaml").read_text(encoding="utf-8"))
    for k in ("id", "name"):
        cfg.pop(k, None)
    agent = rest("POST", "agents", json={"tenant_id": tenant, "name": "Sunrise Clinic front desk", "published_version": 1})[0]
    rest("POST", "agent_versions", json={"agent_id": agent["id"], "tenant_id": tenant, "version": 1, "status": "published", "config": cfg, "note": "seed"})
    rest("POST", "agent_versions", json={"agent_id": agent["id"], "tenant_id": tenant, "version": 2, "status": "draft", "config": cfg, "note": "draft"})
    call = rest("POST", "calls", json={"tenant_id": tenant, "agent_id": agent["id"], "agent_version": 1, "caller_number": "+919876543210", "duration_s": 83, "avg_reply_ms": 2100,
                                       "outcome": "callback", "cost_usd": 0.01, "summary": "The caller asked for a person about a refund and a callback was booked for tomorrow morning.",
                                       "structured": {"intent": "Refund status", "commitments": ["Team to call back"], "open_items": ["Refund for order 4821"]},
                                       "tool_calls": [{"tool": "request_human", "ok": True, "ms": 12}, {"tool": "schedule_callback", "ok": True, "ms": 180}]})[0]
    rest("POST", "call_turns", json=[{"call_id": call["id"], "tenant_id": tenant, "seq": i, "speaker": "agent" if i % 2 == 0 else "caller", "at_ms": i * 6000,
                                      "text": t, "latency_ms": 1400 if i % 2 == 0 else None} for i, t in enumerate([
        "Namaste, Sunrise Clinic mein aapka swagat hai. Main ek AI assistant hoon aur yeh call record ho sakti hai.",
        "Mujhe apne refund ke baare mein kisi insaan se baat karni hai, order number chaar hazaar aath sau ikkees.",
        "Mujhe khed hai, abhi koi insaan is call par nahi aa sakta. Kya aap apna phone number de sakte hain?"])])
    rest("POST", "callbacks", json={"tenant_id": tenant, "call_id": call["id"], "agent_id": agent["id"], "phone_e164": "+919876543210", "preferred_time": "kal subah", "reason": "Refund for order 4821"})
    rest("POST", "knowledge_sources", json={"tenant_id": tenant, "name": "Fee list and timings with a deliberately long name to test wrapping", "source_type": "text",
                                            "raw_text": "x" * 40, "status": "ready", "parsed_md": "Consultation Rs 600.", "stats": {"chunks": 3, "tokens": 120, "quality": {"tested": 3, "hit_rate": 1.0, "failed": []}}})
    rest("POST", "tools", json={"tenant_id": tenant, "name": "check_order_status", "description": "Look up an order by number when the caller gives one.",
                                "endpoint": "https://api.example.com/very/long/path/that/should/wrap/inside/the/card/without/breaking/the/layout", "parameters": {"type": "object", "properties": {}}})
    return agent["id"], call["id"]


class CDP:
    def __init__(self, ws):
        self.ws, self.n, self.waiters, self.events = ws, 0, {}, asyncio.Queue()

    async def pump(self):
        async for msg in self.ws:
            d = json.loads(msg.data)
            if "id" in d and d["id"] in self.waiters:
                self.waiters.pop(d["id"]).set_result(d)
            else:
                await self.events.put(d)

    async def send(self, method, params=None, session=None):
        self.n += 1
        fut = asyncio.get_event_loop().create_future()
        self.waiters[self.n] = fut
        await self.ws.send_str(json.dumps({"id": self.n, "method": method, "params": params or {}, **({"sessionId": session} if session else {})}))
        d = await asyncio.wait_for(fut, 60)
        if "error" in d:
            raise RuntimeError(f"{method}: {d['error']}")
        return d.get("result", {})


MEASURE = """(() => {
  const vw = document.documentElement.clientWidth;
  const wide = [...document.querySelectorAll('body *')].filter(e => {
    const r = e.getBoundingClientRect();
    if (r.width === 0 || getComputedStyle(e).position === 'fixed') return false;
    // elements inside a horizontally scrolling box (tables, code) are allowed to be wider than the screen
    for (let p = e.parentElement; p; p = p.parentElement) { const o = getComputedStyle(p).overflowX; if (o === 'auto' || o === 'scroll' || o === 'hidden') return false; }
    return r.right > vw + 1;
  }).slice(0, 4).map(e => e.tagName.toLowerCase() + '.' + String(e.className).slice(0, 50) + ' right=' + Math.round(e.getBoundingClientRect().right));
  const small = [...document.querySelectorAll('a, button, input:not([type=hidden]):not([type=checkbox]):not([type=radio]), select, textarea, summary')].filter(e => {
    const r = e.getBoundingClientRect(); const s = getComputedStyle(e);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && (r.height < 36 || r.width < 36) && !e.closest('.sr-only') && !(e.className + '').includes('sr-only');
  }).slice(0, 5).map(e => (e.innerText || e.getAttribute('aria-label') || e.name || e.tagName).toString().trim().slice(0, 24) + ' ' + Math.round(e.getBoundingClientRect().width) + 'x' + Math.round(e.getBoundingClientRect().height));
  return JSON.stringify({ vw, pageWidth: document.documentElement.scrollWidth, sideways: document.documentElement.scrollWidth > vw + 1, wide, small, title: document.title });
})()"""


async def main():
    email, pw = f"mob-{uuid.uuid4().hex[:6]}@example.com", "Test-pass-123"
    uid = httpx.post(f"{URL}/auth/v1/admin/users", headers=ADMIN, timeout=60, json={"email": email, "password": pw, "email_confirm": True}).json()["id"]
    tenant = rest("GET", f"tenant_members?select=tenant_id&user_id=eq.{uid}")[0]["tenant_id"]
    profile = tempfile.mkdtemp(prefix="chrome-mobile-")
    proc = None
    try:
        agent_id, call_id = seed(uid)
        cookies = session_cookies(email, pw)
        proc = subprocess.Popen([CHROME, "--headless=new", "--remote-debugging-port=9333", f"--user-data-dir={profile}", "--no-first-run", "--disable-gpu", "about:blank"],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        async with aiohttp.ClientSession() as http:
            ws_url = None
            for _ in range(40):
                try:
                    async with http.get("http://127.0.0.1:9333/json/version") as r:
                        ws_url = (await r.json())["webSocketDebuggerUrl"]
                        break
                except Exception:
                    await asyncio.sleep(0.5)
            ws = await http.ws_connect(ws_url, max_msg_size=0)
            cdp = CDP(ws)
            pump = asyncio.create_task(cdp.pump())
            target = (await cdp.send("Target.createTarget", {"url": "about:blank"}))["targetId"]
            sid = (await cdp.send("Target.attachToTarget", {"targetId": target, "flatten": True}))["sessionId"]
            await cdp.send("Page.enable", session=sid)
            await cdp.send("Network.enable", session=sid)
            for c in cookies:
                await cdp.send("Network.setCookie", {**c, "url": APP, "path": "/"}, session=sid)
            pages = [("login", "/login", False), ("home", "/", True), ("agents", "/agents", True), ("agent-instructions", f"/agents/{agent_id}", True),
                     ("agent-versions", f"/agents/{agent_id}?tab=versions", True), ("agent-tests", f"/agents/{agent_id}?tab=tests", True),
                     ("calls", "/calls", True), ("call-detail", f"/calls/{call_id}", True), ("knowledge", "/knowledge", True), ("tools", "/tools", True),
                     ("callbacks", "/callbacks", True), ("settings", "/settings", True),
                     ("wizard-1-type", "/onboarding/business-type", True), ("wizard-2-details", f"/onboarding/details?agent={agent_id}", True),
                     ("wizard-4-voice", f"/onboarding/voice?agent={agent_id}", True), ("wizard-5-test", f"/onboarding/test-call?agent={agent_id}", True)]
            OUT.mkdir(parents=True, exist_ok=True)
            problems = 0
            print(f"{'screen':<20}{'viewport':<12}result")
            for vname, (w, h, mobile) in VIEWPORTS.items():
                await cdp.send("Emulation.setDeviceMetricsOverride", {"width": w, "height": h, "deviceScaleFactor": 2, "mobile": mobile}, session=sid)
                await cdp.send("Emulation.setUserAgentOverride", {"userAgent": "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) AppleWebKit/605.1.15 Mobile/15E148"}, session=sid)
                for name, path, _auth in pages:
                    await cdp.send("Page.navigate", {"url": APP + path}, session=sid)
                    await asyncio.sleep(3.5)   # development pages compile on first visit
                    res = json.loads((await cdp.send("Runtime.evaluate", {"expression": MEASURE, "returnByValue": True}, session=sid))["result"]["value"])
                    shot = await cdp.send("Page.captureScreenshot", {"format": "png", "captureBeyondViewport": True}, session=sid)
                    (OUT / f"{name}-{vname}.png").write_bytes(base64.b64decode(shot["data"]))
                    bad = res["sideways"] or res["wide"]
                    problems += bool(bad)
                    note = ("SIDEWAYS SCROLL page=%dpx > %dpx; wide: %s" % (res["pageWidth"], res["vw"], res["wide"])) if bad else "ok"
                    if res["small"]:
                        note += "  | small targets: " + "; ".join(res["small"])
                    print(f"{name:<20}{vname:<12}{note}")
            pump.cancel()
        print(f"\n{problems} screen/size combinations scroll sideways. Screenshots: {OUT}")
    finally:
        if proc:
            proc.terminate()
        shutil.rmtree(profile, ignore_errors=True)
        httpx.delete(f"{URL}/auth/v1/admin/users/{uid}", headers=ADMIN, timeout=60)
        httpx.delete(f"{URL}/rest/v1/tenants?id=eq.{tenant}", headers=ADMIN, timeout=60)


asyncio.run(main())
