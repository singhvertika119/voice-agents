"""Generic voice agent worker. The agent identity comes from the room name (dashboard test panel, later phone
dispatch rules) or from config (AGENT_ID env, local YAML).

    uv run python -m agent_worker.agent console     # talk via local mic/speaker
    uv run python -m agent_worker.agent dev         # LiveKit Cloud; test from the dashboard or the Agents Playground
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import time
import uuid
from datetime import datetime, timezone

from dotenv import load_dotenv
from livekit.agents import AgentSession, JobContext, JobProcess, MetricsCollectedEvent, WorkerOptions, cli, llm
from livekit.plugins import silero

try:  # imported at the top on purpose: `download-files` only fetches models for plugins that have been imported (D-077)
    from livekit.plugins.turn_detector.multilingual import MultilingualModel
except Exception:  # package missing: the agent falls back to voice-activity endpointing
    MultilingualModel = None

from . import db, postcall, workspace
from .call_metrics import CallMetricsLog
from .config import REPO_ROOT, AgentConfig, ensure_disclosure, from_dict, load_agent
from .custom_tools import load_custom_tools
from .knowledge import KnowledgeBase, load_knowledge
from .pii import redact
from .providers import build_stack, probe_providers
from .recording import CallRecorder
from .tools import CallState, RecordingBackend, builtin_tools, normalize_phone
from .voice_agent import VoiceAgent, build_instructions

load_dotenv(REPO_ROOT / ".env")
log = logging.getLogger("agent")

CONSENT_NOTICE_VERSION = "2026-10-v1"   # bump when the wording of the disclosure changes
MSG_FULL = "Namaste. Abhi hamari saari lines vyast hain. Kripya thodi der baad dobara call karein. Dhanyavaad."
MSG_OFF = "Namaste. Yeh service abhi uplabdh nahi hai. Kripya baad mein call karein. Dhanyavaad."
MSG_DEGRADED = ("Namaste. Hamare system mein abhi dikkat hai, isliye main sawalon ke jawab nahi de pa rahi. "
                "Kya main aapke liye callback book kar doon?")
DEGRADED_RULES = ("\n\nThe system is having a problem right now. You cannot answer questions about the business. Apologise briefly, "
                  "offer to book a callback, and if the caller agrees use schedule_callback (read the number back and wait for a yes). "
                  "Then say goodbye and use end_call.")


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


def _turn_detector(cfg: AgentConfig):
    if cfg.turn_detection != "multilingual":
        return None
    try:
        if MultilingualModel is None:
            raise RuntimeError("turn-detector package not installed")
        return MultilingualModel()
    except Exception as e:  # model files not downloaded: fall back to VAD-only endpointing
        log.warning("turn detector unavailable (%s); using VAD endpointing", e)
        return None


async def _speak_and_hang_up(session: AgentSession, text: str) -> None:
    handle = session.say(text, allow_interruptions=False)
    try:
        await handle.wait_for_playout()
    finally:
        session.shutdown()


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
    cfg.greeting = ensure_disclosure(cfg.greeting)

    await ctx.connect()
    participant = await ctx.wait_for_participant()
    caller_number = normalize_phone(participant.attributes.get("caller_number") or participant.attributes.get("sip.phoneNumber"))

    settings = await workspace.get_settings(tenant_id) if tenant_id else dict(workspace.DEFAULT_SETTINGS)
    mode = "normal"
    if tenant_id:
        if not await workspace.agent_enabled(agent_ref):
            mode = "disabled"
        elif await workspace.degraded_mode():
            mode = "degraded"
    consent = {"notice": "ai_disclosure_and_recording_notice", "version": CONSENT_NOTICE_VERSION,
               "at": datetime.now(timezone.utc).isoformat(), "recording_stored": bool(settings.get("record_calls", True)), "memory": bool(settings.get("memory_enabled"))}
    if tenant_id:
        call_row = await db.start_call(tenant_id, agent_ref, version, ctx.room.name, caller_number, consent)
        if mode == "normal" and await workspace.active_calls(tenant_id, call_row) >= int(settings["max_concurrent_calls"]):
            mode = "full"

    contact_id, memory_block = (None, "")
    if tenant_id and caller_number and mode == "normal" and settings.get("memory_enabled", True):
        contact_id = await workspace.ensure_contact(tenant_id, caller_number)
        contact_id, memory_block = await workspace.load_memory(tenant_id, caller_number, agent_ref, settings)

    state = CallState(tenant_id=tenant_id, agent_id=agent_ref, call_id=call_row, caller_number=caller_number, settings=settings)
    kb = await load_knowledge(cfg.knowledge_sources, tenant_id) if tenant_id and mode == "normal" else KnowledgeBase()
    tools = builtin_tools(state, workspace.DbBackend() if tenant_id else RecordingBackend())
    if tenant_id and mode == "normal":
        tools += await load_custom_tools(tenant_id, list((cfg.__dict__.get("tool_ids")) or []), state)
    extra_rules = DEGRADED_RULES if mode == "degraded" else ""
    greeting = {"normal": cfg.greeting.strip(), "degraded": MSG_DEGRADED, "full": MSG_FULL, "disabled": MSG_OFF}[mode]

    await probe_providers()
    stack = build_stack(cfg)
    for part in stack.values():  # open provider connections now, not on the first caller turn
        try:
            part.prewarm()
        except Exception as e:
            log.warning("prewarm failed: %s", e)
    session = AgentSession(vad=ctx.proc.userdata["vad"], turn_detection=_turn_detector(cfg), min_endpointing_delay=0.3, **stack)
    agent = VoiceAgent(cfg, kb, tools=tools, memory_block=memory_block, extra_rules=extra_rules)
    want_recording = bool(tenant_id and mode == "normal" and settings.get("record_calls", True))
    recorder = CallRecorder(session, REPO_ROOT / "logs" / "recordings", f"{cfg.id[:12]}-{uuid.uuid4().hex[:8]}") if want_recording else None

    call_id = f"{cfg.id[:12]}-{uuid.uuid4().hex[:8]}"
    mlog = CallMetricsLog(REPO_ROOT / "logs", call_id, cfg.id)
    mlog._write({"event": "mode", "mode": mode, "knowledge_mode": kb.mode, "memory": bool(memory_block), "caller": bool(caller_number)})
    t_start, turns, tasks = time.time(), [], set()

    def _watch(kind: str):
        def handler(ev):
            who = type(getattr(ev, kind, None)).__module__.split(".")[-2:] if getattr(ev, kind, None) else "?"
            mlog._write({"event": "provider_available" if ev.available else "provider_unavailable", "kind": kind, "provider": ".".join(who)})
            log.warning("%s provider %s is now %s", kind, ".".join(who), "available" if ev.available else "UNAVAILABLE (backup in use)")
        return handler

    for kind, name in (("llm", "llm_availability_changed"), ("stt", "stt_availability_changed"), ("tts", "tts_availability_changed")):
        part = stack.get(kind)
        if hasattr(part, "on"):
            try:
                part.on(name, _watch(kind))
            except Exception:
                pass

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
            # Identity numbers are removed before anything is stored (D-052).
            turn = {"seq": len(turns), "speaker": "caller" if item.role == "user" else "agent", "text": redact(text),
                    "at_ms": int((time.time() - t_start) * 1000), "interrupted": bool(getattr(item, "interrupted", False))}
            turns.append(turn)
            if tenant_id:
                tasks.add(t := asyncio.create_task(db.add_turn(call_row, tenant_id, turn)))
                t.add_done_callback(tasks.discard)

    async def _finish():
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        mlog.close()
        log.info("call %s cost ~$%.5f (list prices)", call_id, mlog.cost_usd())
        conversation = [t for t in turns if t["seq"] > 0 or t["speaker"] == "caller"]   # skip the fixed greeting for summaries
        outcome = "dropped" if mode in ("full", "disabled") else state.outcome(any(t["speaker"] == "caller" for t in turns))
        fields = {"ended_at": datetime.now(timezone.utc).isoformat(), "duration_s": round(time.time() - t_start, 1),
                  "avg_reply_ms": mlog.avg_reply_ms(), "cost_usd": round(mlog.cost_usd(), 6),
                  "cost_breakdown": {**mlog.totals, "retrieval_ms": kb.retrieval_ms, "knowledge_mode": kb.mode, "mode": mode},
                  "language": cfg.language, "outcome": outcome, "tool_calls": state.tool_log, "contact_id": contact_id}
        if tenant_id and mode == "normal" and any(t["speaker"] == "caller" for t in turns):
            use_memory = bool(contact_id) and settings.get("memory_enabled", True)
            prior, facts = await workspace.previous_summary(contact_id, agent_ref) if use_memory else ("", {})
            s = await postcall.summarize(conversation, prior, facts, state.tool_log, with_memory=use_memory)
            if s:
                fields["summary"] = s.get("summary")
                fields["structured"] = {k: s.get(k) for k in ("intent", "outcome", "commitments", "open_items", "language", "name")}
                # Older models sometimes leave rolling_summary out. Never lose the call: fall back to the previous
                # memory plus this call's summary, trimmed (found when a returning caller was not remembered).
                rolling = s.get("rolling_summary") or " ".join(x for x in (prior, s.get("summary")) if x)[-1800:]
                if use_memory and rolling:
                    await workspace.save_memory(tenant_id, agent_ref, contact_id, rolling, s.get("facts") or {},
                                                [str(x) for x in (s.get("open_items") or [])], {"hindi": "hi", "english": "en"}.get(s.get("language") or "", None))
        if recorder:
            stored = await recorder.finish(tenant_id, call_row)
            if stored:
                fields["recording_path"], fields["recording_seconds"] = stored
            fields["consent"] = {**consent, "recording_stored": bool(stored)}
        await db.finish_call(call_row, tenant_id, fields, [])

    async def _warm_llm():
        """The first real LLM request is slow (new connection, empty prompt cache). Send the agent's actual
        prompt once, now, while the greeting plays, so the caller's first question does not pay for it."""
        try:
            warm = llm.ChatContext()
            warm.add_message(role="system", content=build_instructions(cfg, kb, memory_block, extra_rules))
            warm.add_message(role="user", content="Hello")
            async with stack["llm"].chat(chat_ctx=warm) as stream:
                async for _ in stream:
                    break
        except Exception as e:
            log.warning("LLM warm-up failed: %s", e)

    if mode == "normal":
        warm_task = asyncio.create_task(_warm_llm())
        tasks.add(warm_task)
        warm_task.add_done_callback(tasks.discard)
    ctx.add_shutdown_callback(_finish)
    await session.start(agent=agent, room=ctx.room)
    if recorder and await recorder.attach() and recorder.started_at:
        t_start = recorder.started_at   # transcript times now line up with the audio, so a click on a line can seek to it
    if mode in ("full", "disabled"):
        await _speak_and_hang_up(session, greeting)
        return
    await session.say(greeting, allow_interruptions=False)


if __name__ == "__main__":
    # A named worker only receives rooms that ask for it by name (the dashboard test panel does). An unnamed worker
    # is sent EVERY new room in the LiveKit project, including other apps' rooms (D-060).
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm, agent_name=os.getenv("AGENT_NAME", "voice-platform")))
