"""After the call: transcribe the caller's side of the recording again, a whole sentence at a time, and use that as
the saved transcript (docs/decision.md D-097).

The live transcript comes from streaming speech recognition, which hears the audio in small pieces and has to decide
quickly that the caller has stopped. On real calls it chopped and merged sentences ("jaan nahi tha haan haan baare
mein ..."), while the same Sarvam model given the complete sentence from the recording got it right ("mujhe jaanna tha
Schoollog ke baare mein"). The live text still drives the live replies; this only improves what is stored, the
summary and the caller's memory. It never raises, and it gives up within a time limit so the call is always saved.
"""
from __future__ import annotations

import asyncio
import io
import logging
import os
import wave
from pathlib import Path

import av
import httpx
import numpy as np

log = logging.getLogger("retranscribe")

SR = 16000
MAX_PIECE_S = 25          # Sarvam's REST endpoint takes at most 30 s of audio per request
SILENCE_GAP_S = 0.8       # a pause this long ends a piece, so sentences are not cut mid-word
ASSIGN_SLACK_S = 1.5      # a turn is saved a moment after the caller's speech ends
PARALLEL = 4
MIN_WORDS = 3             # see worth_replacing
ENABLED = os.getenv("RETRANSCRIBE", "1") == "1"


def caller_channel(path: Path) -> np.ndarray:
    """The caller is the left channel of the recorder's file (D-067). 16 kHz mono int16."""
    with av.open(str(path)) as c:
        res = av.AudioResampler(format="s16", layout="stereo", rate=SR)
        frames = [g.to_ndarray().reshape(-1, 2) for f in c.decode(audio=0) for g in res.resample(f)]
    return np.concatenate(frames)[:, 0] if frames else np.zeros(0, dtype=np.int16)


def speech_pieces(x: np.ndarray) -> list[tuple[float, float, np.ndarray]]:
    """Split on silence into (start_s, end_s, samples) pieces of speech, each under MAX_PIECE_S."""
    win = SR // 10
    if len(x) < win:
        return []
    energy = np.array([np.abs(x[i:i + win].astype(np.int32)).mean() for i in range(0, len(x), win)])
    voiced = energy > max(200.0, float(np.percentile(energy, 60)) * 0.5)
    gap = int(SILENCE_GAP_S * 10)
    spans, start, last = [], None, None
    for i, v in enumerate(voiced):
        if v and start is None:
            start = i
        if v:
            last = i
        if start is not None and (i - last > gap or i - start >= MAX_PIECE_S * 10):
            spans.append((start, last + 1))
            start = None
    if start is not None:
        spans.append((start, last + 1))
    pad = SR // 5
    return [(a / 10, b / 10, x[max(0, a * win - pad): b * win + pad]) for a, b in spans if b - a >= 4]


def assign(caller_turns: list[dict], pieces: list[tuple[float, float, str]]) -> dict[int, str]:
    """Give each transcribed piece to the first caller turn saved at or after the piece ended. Returns {seq: text}."""
    out: dict[int, list[str]] = {}
    ordered = sorted(caller_turns, key=lambda t: t["at_ms"])
    for _, end_s, text in pieces:
        if not text:
            continue
        turn = next((t for t in ordered if t["at_ms"] / 1000 >= end_s - ASSIGN_SLACK_S), None)
        if turn is not None:
            out.setdefault(turn["seq"], []).append(text)
    return {seq: " ".join(parts) for seq, parts in out.items()}


def worth_replacing(live: str, new: str) -> bool:
    """Whole-sentence recognition fixes sentences, but on a lone word it has no context and can do worse than the live
    text (a spoken "No" came back as "nau", nine). Replace only when either version is a phrase of 3 words or more."""
    return bool(new) and new != live and max(len(live.split()), len(new.split())) >= MIN_WORDS


def _wav(x: np.ndarray) -> bytes:
    b = io.BytesIO()
    with wave.open(b, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(SR)
        w.writeframes(x.astype(np.int16).tobytes())
    return b.getvalue()


async def _sarvam(c: httpx.AsyncClient, audio: bytes, model: str, mode: str, language: str) -> str:
    r = await c.post("https://api.sarvam.ai/speech-to-text", headers={"api-subscription-key": os.environ["SARVAM_API_KEY"]},
                     files={"file": ("piece.wav", audio, "audio/wav")},
                     data={"model": model, "mode": mode, "language_code": language})
    r.raise_for_status()
    return (r.json().get("transcript") or "").strip()


async def caller_turn_texts(recording: Path, caller_turns: list[dict], stt_spec: dict, language: str,
                            timeout_s: float = 30) -> dict[int, str]:
    """Better text for caller turns, as {seq: text}. Empty when disabled, without a Sarvam key, or on any failure."""
    if not (ENABLED and caller_turns and os.getenv("SARVAM_API_KEY") and recording.exists()):
        return {}
    try:
        return await asyncio.wait_for(_run(recording, caller_turns, stt_spec, language), timeout_s)
    except Exception as e:   # includes the time limit: the live transcript is kept as it is
        log.warning("re-transcription skipped: %s", str(e)[:160] or type(e).__name__)
        return {}


async def _run(recording: Path, caller_turns: list[dict], stt_spec: dict, language: str) -> dict[int, str]:
    x = await asyncio.to_thread(caller_channel, recording)
    pieces = await asyncio.to_thread(speech_pieces, x)
    if not pieces:
        return {}
    model = stt_spec.get("model", "saaras:v3") if stt_spec.get("provider") == "sarvam" else "saaras:v3"
    mode = stt_spec.get("mode", "codemix") if stt_spec.get("provider") == "sarvam" else "codemix"
    sem = asyncio.Semaphore(PARALLEL)
    async with httpx.AsyncClient(timeout=10) as c:
        async def one(audio: np.ndarray) -> str:
            async with sem:
                try:
                    return await _sarvam(c, _wav(audio), model, mode, language)
                except Exception as e:
                    log.info("one piece could not be re-transcribed: %s", str(e)[:100])
                    return ""
        texts = await asyncio.gather(*(one(a) for _, _, a in pieces))
    live = {t["seq"]: t["text"] for t in caller_turns}
    result = {seq: text for seq, text in assign(caller_turns, [(s, e, t) for (s, e, _), t in zip(pieces, texts)]).items()
              if worth_replacing(live.get(seq, ""), text)}
    log.info("re-transcribed %d of %d caller turns from %d pieces", len(result), len(caller_turns), len(pieces))
    return result
