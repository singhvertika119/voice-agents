"""Built-in tools every agent has: ask for a person, book a callback, end the call.

Tools talk to a Backend. In a real call the backend writes to the database; in a test conversation it just
records what happened (docs/decision.md D-047). A live transfer to a human phone needs a phone line, which
does not exist yet, so for now "get me a person" always ends in a booked callback.
"""
from __future__ import annotations

import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from livekit.agents import RunContext, function_tool

log = logging.getLogger("tools")
IST = timezone(timedelta(hours=5, minutes=30))

DEFAULT_HOURS = {"days": [1, 2, 3, 4, 5, 6], "start": "09:00", "end": "19:00"}  # ISO weekday: 1 = Monday

# Appended to every agent's instructions. Written for the model; kept short because every word costs time.
# Found by the first test run (D-048): without these, agents answered English callers in Hindi, offered a live
# transfer they cannot do, and said "I don't know" to a vague caller instead of asking what they meant.
CONVERSATION_RULES = """

Always:
- Reply in the language of the caller's most recent message: English gets English, Hindi in Roman letters gets
  Roman Hinglish, Devanagari gets Devanagari.
- If the caller is vague or unsure what they want, ask exactly one short clarifying question before saying you do not know.
- You cannot connect a call to a person live. Offer a callback from the team instead.
- For a broad question such as "what do you do" or "tell me about yourselves", give a two-sentence summary of the
  main things you know instead of saying you have no information.
- If a "Caller context" section is present, it is your record of earlier calls with this caller: use it when they ask
  about earlier calls or what was discussed. If there is no such section, you have no record and should say so.
- Say only what the business information states. For anything it does not state (names, numbers, experience, features,
  policies, who or what is included) say you do not have it. Never fill gaps with what is usual for such a business.
- Answer only what was asked. Do not add related facts, benefits or praise (best, perfect, powerful, leading) the caller
  did not ask for, even if the information contains them.
- Words matter: if the caller uses a different word from the information (founder vs CEO, free vs cheap), do not treat
  them as the same; say what you know in the information's own words.
- If the caller assumes something the information contradicts or does not support (a price, a time, a name, a feature),
  never agree. Politely give the correct fact, or say you do not have it.
- If the caller pushes back on a fact you gave ("but I was told 1000"), stay calm and repeat the fact from the information
  once more. Do not retreat to "I do not know" about something you just answered, and do not give in.
- For "where are you", "how can I reach or visit you" or "how do I book", give the address and the ways to book or
  contact that the information states. Only say you lack a phone number if the information gives none.
- Use the business name exactly as written in the information; if none is given, say "we".
- Keep every reply to one or two short spoken sentences."""

TOOL_RULES = """
When to use your tools:
- If the caller asks for a person, or you could not help after two tries, or it is a complaint, payment dispute,
  legal matter or medical emergency: call request_human, then follow what it tells you.
- Before schedule_callback, YOU read the phone number back digit by digit and wait for a clear yes in the caller's
  next message. Asking the caller to say it again is not a read-back. Set confirmed=true only after that yes.
- Never promise a specific callback time. Never make offers, discounts or promotions.
- Call end_call only after the caller has said goodbye or has nothing more to ask, and after you said goodbye."""


def normalize_phone(raw: str | None) -> str | None:
    """E.164, or None if it does not look like a valid number.

    A number with a leading + (or 00) is taken as international and kept as given (phone calls arrive this way,
    including from outside India). Without one, only Indian mobile numbers are accepted, since that is what people
    say aloud or type into the dashboard."""
    text = (raw or "").strip()
    digits = re.sub(r"\D", "", text)
    if text.startswith("+") or text.startswith("00"):
        digits = digits[2:] if text.startswith("00") else digits
        if digits.startswith("91"):
            return f"+{digits}" if re.fullmatch(r"91\d{10}", digits) else None   # India: 10 digits after the country code
        return f"+{digits}" if re.fullmatch(r"[1-9]\d{7,14}", digits) else None
    if len(digits) == 12 and digits.startswith("91"):
        digits = digits[2:]
    if len(digits) == 11 and digits.startswith("0"):
        digits = digits[1:]
    return f"+91{digits}" if re.fullmatch(r"[6-9]\d{9}", digits) else None


def within_hours(settings: dict | None, now: datetime | None = None) -> bool:
    h = (settings or {}).get("business_hours") or DEFAULT_HOURS
    now = (now or datetime.now(IST)).astimezone(IST)
    if now.isoweekday() not in h.get("days", DEFAULT_HOURS["days"]):
        return False
    return h.get("start", "09:00") <= now.strftime("%H:%M") < h.get("end", "19:00")


