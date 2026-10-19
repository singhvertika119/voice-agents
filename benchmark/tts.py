"""TTS check: synthesize hard Hinglish/number sentences with Sarvam (and Cartesia if keyed); measure
time-to-audio and save WAVs to results/ for a listening test. Usage: python tts.py"""
import base64
import json
import time

import httpx

from common import RESULTS, key

SENTENCES = [
    "आपकी अपॉइंटमेंट कल शाम पाँच बजे है, फीस छह सौ रुपये होगी।",
    "Aapka order number 4821 hai, refund 48 ghante mein aa jayega.",
    "Dr. Sharma Monday, Wednesday aur Saturday ko available hain.",
    "कृपया अपना फ़ोन नंबर 9876543210 बताइए।",
]
out = {}
if key("SARVAM_API_KEY", False):
    for i, s in enumerate(SENTENCES):
        t0 = time.perf_counter()
        r = httpx.post(
            "https://api.sarvam.ai/text-to-speech",
            headers={"api-subscription-key": key("SARVAM_API_KEY")},
            json={"text": s, "target_language_code": "hi-IN", "speaker": "ritu", "model": "bulbul:v3"},
            timeout=60,
        )
        if r.status_code != 200:
            out[f"sarvam_{i}"] = {"error": r.status_code, "body": r.text[:200]}
            continue
        (RESULTS / f"tts_sarvam_{i}.wav").write_bytes(base64.b64decode(r.json()["audios"][0]))
        out[f"sarvam_{i}"] = {"chars": len(s), "seconds_to_audio": round(time.perf_counter() - t0, 2)}
if key("CARTESIA_API_KEY", False):
    for i, s in enumerate(SENTENCES):
        t0 = time.perf_counter()
        r = httpx.post(
            "https://api.cartesia.ai/tts/bytes",
            headers={"X-API-Key": key("CARTESIA_API_KEY"), "Cartesia-Version": "2025-04-16"},
            json={
                "model_id": "sonic-3",
                "transcript": s,
                "language": "hi",
                "voice": {"mode": "id", "id": "f786b574-daa5-4673-aa0c-cbe3e8534c02"},
                "output_format": {"container": "wav", "encoding": "pcm_s16le", "sample_rate": 22050},
            },
            timeout=60,
        )
        if r.status_code == 200:
            (RESULTS / f"tts_cartesia_{i}.wav").write_bytes(r.content)
            out[f"cartesia_{i}"] = {"chars": len(s), "seconds_to_audio": round(time.perf_counter() - t0, 2)}
        else:
            out[f"cartesia_{i}"] = {"error": r.status_code, "body": r.text[:200]}
print(json.dumps(out, indent=2, ensure_ascii=False))
(RESULTS / "tts.json").write_text(json.dumps(out, indent=2))
