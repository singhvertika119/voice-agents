"""Call recordings, kept on our own storage only (docs/decision.md D-067).

LiveKit Agents can record a session itself, but that path uploads audio and transcripts to LiveKit's servers. We use
only its local recorder (`RecorderIO`, one file, caller on the left channel and agent on the right), then turn the
file into an AAC .m4a, which plays in every browser (Ogg Opus does not on Safari), and upload it to a private
Supabase bucket. The file never leaves this machine except for that upload.
"""
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import av
from livekit.agents.voice.recorder_io import RecorderIO
from vp_core import supa

log = logging.getLogger("recording")
BUCKET = "recordings"


def to_m4a(src: Path, dst: Path) -> float:
    """Decode any audio file PyAV can read and write stereo AAC. Returns the duration in seconds."""
    with av.open(str(src)) as inp, av.open(str(dst), mode="w", format="mp4") as out:
        in_stream = inp.streams.audio[0]
        rate = 48000
        stream = out.add_stream("aac", rate=rate)
        stream.layout = "stereo"
        stream.bit_rate = 64000
        resampler = av.AudioResampler(format="fltp", layout="stereo", rate=rate)
        samples = 0
        for frame in inp.decode(in_stream):
            for f in resampler.resample(frame):
                samples += f.samples
                for packet in stream.encode(f):
                    out.mux(packet)
        for f in resampler.resample(None) or []:
            samples += f.samples
            for packet in stream.encode(f):
                out.mux(packet)
        for packet in stream.encode(None):
            out.mux(packet)
    return samples / rate


def object_path(tenant_id: str, call_id: str) -> str:
    return f"{tenant_id}/{call_id}.m4a"


async def store(ogg: Path, tenant_id: str, call_id: str) -> tuple[str, float] | None:
    """Convert, upload, and delete the local files. Returns (object path, seconds) or None. Never raises."""
    m4a = ogg.with_suffix(".m4a")
    try:
        if not ogg.exists() or ogg.stat().st_size < 500:
            return None
        seconds = await asyncio.to_thread(to_m4a, ogg, m4a)
        path = object_path(tenant_id, call_id)
        await supa.upload(BUCKET, path, m4a.read_bytes(), "audio/mp4")
        return path, round(seconds, 1)
    except Exception as e:
        log.warning("could not store the recording for call %s: %s", call_id, e)
        return None
    finally:
        for f in (ogg, m4a):
            try:
                f.unlink(missing_ok=True)
            except OSError:
                pass


class CallRecorder:
    """Wraps one AgentSession's audio in and out. Create it, `await attach()` after the session has started."""

    def __init__(self, session, local_dir: Path, call_key: str):
        self._session = session
        self._path = local_dir / f"{call_key}.ogg"
        self._io: RecorderIO | None = None
        self.started_at: float | None = None

    async def attach(self) -> bool:
        s = self._session
        if not (s.input.audio and s.output.audio):
            log.warning("no audio on this session; not recording")
            return False
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._io = RecorderIO(agent_session=s)
            s.input.audio = self._io.record_input(s.input.audio)
            s.output.audio = self._io.record_output(s.output.audio)
            await self._io.start(output_path=self._path)
            self.started_at = self._io.recording_started_at
            return True
        except Exception as e:
            log.warning("recording could not start: %s", e)
            self._io = None
            return False

    async def finish(self, tenant_id: str | None, call_id: str | None) -> tuple[str, float] | None:
        if not self._io:
            return None
        try:
            await self._io.aclose()
        except Exception as e:
            log.warning("recorder did not close cleanly: %s", e)
        if not (tenant_id and call_id):
            self._path.unlink(missing_ok=True)   # local mode: keep nothing on disk
            return None
        return await store(self._path, tenant_id, call_id)
