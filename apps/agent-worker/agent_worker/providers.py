"""Build STT / LLM / TTS stacks from an AgentConfig. Providers whose key is missing are skipped, so a
single missing key degrades to fewer fallbacks instead of failing the call."""
from __future__ import annotations

import logging
import os
import time

import httpx

from livekit.agents import llm, stt, tts
from livekit.plugins import cartesia, deepgram, google, openai, sarvam

from .config import AgentConfig

log = logging.getLogger("providers")

# Providers that answered "out of credits / not allowed" are skipped for a while. Without this every new call
# first waits for the dead provider to fail before the backup takes over (seen: +5 s on the first turn).
_down_until: dict[str, float] = {}
DOWN_SECONDS = 600
TEMPERATURE = float(os.getenv("LLM_TEMPERATURE", "0.2"))   # lower = steadier answers; tuned against the grounding tests


def is_down(provider: str) -> bool:
    return _down_until.get(provider, 0) > time.time()


async def probe_providers() -> None:
    """Cheap check at call start, cached for DOWN_SECONDS. Only Sarvam needs it: it is the one primary that
    can run out of prepaid credit; the LLMs fail fast on their own and the fallback adapter handles them."""
    key = os.getenv("SARVAM_API_KEY")
    if not key or is_down("sarvam") or time.time() < _down_until.get("_probed_sarvam", 0):
        return
    _down_until["_probed_sarvam"] = time.time() + DOWN_SECONDS
    try:
        async with httpx.AsyncClient(timeout=4) as c:
            r = await c.post("https://api.sarvam.ai/text-to-speech", headers={"api-subscription-key": key},
                             json={"text": "Namaste", "target_language_code": "hi-IN", "speaker": "ritu", "model": "bulbul:v3"})
        if r.status_code in (401, 402, 403):
            _down_until["sarvam"] = time.time() + DOWN_SECONDS
            log.warning("Sarvam unavailable (HTTP %s: %s). Using backup providers for the next %d min.",
                        r.status_code, r.text[:80], DOWN_SECONDS // 60)
    except Exception as e:  # network trouble is not proof the account is empty; leave it enabled
        log.info("Sarvam probe inconclusive: %s", e)


def _has(*names: str) -> bool:
    return any(os.getenv(n) for n in names)


def _stt(spec: dict, lang: str):
    p = spec["provider"]
    if p == "sarvam" and _has("SARVAM_API_KEY") and not is_down("sarvam"):
        # high_vad_sensitivity: Sarvam's own speech detector declares the end of an utterance sooner
        return sarvam.STT(language=lang, model=spec["model"], mode=spec.get("mode", "transcribe"),
                          high_vad_sensitivity=spec.get("high_vad_sensitivity", True))
    if p == "deepgram" and _has("DEEPGRAM_API_KEY"):
        return deepgram.STT(model=spec["model"], language=lang.split("-")[0], sample_rate=16000)
    return None


def _tts(spec: dict, lang: str):
    p = spec["provider"]
    if p == "sarvam" and _has("SARVAM_API_KEY") and not is_down("sarvam"):
        return sarvam.TTS(target_language_code=lang, model=spec["model"], speaker=spec.get("speaker"))
    if p == "cartesia" and _has("CARTESIA_API_KEY"):
        return cartesia.TTS(model=spec["model"], language=lang.split("-")[0], word_timestamps=False)
    return None


def _llm(spec: dict, max_tokens: int):
    p = spec["provider"]
    if p == "groq" and _has("GROQ_API_KEY"):
        return openai.LLM(model=spec["model"], base_url="https://api.groq.com/openai/v1",
                          api_key=os.environ["GROQ_API_KEY"], temperature=TEMPERATURE,
                          max_completion_tokens=max_tokens, reasoning_effort=spec.get("reasoning_effort", "low"))
    if p == "gemini" and _has("GEMINI_API_KEY", "GOOGLE_API_KEY"):
        return google.LLM(model=spec["model"], api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"),
                          temperature=TEMPERATURE, max_output_tokens=max_tokens)
    if p == "openai" and _has("OPENAI_API_KEY"):  # switch via YAML once an OpenAI key exists
        return openai.LLM(model=spec["model"], temperature=TEMPERATURE, max_completion_tokens=max_tokens)
    return None


def _chain(adapter, items, what: str):
    items = [i for i in items if i is not None]
    if not items:
        raise RuntimeError(f"No usable {what} provider: check API keys in .env")
    if len(items) == 1:
        log.warning("%s has no fallback configured", what)
        return items[0]
    return adapter(items)


def build_stack(cfg: AgentConfig) -> dict:
    lang = cfg.language
    return {
        "stt": _chain(stt.FallbackAdapter, [_stt(cfg.stt["primary"], lang), _stt(cfg.stt["fallback"], lang)], "STT"),
        # attempt_timeout 4 s (library default 5 s; 2.5 s caused needless failovers under load, see D-050)
        "llm": _chain(lambda items: llm.FallbackAdapter(items, attempt_timeout=4.0),
                      [_llm(cfg.llm[k], cfg.llm.get("max_tokens", 200))
                       for k in ("primary", "fallback", "fallback2") if k in cfg.llm], "LLM"),
        "tts": _chain(tts.FallbackAdapter, [_tts(cfg.voice["tts_primary"], lang),
                                            _tts(cfg.voice["tts_fallback"], lang)], "TTS"),
    }


def build_llm(cfg: AgentConfig):
    """Just the model chain (with its backups). Used by test conversations, which have no audio."""
    return _chain(lambda items: llm.FallbackAdapter(items, attempt_timeout=4.0),
                  [_llm(cfg.llm[k], cfg.llm.get("max_tokens", 200)) for k in ("primary", "fallback", "fallback2") if k in cfg.llm], "LLM")
