"""Makes one of your agents phone a number and talk to whoever answers.

    uv run python scripts/call_me.py <agent id> <phone number>      e.g. +919876543210 or 9876543210

Needs an outbound SIP trunk in LiveKit (docs/phone-calls.md). Put its id and the number it dials from in .env:

    OUTBOUND_TRUNK_ID=ST_xxxxxxxx
    OUTBOUND_FROM_NUMBER=+1xxxxxxxxxx        (the number your SIP provider gave you)

The room is named 'live-<agent id>-<number>_<random>', so the call is answered by the agent's published version and
saved like any other phone call (transcript, summary, recording, memory). Call only numbers you own or have permission
to call: this places a real call and spends your SIP provider's credit.
"""
import asyncio
import os
import re
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT / "apps" / "agent-worker"))
sys.path.insert(0, str(ROOT / "packages" / "core"))

from livekit import api  # noqa: E402

from agent_worker import db  # noqa: E402
from agent_worker.tools import normalize_phone  # noqa: E402


async def main(agent_id: str, number: str) -> None:
    trunk = os.getenv("OUTBOUND_TRUNK_ID")
    sip_from = os.getenv("OUTBOUND_FROM_NUMBER")
    if not trunk or not sip_from:
        raise SystemExit("Set OUTBOUND_TRUNK_ID and OUTBOUND_FROM_NUMBER in .env first (see docs/phone-calls.md).")
    pub = await db.fetch_published(agent_id)   # stops with a clear message if the agent is missing or unpublished
    room = f"live-{agent_id}-{number}_{uuid.uuid4().hex[:6]}"
    agent_name = os.getenv("AGENT_NAME", "voice-platform")
    print(f"Calling {number} as {pub['agent']['name']} (published v{pub['version']}), room {room}")

    lk = api.LiveKitAPI(os.environ["LIVEKIT_URL"], os.environ["LIVEKIT_API_KEY"], os.environ["LIVEKIT_API_SECRET"])
    try:
        await lk.agent_dispatch.create_dispatch(api.CreateAgentDispatchRequest(agent_name=agent_name, room=room))
        try:
            await lk.sip.create_sip_participant(api.CreateSIPParticipantRequest(
                sip_trunk_id=trunk,
                sip_call_to=number,
                sip_number=sip_from,
                room_name=room,
                participant_identity=f"callee-{number}",
                participant_name="Callee",
                participant_attributes={"caller_number": number},
                wait_until_answered=True,
                ringing_timeout={"seconds": 45},
            ))
        except api.TwirpError as e:
            raise SystemExit(f"The call did not connect: {e.message} (code {e.code}, SIP status {e.metadata.get('sip_status', '?')}). "
                             "Not answered, rejected, or the SIP provider refused it; see the provider's call log.")
        print("Answered. The agent is talking to you now. Hang up on your phone to end the call, then check the Calls page.")
    finally:
        await lk.aclose()


if __name__ == "__main__":
    if len(sys.argv) != 3 or not db.is_agent_uuid(sys.argv[1]):
        raise SystemExit("Usage: call_me.py <agent id (uuid)> <phone number>")
    e164 = normalize_phone(sys.argv[2])
    if not e164:
        raise SystemExit("That does not look like a phone number. Use 10 digits for an Indian mobile or +<country code>... for others.")
    asyncio.run(main(sys.argv[1], e164))
