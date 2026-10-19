"""Checks that the LiveKit project in .env belongs to this platform only.

    uv run python db/tests/check_livekit.py

1. The keys work.
2. Nobody else's worker answers rooms: a room is created WITHOUT asking for our worker by name, and no agent should
   join. (Our own worker is named, so it ignores such rooms; any agent that does join is someone else's.)
3. If our worker is running, a room that asks for it by name gets exactly one agent.

Run it once with our worker closed (checks 1 and 2) and once with it open (check 3).
"""
import asyncio
import os
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv
from livekit import api, rtc

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env", override=True)
URL, KEY, SECRET = os.environ["LIVEKIT_URL"], os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"]
NAME = os.getenv("AGENT_NAME", "voice-platform")


async def agents_in(room_name: str, explicit: bool, wait_s: int) -> list[str]:
    grants = api.VideoGrants(room_join=True, room=room_name)
    tok = api.AccessToken(KEY, SECRET).with_identity("check").with_grants(grants)
    if explicit:
        tok = tok.with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=NAME)]))
    room = rtc.Room()
    await room.connect(URL, tok.to_jwt())
    found: list[str] = []
    for _ in range(wait_s * 2):
        found = [p.identity for p in room.remote_participants.values() if p.identity.startswith("agent")]
        if found:
            break
        await asyncio.sleep(0.5)
    await room.disconnect()
    return found


async def main() -> int:
    bad = 0
    lk = api.LiveKitAPI(URL.replace("wss://", "https://"), KEY, SECRET)
    try:
        await lk.room.list_rooms(api.ListRoomsRequest())
        print("PASS keys work for", URL)
    except Exception as e:
        print("FAIL keys do not work:", e)
        return 1
    finally:
        await lk.aclose()

    other = await agents_in(f"isolation-check-{uuid.uuid4().hex[:6]}", explicit=False, wait_s=12)
    if other:
        bad += 1
        print("FAIL another app's agent answered a room that did not ask for ours:", other,
              "\n     This LiveKit project is shared. Create a separate project for this platform.")
    else:
        print("PASS no other app's agent answers rooms on this project")

    # The room name must carry a real, published agent id, or our worker rightly refuses the job before joining.
    import httpx
    sb = os.environ["SUPABASE_URL"].rstrip("/")
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    rows = httpx.get(f"{sb}/rest/v1/agents?select=id&published_version=not.is.null&limit=1", headers={"apikey": key, "Authorization": f"Bearer {key}"}, timeout=30).json()
    if not rows:
        print("INFO no published agent exists, so check 3 was skipped. Publish one and run again.")
        return bad
    mine = await agents_in(f"live-{rows[0]['id']}-{uuid.uuid4().hex[:4]}", explicit=True, wait_s=20)
    if len(mine) == 1:
        print("PASS our worker answered a room that asked for it by name (exactly one agent)")
    elif not mine:
        print("INFO our worker is not running (or not registered), so check 3 was skipped. Start it and run again.")
    else:
        bad += 1
        print("FAIL more than one agent joined:", mine)
    return bad


sys.exit(asyncio.run(main()))
