"""STT benchmark: WER + latency for Sarvam vs Deepgram on data/audio. Usage: python stt.py"""
import json
import re
import time

import httpx
from jiwer import wer

from common import AUDIO_DIR, RESULTS, key


def norm(s: str) -> str:
    return re.sub(r"[^\w\s]", "", s.lower()).strip()


def sarvam(wav: bytes) -> str:
    r = httpx.post(
        "https://api.sarvam.ai/speech-to-text",
        headers={"api-subscription-key": key("SARVAM_API_KEY")},
        files={"file": ("a.wav", wav, "audio/wav")},
        data={"model": "saaras:v3", "language_code": "hi-IN"},
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["transcript"]


def deepgram(wav: bytes) -> str:
    r = httpx.post(
        "https://api.deepgram.com/v1/listen?model=nova-3&language=hi&smart_format=true",
        headers={"Authorization": f"Token {key('DEEPGRAM_API_KEY')}", "Content-Type": "audio/wav"},
        content=wav,
        timeout=60,
    )
    r.raise_for_status()
    return r.json()["results"]["channels"][0]["alternatives"][0]["transcript"]


PROVIDERS = {}
if key("SARVAM_API_KEY", False):
    PROVIDERS["sarvam"] = sarvam
if key("DEEPGRAM_API_KEY", False):
    PROVIDERS["deepgram"] = deepgram

clips = sorted(AUDIO_DIR.glob("*.wav"))
if not clips:
    raise SystemExit("No audio. Run: python prepare_audio.py")
out = {}
for name, fn in PROVIDERS.items():
    refs, hyps, lat, errs = [], [], [], 0
    for c in clips:
        ref = norm(c.with_suffix(".txt").read_text(encoding="utf-8"))
        t0 = time.perf_counter()
        try:
            hyp = norm(fn(c.read_bytes()))
        except Exception as e:  # keep going; count failures
            errs += 1
            print(name, c.name, "ERR", e)
            continue
        lat.append(time.perf_counter() - t0)
        refs.append(ref)
        hyps.append(hyp)
    if refs:
        lat.sort()
        out[name] = {
            "clips": len(refs),
            "errors": errs,
            "wer": round(wer(refs, hyps), 4),
            "latency_p50_s": round(lat[len(lat) // 2], 2),
            "latency_max_s": round(lat[-1], 2),
        }
print(json.dumps(out, indent=2))
(RESULTS / "stt.json").write_text(json.dumps(out, indent=2))
