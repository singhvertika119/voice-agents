"""The agent itself, shared by live calls and test conversations so a test exercises exactly what a caller meets."""
from __future__ import annotations

import re
from collections.abc import AsyncIterable

from livekit.agents import Agent

from .config import AgentConfig
from .language import language_hint, set_tts_language, tts_language
from .knowledge import KnowledgeBase, make_lookup_tool
from .normalize import normalize_for_speech
from .tools import CONVERSATION_RULES, TOOL_RULES

_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


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

    async def turn_context_additions(self, caller_text: str) -> list[tuple[str, str]]:
        """Extra (role, text) messages for this turn: a language reminder and, for large knowledge, passages.
        Shared by live calls and text tests so both behave the same."""
        extra: list[tuple[str, str]] = []
        hint = language_hint(caller_text)
        if hint:
            extra.append(("system", hint))
        found = await self.kb.retrieve(caller_text)
        if found is not None:
            if found:
                msg = "Passages from the business's documents that may answer the caller's last question:\n" + found
            else:
                msg = "No passage in the documents matched the caller's last question. Say you do not have that information."
            extra.append(("assistant", msg))
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
        self.speak_in(tts_language(new_message.text_content or "", self.voice_language))
        for role, text in await self.turn_context_additions(new_message.text_content or ""):
            turn_ctx.add_message(role=role, content=text)

    async def tts_node(self, text: AsyncIterable[str], model_settings) -> AsyncIterable:
        async def spoken() -> AsyncIterable[str]:
            buf = ""
            async for chunk in text:  # normalize per sentence so digit strings are never split mid-number
                buf += chunk
                parts = _SENTENCE_END.split(buf)
                for s in parts[:-1]:
                    yield normalize_for_speech(s) + " "
                buf = parts[-1]
            if buf.strip():
                yield normalize_for_speech(buf)

        return Agent.default.tts_node(self, spoken(), model_settings)