def describe_hours(settings: dict | None) -> str:
    h = (settings or {}).get("business_hours") or DEFAULT_HOURS
    names = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
    days = sorted(h.get("days", []))
    span = f"{names[days[0] - 1]} to {names[days[-1] - 1]}" if days else "no days"
    return f"{span}, {h.get('start', '09:00')} to {h.get('end', '19:00')} IST"


@dataclass
class CallState:
    tenant_id: str | None = None
    agent_id: str | None = None
    call_id: str | None = None
    caller_number: str | None = None
    settings: dict = field(default_factory=dict)
    handoff_requested: bool = False
    callback_booked: bool = False
    ended: bool = False
    tool_log: list = field(default_factory=list)   # names and outcomes only: arguments can hold personal data

    def outcome(self, had_conversation: bool) -> str:
        if self.callback_booked:
            return "callback"
        if self.handoff_requested:
            return "handed_off"
        return "resolved" if had_conversation else "dropped"


class Backend:
    """Where tool results are stored. The base class does nothing (used when no database is configured)."""

    async def record_handoff(self, state: CallState, reason: str, outcome: str) -> None: ...
    async def create_callback(self, state: CallState, phone: str, when: str, reason: str) -> None: ...


class RecordingBackend(Backend):
    """For test conversations: keeps everything in memory so a test can assert on it."""

    def __init__(self):
        self.handoffs: list[dict] = []
        self.callbacks: list[dict] = []

    async def record_handoff(self, state, reason, outcome):
        self.handoffs.append({"reason": reason, "outcome": outcome})

    async def create_callback(self, state, phone, when, reason):
        self.callbacks.append({"phone": phone, "when": when, "reason": reason})


def builtin_tools(state: CallState, backend: Backend) -> list:
    def logged(name: str, ok: bool, t0: float, **extra):
        state.tool_log.append({"tool": name, "ok": ok, "ms": int((time.perf_counter() - t0) * 1000), **extra})

    @function_tool
    async def request_human(context: RunContext, reason: str) -> str:
        """Use when the caller wants to talk to a person, or you cannot help, or the matter is serious.

        Args:
            reason: One short sentence in English saying why a person is needed.
        """
        t0 = time.perf_counter()
        open_now = within_hours(state.settings)
        state.handoff_requested = True
        await backend.record_handoff(state, reason, "callback_requested" if open_now else "after_hours")
        logged("request_human", True, t0, in_hours=open_now)
        known = f" The caller is calling from {state.caller_number}; ask if the team may call back on this number." if state.caller_number else " Ask for the number to call back on."
        if open_now:
            return ("No person can join this call right now. Say a team member will call them back soon." + known +
                    " When they agree, read the number back and use schedule_callback once they say yes.")
        return (f"The team is not available now (they work {describe_hours(state.settings)}). Say so kindly, say a team member "
                "will call back when they are in." + known + " When they agree, read the number back and use schedule_callback once they say yes.")

    @function_tool
    async def schedule_callback(context: RunContext, phone: str, confirmed: bool, preferred_time: str = "", reason: str = "") -> str:
        """Book a callback from the team. Only after the caller confirmed the phone number.

        Args:
            phone: The 10-digit mobile number.
            confirmed: True ONLY if you already read this number back to the caller digit by digit and their latest
                message was a clear yes. Otherwise False.
            preferred_time: When the caller prefers to be called, in their words, or empty.
            reason: One short sentence in English about what the call is for.
        """
        t0 = time.perf_counter()
        if not confirmed:
            logged("schedule_callback", False, t0, problem="not_confirmed")
            return "Not booked yet. Read the number back to the caller digit by digit, ask if it is right, and call this again with confirmed=true only after they say yes."
        e164 = normalize_phone(phone)
        if not e164:
            logged("schedule_callback", False, t0, problem="invalid_number")
            return "That is not a valid 10-digit mobile number. Ask the caller to say it again, digit by digit."
        await backend.create_callback(state, e164, preferred_time.strip()[:80], reason.strip()[:200])
        state.callback_booked = True
        logged("schedule_callback", True, t0)
        pref = f" You may say only that you noted their preference ({preferred_time.strip()}). Never say the team WILL call at that time, tomorrow or on any day." if preferred_time.strip() else ""
        return ("The callback is booked. Tell the caller the team will call them back." + pref +
                " Do not promise a time. Ask if there is anything else.")

    @function_tool
    async def end_call(context: RunContext) -> str:
        """End the call. Use only after saying goodbye."""
        t0 = time.perf_counter()
        state.ended = True
        logged("end_call", True, t0)
        try:
            speech = context.session.current_speech
            if speech is not None:
                await speech.wait_for_playout()
            context.session.shutdown()
        except Exception as e:  # text-mode tests have no speech to wait for
            log.debug("end_call: %s", e)
        return "Call ended."

    return [request_human, schedule_callback, end_call]
