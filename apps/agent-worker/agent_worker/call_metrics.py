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
    "llm_out_per_tok": 0.50 / 1e6,
}


class CallMetricsLog:
    def __init__(self, log_dir: Path, call_id: str, agent_id: str):
        log_dir.mkdir(parents=True, exist_ok=True)
        self.path = log_dir / f"{call_id}.jsonl"
        self.agent_id = agent_id
        self.totals = {"stt_sec": 0.0, "tts_chars": 0, "llm_in": 0, "llm_out": 0}
        self._turns: list[dict] = []   # one entry per caller turn: eou, ttft, ttfb
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
            self.totals["llm_out"] += m.completion_tokens
            self._write({"event": "llm", "ttft_s": round(m.ttft, 3), "prompt_tokens": m.prompt_tokens,
                         "completion_tokens": m.completion_tokens, "reasoning_tokens": m.reasoning_tokens})
        elif isinstance(m, metrics.TTSMetrics):
            if self._turns and "ttfb" not in self._turns[-1] and "ttft" in self._turns[-1]:
                self._turns[-1]["ttfb"] = m.ttfb
                t = self._turns[-1]
                self._write({"event": "reply", "reply_s": round(t["eou"] + t["ttft"] + m.ttfb, 3)})
            self.totals["tts_chars"] += m.characters_count
            self._write({"event": "tts", "ttfb_s": round(m.ttfb, 3), "chars": m.characters_count})
        elif isinstance(m, metrics.STTMetrics):
            self.totals["stt_sec"] += m.audio_duration
            self._write({"event": "stt", "audio_s": round(m.audio_duration, 2)})

    def reply_times(self) -> list[float]:
        """Per caller turn: end-of-utterance delay + LLM first token + voice first byte, in seconds."""
        return [t["eou"] + t["ttft"] + t["ttfb"] for t in self._turns if "ttft" in t and "ttfb" in t]

    def avg_reply_ms(self) -> int | None:
        r = self.reply_times()
        return round(sum(r) / len(r) * 1000) if r else None

    def cost_usd(self) -> float:
        t = self.totals
        return (t["stt_sec"] * RATES["stt_per_sec"] + t["tts_chars"] * RATES["tts_per_char"]
                + t["llm_in"] * RATES["llm_in_per_tok"] + t["llm_out"] * RATES["llm_out_per_tok"])

    def close(self) -> None:
        self._write({"event": "call_ended", "totals": self.totals, "cost_usd": round(self.cost_usd(), 5)})
