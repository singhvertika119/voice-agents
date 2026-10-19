"""Generic voice agent worker. The agent identity comes from config (AGENT_ID env, later dispatch metadata).

    uv run python -m agent_worker.agent console     # talk via local mic/speaker
    uv run python -m agent_worker.agent dev         # LiveKit Cloud; test from the Agents Playground
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone
from collections.abc import AsyncIterable

from dotenv import load_dotenv
from livekit.agents import Agent, AgentSession, llm, JobContext, JobProcess, MetricsCollectedEvent, WorkerOptions, cli
from livekit.plugins import silero

from . import db
from .call_metrics import CallMetricsLog
from .config import REPO_ROOT, AgentConfig, from_dict, load_agent
from .knowledge import KnowledgeBase, load_knowledge, make_lookup_tool
from .normalize import normalize_for_speech
from .providers import build_stack, probe_providers

load_dotenv(REPO_ROOT / ".env")
log = logging.getLogger("agent")
_SENTENCE_END = re.compile(r"(?<=[.!?।])\s+")


class VoiceAgent(Agent):
    def __init__(self, cfg: AgentConfig, kb: KnowledgeBase):
        super().__init__(instructions=cfg.system_prompt + kb.prompt_addition(),
                         tools=[make_lookup_tool(kb)] if kb.tables else [])
        self.kb = kb

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        """Large knowledge bases: search with the caller's words and hand the passages to the model."""
        found = await self.kb.retrieve(new_message.text_content or "")
        if found is None:
            return
        turn_ctx.add_message(
            role="assistant",
            content=("Passages from the business's documents that may answer the caller's last question:\n" + found)
            if found else "No passage in the documents matched the caller's last question. Say you do not have that information.",
        )

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


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


def _turn_detector(cfg: AgentConfig):
    if cfg.turn_detection != "multilingual":
        return None
    try:
        from livekit.plugins.turn_detector.multilingual import MultilingualModel
        return MultilingualModel()
    except Exception as e:  # model files not downloaded: fall back to VAD-only endpointing
        log.warning("turn detector unavailable (%s); using VAD endpointing", e)
        return None


async def entrypoint(ctx: JobContext):
    tenant_id = version = call_row = None
    room = db.parse_room(ctx.room.name)   # dashboard test panel: room name carries the agent id
    agent_ref = room[1] if room else os.getenv("AGENT_ID")
    if room or db.is_agent_uuid(agent_ref):  # platform mode: config comes from the database
        pub = await (db.fetch_latest(agent_ref) if room and room[0] == "draft" else db.fetch_published(agent_ref))
        cfg = from_dict(agent_ref, pub["agent"]["name"], pub["config"])
        tenant_id, version = pub["agent"]["tenant_id"], pub["version"]
    else:                                    # local mode: YAML file
        cfg = load_agent(agent_ref)
    kb = await load_knowledge(cfg.knowledge_sources, tenant_id) if tenant_id else KnowledgeBase()
    await ctx.connect()
    if tenant_id:
        call_row = await db.start_call(tenant_id, agent_ref, version, ctx.room.name)
    await probe_providers()
    stack = build_stack(cfg)
    for part in stack.values():  # open provider connections now, not on the first caller turn
        try:
            part.prewarm()
        except Exception as e:
            log.warning("prewarm failed: %s", e)
    session = AgentSession(vad=ctx.proc.userdata["vad"], turn_detection=_turn_detector(cfg),
                           min_endpointing_delay=0.3, **stack)

    call_id = f"{cfg.id[:12]}-{uuid.uuid4().hex[:8]}"
    mlog = CallMetricsLog(REPO_ROOT / "logs", call_id, cfg.id)
    t_start, turns, tasks = time.time(), [], set()

    @session.on("metrics_collected")
    def _on_metrics(ev: MetricsCollectedEvent):
        mlog.on_metrics(ev.metrics)

    @session.on("user_input_transcribed")
    def _on_words(ev):
        kb.prefetch(ev.transcript)

    @session.on("conversation_item_added")
    def _on_item(ev):
        item = ev.item
        text = getattr(item, "text_content", None)
        if getattr(item, "role", None) in ("user", "assistant") and text:
            turn = {"seq": len(turns), "speaker": "caller" if item.role == "user" else "agent",
                    "text": text, "at_ms": int((time.time() - t_start) * 1000),
                    "interrupted": bool(getattr(item, "interrupted", False))}
            turns.append(turn)
            if tenant_id:
                tasks.add(t := asyncio.create_task(db.add_turn(call_row, tenant_id, turn)))
                t.add_done_callback(tasks.discard)

    async def _finish():
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        mlog.close()
        log.info("call %s cost ~$%.5f (list prices)", call_id, mlog.cost_usd())
        await db.finish_call(call_row, tenant_id, {
            "ended_at": datetime.now(timezone.utc).isoformat(), "duration_s": round(time.time() - t_start, 1),
            "avg_reply_ms": mlog.avg_reply_ms(), "cost_usd": round(mlog.cost_usd(), 6),
            "cost_breakdown": {**mlog.totals, "retrieval_ms": kb.retrieval_ms, "knowledge_mode": kb.mode}, "language": cfg.language,
            # TODO: derive outcome from handoff/tool events; until then a completed call counts as resolved.
            "outcome": "resolved" if turns else "dropped"}, [])

    async def _warm_llm():
        """The first real LLM request is slow (new connection, empty prompt cache). Send the agent's actual
        prompt once, now, while the greeting plays, so the caller's first question does not pay for it."""
        try:
            warm = llm.ChatContext()
            warm.add_message(role="system", content=cfg.system_prompt + kb.prompt_addition())
            warm.add_message(role="user", content="Hello")
            async with stack["llm"].chat(chat_ctx=warm) as stream:
                async for _ in stream:
                    break
        except Exception as e:
            log.warning("LLM warm-up failed: %s", e)

    warm_task = asyncio.create_task(_warm_llm())
    tasks.add(warm_task)
    warm_task.add_done_callback(tasks.discard)
    ctx.add_shutdown_callback(_finish)
    await session.start(agent=VoiceAgent(cfg, kb), room=ctx.room)
    await session.say(cfg.greeting.strip(), allow_interruptions=False)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
