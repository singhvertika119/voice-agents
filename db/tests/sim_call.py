"""Simulated phone caller for end-to-end checks of recording, summary and memory. Needs the agent worker running.

    uv run python db/tests/sim_call.py <agent id>

Joins a room that asks for our worker, speaks two recorded Hindi clips (benchmark/data/audio), hangs up. It uses the made-up
number +919999900001, so delete that caller afterwards (Settings > Delete a caller data).
"""
import asyncio, glob, os, sys, time, uuid
import numpy as np, soundfile as sf
from scipy.signal import resample_poly
from dotenv import load_dotenv; load_dotenv(".env", override=True)
from livekit import api, rtc
AG=sys.argv[1]; SR=16000
# Optional second argument: a phone-style caller, e.g. +14155550100. The room is then named the way a SIP dispatch rule
# would name it (live-<agent>-<number>_<random>), so this also checks phone routing and non-Indian numbers.
PHONE=sys.argv[2] if len(sys.argv)>2 else None
def clip(path):
    x,sr=sf.read(path); x=resample_poly(x,SR,sr) if sr!=SR else x
    return (np.clip(x,-1,1)*32767).astype(np.int16)
async def main():
    room_name=f"live-{AG}-{PHONE}_{uuid.uuid4().hex[:6]}" if PHONE else f"live-{AG}-sim{uuid.uuid4().hex[:4]}"
    tok=(api.AccessToken(os.environ["LIVEKIT_API_KEY"],os.environ["LIVEKIT_API_SECRET"]).with_identity("sim-caller")
         .with_grants(api.VideoGrants(room_join=True,room=room_name)).with_attributes({"caller_number":PHONE or "+919999900001"})
         .with_room_config(api.RoomConfiguration(agents=[api.RoomAgentDispatch(agent_name=os.getenv("AGENT_NAME","voice-platform"))])).to_jwt())
    room=rtc.Room(); await room.connect(os.environ["LIVEKIT_URL"],tok)
    src=rtc.AudioSource(SR,1); track=rtc.LocalAudioTrack.create_audio_track("mic",src)
    await room.local_participant.publish_track(track,rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE))
    async def say(pcm):
        for i in range(0,len(pcm)-1600,1600):
            await src.capture_frame(rtc.AudioFrame(pcm[i:i+1600].tobytes(),SR,1,1600)); await asyncio.sleep(0.1)
    async def silence(sec):
        z=np.zeros(1600,np.int16)
        for _ in range(int(sec*10)): await src.capture_frame(rtc.AudioFrame(z.tobytes(),SR,1,1600)); await asyncio.sleep(0.1)
    clips=sorted(glob.glob("benchmark/data/audio/*.wav"))
    # SIM_CLIPS=short: the two shortest clips. LiveKit only starts a reply early for speech under 10 s, and the
    # default clips are 9.1 s and 13.8 s, so they hide that (D-116); real callers usually ask in a few seconds.
    clips=sorted(clips,key=lambda p:sf.info(p).duration)[:2] if os.getenv("SIM_CLIPS")=="short" else clips[:2]
    await silence(12)                       # let the greeting play
    for c in clips:
        print("speaking",os.path.basename(c)); await say(clip(c)); await silence(14)   # wait for the answer
    await silence(3)
    t=time.time(); await room.disconnect(); print("hung up at",time.strftime("%H:%M:%S"),"room",room_name)
asyncio.run(main())
