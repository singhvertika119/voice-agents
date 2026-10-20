"""Runs one test conversation: the real agent (same prompt, knowledge, tools, model chain) against a simulated
caller, in text. Speech recognition, voice and turn detection are not part of a text test (see D-048)."""
from __future__ import annotations

import time

from livekit.agents import AgentSession, MetricsCollectedEvent, metrics
from livekit.agents.voice.run_result import ChatMessageEvent, FunctionCallEvent

from agent_worker.config import AgentConfig
from agent_worker.knowledge import KnowledgeBase
from agent_worker.providers import build_llm
from agent_worker.tools import CallState, RecordingBackend, builtin_tools
from agent_worker.voice_agent import VoiceAgent

from .caller import END, SimulatedCaller


async def run_conversation(cfg: AgentConfig, kb: KnowledgeBase, scenario: dict, settings: dict | None = None,
                           memory_block: str = "") -> dict:
    backend = RecordingBackend()
    caller_phone = (scenario.get("caller_knows") or {}).get("phone")
    state = CallState(settings=settings or {}, caller_number=caller_phone)
    agent = VoiceAgent(cfg, kb, tools=builtin_tools(state, backend), memory_block=memory_block)
    session = AgentSession(llm=build_llm(cfg))
    ttft: list[float] = []

    @session.on("metrics_collected")
    def _m(ev: MetricsCollectedEvent):
        if isinstance(ev.metrics, metrics.LLMMetrics) and ev.metrics.ttft and ev.metrics.ttft > 0:
            ttft.append(ev.metrics.ttft)

    transcript = [{"speaker": "agent", "text": cfg.greeting.strip(), "greeting": True}]
    tool_calls: list[dict] = []
    reply_ms: list[int] = []
    error = None
    await session.start(agent)
    ctx = agent.chat_ctx.copy()
    ctx.add_message(role="assistant", content=cfg.greeting.strip())
    await agent.update_chat_ctx(ctx)

    caller = SimulatedCaller(scenario)
    line = await caller.next_line(None)
    try:
        for _ in range(int(scenario.get("max_turns", 8))):
            if line == END or state.ended:
                break
            transcript.append({"speaker": "caller", "text": line})
            n_ttft, n_ret = len(ttft), len(kb.retrieval_ms)
            extra = await agent.turn_context_additions(line)  # what a live call does in on_user_turn_completed
            if extra:
                c2 = agent.chat_ctx.copy()
                for role, text in extra:
                    c2.add_message(role=role, content=text)
                await agent.update_chat_ctx(c2)
            t0 = time.perf_counter()
            result = await session.run(user_input=line)
            wall = time.perf_counter() - t0
            said, turn_tools = [], []
            for ev in result.events:
                if isinstance(ev, ChatMessageEvent) and ev.item.role == "assistant" and ev.item.text_content:
                    said.append(ev.item.text_content.strip())
                elif isinstance(ev, FunctionCallEvent):
                    tool_calls.append({"name": ev.item.name, "arguments": ev.item.arguments})
                    turn_tools.append(ev.item.name)
            reply = " ".join(said)
            transcript.append({"speaker": "agent", "text": reply, "tools": turn_tools})
            # Time to first word in a live call is about: (first LLM token) + (document search, if any).
            first = ttft[n_ttft] if len(ttft) > n_ttft else wall
            reply_ms.append(int((first + sum(kb.retrieval_ms[n_ret:]) / 1000) * 1000))
            if caller.finished:
                break
            line = await caller.next_line(reply)
    except Exception as e:  # a provider failure is a test result, not a crash of the whole run
        error = f"{type(e).__name__}: {e}"
    finally:
        try:
            await session.aclose()
        except Exception:
            pass
    return {"transcript": transcript, "tool_calls": tool_calls, "reply_ms": reply_ms, "error": error,
            "backend": {"handoffs": backend.handoffs, "callbacks": backend.callbacks}, "state_outcome": state.outcome(True)}
