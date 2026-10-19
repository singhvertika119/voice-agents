"""LLM benchmark: time-to-first-token and keyword accuracy on Hinglish clinic questions.
Providers are enabled by the keys present in .env. Usage: python llm.py"""
import json
import time

import httpx

from common import RESULTS, key
from questions import KB, QUESTIONS

GEMINI = key('GEMINI_API_KEY', False) or key('GOOGLE_API_KEY', False)

SYSTEM = (
    "You are a phone receptionist for a clinic. Reply in the caller's language (Hindi/Hinglish/English), "
    "in 1-2 short spoken sentences. Answer ONLY from the knowledge below; if the answer is not there, say you "
    "don't have that information and offer a human.\n\nKnowledge:\n" + KB
)


def stream_openai_compat(url, api_key, model, q, extra=None):
    t0 = time.perf_counter()
    first, text = None, ""
    body = {
        "model": model,
        "stream": True,
        "max_tokens": 400,
        "temperature": 0.2,
        **(extra or {}),
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": q}],
    }
    if extra and "max_completion_tokens" in extra:
        body.pop("max_tokens")
    with httpx.stream("POST", url, headers={"Authorization": f"Bearer {api_key}"}, json=body, timeout=60) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if not line.startswith("data: ") or line.endswith("[DONE]"):
                continue
            choices = json.loads(line[6:]).get("choices") or [{}]
            d = choices[0].get("delta", {}).get("content")
            if d:
                first = first or time.perf_counter() - t0
                text += d
    return first, time.perf_counter() - t0, text


def stream_gemini(model, q):
    t0 = time.perf_counter()
    first, text = None, ""
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?alt=sse"
    body = {
        "systemInstruction": {"parts": [{"text": SYSTEM}]},
        "contents": [{"role": "user", "parts": [{"text": q}]}],
        "generationConfig": {"maxOutputTokens": 120, "temperature": 0.2},
    }
    with httpx.stream("POST", url, headers={"x-goog-api-key": GEMINI}, json=body, timeout=60) as r:
        r.raise_for_status()
        for line in r.iter_lines():
            if line.startswith("data: "):
                cand = json.loads(line[6:])["candidates"][0]
                for p in cand.get("content", {}).get("parts", []):
                    if p.get("text"):
                        first = first or time.perf_counter() - t0
                        text += p["text"]
    return first, time.perf_counter() - t0, text


import sys
ONLY = sys.argv[1:]
CANDIDATES = {}
if GEMINI:
    CANDIDATES["gemini-flash"] = lambda q: stream_gemini("gemini-2.5-flash", q)
if key("GROQ_API_KEY", False):
    _g = "https://api.groq.com/openai/v1/chat/completions"
    CANDIDATES["groq-gpt-oss-120b"] = lambda q: stream_openai_compat(
        _g, key("GROQ_API_KEY"), "openai/gpt-oss-120b", q, {"reasoning_effort": "low"})
    CANDIDATES["groq-gpt-oss-20b"] = lambda q: stream_openai_compat(
        _g, key("GROQ_API_KEY"), "openai/gpt-oss-20b", q, {"reasoning_effort": "low"})
if key("OPENAI_API_KEY", False):
    for _m in ("gpt-4.1-mini", "gpt-4o-mini"):
        CANDIDATES[f"openai-{_m}"] = (lambda m: lambda q: stream_openai_compat(
            "https://api.openai.com/v1/chat/completions", key("OPENAI_API_KEY"), m, q, {"max_completion_tokens": 400}))(_m)
if key("SARVAM_API_KEY", False):
    CANDIDATES["sarvam-105b"] = lambda q: stream_openai_compat(
        "https://api.sarvam.ai/v1/chat/completions", key("SARVAM_API_KEY"), "sarvam-105b", q
    )

CANDIDATES = {k: v for k, v in CANDIDATES.items() if not ONLY or any(o in k for o in ONLY)}
if not CANDIDATES:
    raise SystemExit("No LLM keys in .env")
out, samples = {}, {}
for name, fn in CANDIDATES.items():
    ttft, ok, errs = [], 0, 0
    samples[name] = []
    for q, expect in QUESTIONS:
        try:
            f, total, text = fn(q)
        except Exception as e:
            errs += 1
            print(name, q, "ERR", e)
            continue
        ttft.append(f or total)
        hit = any(x in text.lower() for x in expect)
        ok += hit
        samples[name].append({"q": q, "answer": text.strip(), "ttft": round(f or total, 2), "ok": hit})
        time.sleep(1)  # be polite to free-tier rate limits
    ttft.sort()
    if ttft:
        out[name] = {
            "n": len(QUESTIONS),
            "errors": errs,
            "keyword_accuracy": round(ok / len(QUESTIONS), 2),
            "ttft_p50_s": round(ttft[len(ttft) // 2], 2),
            "ttft_max_s": round(ttft[-1], 2),
        }
print(json.dumps(out, indent=2))
(RESULTS / ("llm_" + "_".join(ONLY) + ".json" if ONLY else "llm.json")).write_text(
    json.dumps({"summary": out, "samples": samples}, ensure_ascii=False, indent=2), encoding="utf-8"
)
