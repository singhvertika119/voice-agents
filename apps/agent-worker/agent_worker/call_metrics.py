"""Per-turn latency and per-call provider cost, written as JSONL (one file per call) in logs/.

Cost rates are rough list prices in USD, kept here so they are easy to correct (docs/decision.md D-009).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from livekit.agents import metrics

# USD. Free tiers make the real spend zero; these record what production would cost.
RATES = {
    "stt_per_sec": 0.0083 / 60,      # ~Rs 30/hour Sarvam / Deepgram-class
    "tts_per_char": 15 / 10_000 / 85,  # Rs 15 per 10K chars (bulbul v2 list), Rs/USD ~85
    "llm_in_per_tok": 0.10 / 1e6,
    "llm_cached_share": 0.5,          # cached input is billed at half the input price (OpenAI gpt-4o-mini, Groq gpt-oss)
    "llm_out_per_tok": 0.50 / 1e6,
}


class CallMetricsLog:
    def __init__(self, log_dir: Path, call_id: str, agent_id: str):
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{call_id}.jsonl"
        self.agent_id = agent_id
        self.totals = {"stt_sec": 0.0, "tts_chars": 0, "llm_in": 0, "llm_cached": 0, "llm_out": 0}
        self._turns: list[dict] = []   # one entry per caller turn: eou, ttft, ttfb
        self._replies: list[dict] = []  # per reply, from the messages' own timings (on_message)
        self._caller: dict | None = None
        self._search_ms = 0
        self._write({"event": "call_started", "agent_id": agent_id})

    def _write(self, rec: dict):
        rec["ts"] = round(time.time(), 3)
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    def on_metrics(self, m) -> None:
        if isinstance(m, metrics.EOUMetrics):
            self._turns.append({"eou": m.end_of_utterance_delay})
            self._write({"event": "turn", "end_of_utterance_delay_s": round(m.end_of_utterance_delay, 3),
                         "transcription_delay_s": round(m.transcription_delay, 3)})
        elif isinstance(m, metrics.LLMMetrics):
            # Calls before the first caller turn are the warm-up request; later ones belong to the latest turn.
            if self._turns and "ttft" not in self._turns[-1]:
                self._turns[-1]["ttft"] = m.ttft
            self.totals["llm_in"] += m.prompt_tokens
            self.totals["llm_cached"] += getattr(m, "prompt_cached_tokens", 0) or 0   # part of llm_in served from the provider's cache
            self.totals["llm_out"] += m.completion_tokens
            self._write({"event": "llm", "provider": getattr(m, "label", ""), "model": (m.metadata.model_name if getattr(m, "metadata", None) else ""), "ttft_s": round(m.ttft, 3), "prompt_tokens": m.prompt_tokens,
                         "cached_tokens": getattr(m, "prompt_cached_tokens", 0) or 0,
                         "completion_tokens": m.completion_tokens, "reasoning_tokens": m.reasoning_tokens})
        elif isinstance(m, metrics.TTSMetrics):
            if self._turns and "ttfb" not in self._turns[-1] and "ttft" in self._turns[-1]:
                self._turns[-1]["ttfb"] = m.ttfb
                t = self._turns[-1]
                self._write({"event": "reply", "reply_s": round(t["eou"] + t["ttft"] + m.ttfb, 3)})
            self.totals["tts_chars"] += m.characters_count
            self._write({"event": "tts", "provider": getattr(m, "label", ""), "ttfb_s": round(m.ttfb, 3), "chars": m.characters_count})
        elif isinstance(m, metrics.STTMetrics):
            self.totals["stt_sec"] += m.audio_duration
            self._write({"event": "stt", "provider": getattr(m, "label", ""), "audio_s": round(m.audio_duration, 2)})

    def on_prepared(self, ms: int) -> None:
        """Time the model waited for the language hint and knowledge search (from VoiceAgent.llm_node)."""
        self._search_ms = ms

    def on_message(self, role: str, m: dict) -> None:
        """Timings LiveKit attaches to each message: the caller's has the end-of-turn wait, the agent's has the model's
        first word, the voice's first audio and e2e_latency (caller stopped speaking -> agent started speaking)."""
        ms = lambda s: round((s or 0) * 1000)  # noqa: E731
        if role == "user":
            self._caller = {"wait": ms(m.get("end_of_turn_delay")), "transcript": ms(m.get("transcription_delay"))}
        elif role == "assistant" and m.get("e2e_latency") is not None and self._caller:
            self._replies.append({**self._caller, "search": self._search_ms,
                                  "first_word": ms(m.get("llm_node_ttft")), "voice": ms(m.get("tts_node_ttfb")),
                                  "total": ms(m["e2e_latency"])})
            self._write({"event": "reply_timing", **self._replies[-1]})
            self._caller, self._search_ms = None, 0

    def reply_times(self) -> list[float]:
        """Per reply, seconds from the caller going quiet to the agent's voice starting. LiveKit's own measure since
        D-116; the parts (wait, search, model, voice) can overlap, so they are no longer added up. Older formula
        (end-of-utterance + first token + first audio, which left out the search) only if that is missing."""
        if self._replies:
            return [r["total"] / 1000 for r in self._replies]
        return [t["eou"] + t["ttft"] + t["ttfb"] for t in self._turns if "ttft" in t and "ttfb" in t]

    def turn_timings(self) -> list[dict]:
        """Per reply, in ms, saved with the call for the dashboard's "Reply times" card (D-115, D-116)."""
        return self._replies

    def avg_reply_ms(self) -> int | None:
        r = self.reply_times()
        return round(sum(r) / len(r) * 1000) if r else None

    def cost_usd(self) -> float:
        t = self.totals
        cached = t.get("llm_cached", 0)
        return (t["stt_sec"] * RATES["stt_per_sec"] + t["tts_chars"] * RATES["tts_per_char"]
                + (t["llm_in"] - cached) * RATES["llm_in_per_tok"]
                + cached * RATES["llm_in_per_tok"] * RATES["llm_cached_share"]
                + t["llm_out"] * RATES["llm_out_per_tok"])

    def close(self) -> None:
        self._write({"event": "call_ended", "totals": self.totals, "cost_usd": round(self.cost_usd(), 5)})
