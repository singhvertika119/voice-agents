"""End-to-end check of call recordings against the real project.

    uv run python db/tests/e2e_recording.py

Builds a synthetic two-channel recording, runs it through the same store step a real call uses, then checks: the file
is a playable m4a in the private bucket, a signed link works and an unauthenticated or other-user request does not,
the retention purge removes old audio, and removal works. Needs migration 0006 for the last two checks.
"""
import asyncio
import math
import os
import sys
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import av
import httpx
import numpy as np
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(ROOT / "packages/core"), str(ROOT / "apps/agent-worker"), str(ROOT / "apps/ingestion-worker")]
load_dotenv(ROOT / ".env", override=True)

from agent_worker.recording import BUCKET, store  # noqa: E402
from ingestion.main import purge_recordings  # noqa: E402
from vp_core import supa  # noqa: E402

URL, ANON, SVC = os.environ["SUPABASE_URL"].rstrip("/"), os.environ["SUPABASE_ANON_KEY"], os.environ["SUPABASE_SERVICE_ROLE_KEY"]
T = 60
ADMIN = {"apikey": SVC, "Authorization": f"Bearer {SVC}", "Content-Type": "application/json"}
bad: list[str] = []


def check(name, ok, extra=""):
    print("PASS" if ok else "FAIL", name, extra)
    if not ok:
        bad.append(name)


def make_ogg(path: Path, seconds=3.0, rate=48000):
    t = np.arange(int(seconds * rate)) / rate
    data = np.stack([(0.3 * np.sin(2 * math.pi * 440 * t)).astype(np.float32), (0.3 * np.sin(2 * math.pi * 660 * t)).astype(np.float32)])
    with av.open(str(path), mode="w", format="ogg") as out:
        stream = out.add_stream("libopus", rate=rate)
        stream.layout = "stereo"
        frame = av.AudioFrame.from_ndarray(data, format="fltp", layout="stereo")
        frame.sample_rate = rate
        for p in stream.encode(frame):
            out.mux(p)
        for p in stream.encode(None):
            out.mux(p)


def make_user(tag):
    email = f"rec-{tag}-{uuid.uuid4().hex[:6]}@example.com"
    uid = httpx.post(f"{URL}/auth/v1/admin/users", headers=ADMIN, timeout=T, json={"email": email, "password": "Test-pass-123", "email_confirm": True}).json()["id"]
    tok = httpx.post(f"{URL}/auth/v1/token?grant_type=password", headers={"apikey": ANON}, timeout=T, json={"email": email, "password": "Test-pass-123"}).json()["access_token"]
    return uid, tok


async def main():
    a_id, _ = make_user("a")
    b_id, b_tok = make_user("b")
    tenant = (await supa.select("tenant_members", select="tenant_id", user_id=f"eq.{a_id}"))[0]["tenant_id"]
    tenant_b = (await supa.select("tenant_members", select="tenant_id", user_id=f"eq.{b_id}"))[0]["tenant_id"]
    call_id = str(uuid.uuid4())
    tmp = ROOT / "logs" / "recordings"
    tmp.mkdir(parents=True, exist_ok=True)
    ogg = tmp / f"e2e-{call_id[:8]}.ogg"
    path = None
    try:
        make_ogg(ogg, 3.0)
        out = await store(ogg, tenant, call_id)
        check("recording was converted and uploaded", out is not None and 2.5 < out[1] < 3.6, str(out))
        path = out[0] if out else None
        check("local audio files were deleted after upload", not ogg.exists() and not ogg.with_suffix(".m4a").exists())
        if path:
            data = await supa.download(BUCKET, path)
            check("stored object is an m4a file", data[4:8] == b"ftyp" and len(data) > 3000, f"{len(data)} bytes")
            async with supa.client() as c:
                r = await c.post(f"/storage/v1/object/sign/{BUCKET}/{path}", json={"expiresIn": 60})
                signed = r.json().get("signedURL")
            check("a signed link is issued", bool(signed))
            if signed:
                g = httpx.get(f"{URL}/storage/v1{signed}", timeout=T)
                check("the signed link plays without any login", g.status_code == 200 and g.content[4:8] == b"ftyp", str(g.status_code))
            anon = httpx.get(f"{URL}/storage/v1/object/{BUCKET}/{path}", headers={"apikey": ANON}, timeout=T)
            check("an anonymous request is refused", anon.status_code in (400, 401, 403, 404), str(anon.status_code))
            other = httpx.get(f"{URL}/storage/v1/object/authenticated/{BUCKET}/{path}", headers={"apikey": ANON, "Authorization": f"Bearer {b_tok}"}, timeout=T)
            check("another workspace's user cannot fetch it", other.status_code in (400, 401, 403, 404), str(other.status_code))
            public = httpx.get(f"{URL}/storage/v1/object/public/{BUCKET}/{path}", timeout=T)
            check("the bucket is not public", public.status_code in (400, 401, 403, 404), str(public.status_code))

        # needs migration 0006
        try:
            await supa.select("calls", select="recording_path", limit="1")
            has_col = True
        except Exception:
            has_col = False
        if not has_col:
            print("INFO migration 0006 is not applied yet: skipped the purge check")
        elif path:
            ag = (await supa.insert("agents", {"tenant_id": tenant, "name": "rec test"}))[0]
            old = (await supa.insert("calls", {"tenant_id": tenant, "agent_id": ag["id"], "agent_version": 1, "recording_path": path,
                                               "started_at": (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()}))[0]
            await supa.insert("tenant_settings", {"tenant_id": tenant, "retention_days": 2})
            n = await purge_recordings()
            check("retention purge removed the old recording", n >= 1, f"{n} removed")
            check("the call row no longer points at a file", (await supa.select("calls", select="recording_path", id=f"eq.{old['id']}"))[0]["recording_path"] is None)
            try:
                await supa.download(BUCKET, path)
                check("the audio file is really gone", False)
            except FileNotFoundError:
                check("the audio file is really gone", True)
            path = None
    finally:
        if path:
            await supa.remove(BUCKET, [path])
        for uid in (a_id, b_id):
            httpx.delete(f"{URL}/auth/v1/admin/users/{uid}", headers=ADMIN, timeout=T)
        for t in (tenant, tenant_b):
            httpx.delete(f"{URL}/rest/v1/tenants?id=eq.{t}", headers=ADMIN, timeout=T)
    print("\nAll recording checks passed." if not bad else f"\n{len(bad)} FAILED: {bad}")
    sys.exit(1 if bad else 0)


asyncio.run(main())
