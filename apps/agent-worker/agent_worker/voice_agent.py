"""The agent itself, shared by live calls and test conversations so a test exercises exactly what a caller meets."""
from __future__ import annotations

import time
from collections.abc import AsyncIterable

from livekit.agents import Agent, llm

from .config import AgentConfig
from .language import language_hint, set_tts_language, tts_language
from .knowledge import KnowledgeBase, is_acknowledgement, make_lookup_tool
from .normalize import normalize_for_speech
from .speech_chunks import ClauseSplitter
from .tools import CONVERSATION_RULES, TOOL_RULES


def build_instructions(cfg: AgentConfig, kb: KnowledgeBase, memory_block: str = "", extra_rules: str = "") -> str:
    """Static part first (instructions, notes, documents, tool rules) so the provider's prompt cache covers it;
    anything that changes per caller goes last."""
    return cfg.system_prompt + kb.prompt_addition() + TOOL_RULES + extra_rules + CONVERSATION_RULES + (("\n\n" + memory_block) if memory_block else "")


class VoiceAgent(Agent):
    def __init__(self, cfg: AgentConfig, kb: KnowledgeBase, tools: list | None = None, memory_block: str = "",
                 extra_rules: str = ""):
        all_tools = list(tools or []) + ([make_lookup_tool(kb)] if kb.tables else [])
        super().__init__(instructions=build_instructions(cfg, kb, memory_block, extra_rules), tools=all_tools)
        self.kb = kb
        self.voice_language = cfg.language   # what the speech providers were built with; changes with the caller's language
        self._extra: tuple[tuple[str, str], list[tuple[str, str]]] | None = None   # ((message id, text), additions)
        self.on_prepared = None   # set by the call: receives the ms the model waited for hints and search

    async def turn_context_additions(self, caller_text: str) -> list[tuple[str, str]]:
        """Extra (role, text) messages for this turn: a language reminder and, for large knowledge, passages.
        Shared by live calls and text tests so both behave the same."""
        extra: list[tuple[str, str]] = []
        hint = language_hint(caller_text)
        if hint:
            extra.append(("system", hint))
        if is_acknowledgement(caller_text):
            # A general "no closing offers" rule (D-098) was not enough: an "OK" still got "Thank you! If you have any
            # more questions, feel free to ask." An instruction for this turn only is followed (D-112).
            extra.append(("system", "The caller only acknowledged what you said. Reply with one to three words in their "
                                    "language, such as \"Ji.\", \"Sure.\" or \"Theek hai.\". Do not thank them and do "
                                    "not offer more help. If you had asked them something, ask it again briefly instead."))
        found = await self.kb.retrieve(caller_text)
        if found is not None:
            if found:
                msg = "Passages from the business's documents that may answer the caller's last question:\n" + found
            else:
                msg = "No passage in the documents matched the caller's last question. Say you do not have that information."
            # As a system message, not an assistant one: given the contact passage as its own earlier words, the model
            # said "phone number nahi pata" 9 times in 9 while reading the hours from the same passage; as a system
            # message it gave "+91 806 940 9217" 3 times in 3 (D-110).
            extra.append(("system", msg))
        return extra

    def speak_in(self, code: str) -> None:
        """Switch the voice language (no-op if it is already set or there is no live session, as in text tests)."""
        if code == self.voice_language:
            return
        self.voice_language = code
        try:
            set_tts_language(self.session.tts, code)
        except Exception:
            pass

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        # Only the voice language here. The hint and passages are added in llm_node: anything added to turn_ctx here
        # made LiveKit throw away the reply it had started early, so the search and the model ran one after the other
        # after the end-of-turn wait (logs: "preemptive generation invalidated", D-116).
        self.speak_in(tts_language(new_message.text_content or "", self.voice_language))

    async def llm_node(self, chat_ctx, tools, model_settings):
        """Adds this turn's language hint and passages right after the caller's last message, for this model request
        only, as on_user_turn_completed did before. LiveKit runs this early, while it is still deciding whether the
        caller has finished, so the search now overlaps that wait. Kept per caller message: the model is asked again
        after a tool call and must see the same passages."""
        items = chat_ctx.items
        at = next((i for i in range(len(items) - 1, -1, -1)
                   if getattr(items[i], "type", None) == "message" and items[i].role == "user"), None)
        if at is not None:
            msg = items[at]
            key = (msg.id, msg.text_content or "")
            if self._extra is None or self._extra[0] != key:
                t0 = time.perf_counter()
                self._extra = (key, await self.turn_context_additions(key[1]))
                if self.on_prepared:
                    self.on_prepared(round((time.perf_counter() - t0) * 1000))
            if self._extra[1]:
                chat_ctx = chat_ctx.copy()
                for j, (role, text) in enumerate(self._extra[1]):
                    chat_ctx.items.insert(at + 1 + j, llm.ChatMessage(role=role, content=[text], created_at=msg.created_at))
        return Agent.default.llm_node(self, chat_ctx, tools, model_settings)

    async def tts_node(self, text: AsyncIterable[str], model_settings) -> AsyncIterable:
        async def spoken() -> AsyncIterable[str]:
            # Normalized a piece at a time so digit strings are never split mid-number. The first piece may end at a
            # comma, so the voice starts before the first sentence is finished (D-115); later pieces are sentences.
            split = ClauseSplitter()
            buf = ""
            async for chunk in text:
                buf += chunk
                pieces = split(buf)
                if len(pieces) > 1:
                    for p, _, _ in pieces[:-1]:
                        yield normalize_for_speech(p) + " "
                    buf = buf[pieces[-1][1]:]
            if buf.strip():
                yield normalize_for_speech(buf)

        return Agent.default.tts_node(self, spoken(), model_settings)
