"""The simulated caller: an AI that plays a person with a goal, one short spoken line at a time."""
from __future__ import annotations

from . import llm

END = "<END>"

_STYLE = {
    "hinglish": "Speak Hinglish: Hindi in Roman letters mixed with English words, the way people talk on the phone in India.",
    "hindi": "Speak Hindi in Devanagari script.",
    "english": "Speak plain English only.",
}


class SimulatedCaller:
    def __init__(self, scenario: dict):
        self.s = scenario
        self.history: list[dict] = []   # {role: caller|agent, text}
        self.finished = False

    def _system(self) -> str:
        knows = self.s.get("caller_knows") or {}
        return (
            f"You are playing a person who has phoned a business. {self.s.get('persona', 'A normal caller.')}\n"
            f"{_STYLE.get(self.s.get('language', 'hinglish'), _STYLE['hinglish'])}\n"
            f"Your goal: {self.s['goal']}\n"
            + (f"Facts you know: {knows}\n" if knows else "")
            + "Rules: say only 1 or 2 short spoken sentences per turn. Never say you are an AI or that this is a test. "
              "Do not repeat what the agent said. If the agent asks for your phone number and you know it, say it digit by digit. "
              "If the agent's last message asks you a question or asks you to confirm something, answer it. Only when your goal is fully "
              "done (for example the agent confirmed a booking) or you give up, reply with exactly <END> and nothing else."
        )

    async def next_line(self, agent_said: str | None) -> str:
        """Returns the caller's next utterance, or END."""
        if agent_said is not None:
            self.history.append({"role": "agent", "text": agent_said})
        elif self.s.get("opening") and not self.history:
            self.history.append({"role": "caller", "text": self.s["opening"]})
            return self.s["opening"]
        msgs = [{"role": "system", "content": self._system()}]
        for h in self.history:  # from the caller's point of view, the agent is the other speaker
            msgs.append({"role": "assistant" if h["role"] == "caller" else "user", "content": h["text"]})
        if not self.history:
            msgs.append({"role": "user", "content": "(The phone is answered. Say your first line.)"})
        text = (await llm.chat(msgs, temperature=0.8, max_tokens=80)).strip()
        if END in text:
            # "Yes that is right. <END>": say the words, then stop after the agent has replied to them.
            text = text.replace(END, "").strip()
            self.finished = True
            if not text:
                return END
        self.history.append({"role": "caller", "text": text})
        return text
