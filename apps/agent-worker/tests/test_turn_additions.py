"""Hints and passages are added in llm_node, not on_user_turn_completed, so LiveKit keeps the reply it started early
(D-116). They go right after the caller's message, for that model request only, and are reused after a tool call."""
import asyncio

from livekit.agents import Agent, llm

from agent_worker.config import AgentConfig
from agent_worker.knowledge import KnowledgeBase
from agent_worker.voice_agent import VoiceAgent


class FakeKB(KnowledgeBase):
    searches = 0

    async def retrieve(self, text):
        FakeKB.searches += 1
        return "Office: E-42, Jaipur"


def make_agent():
    cfg = AgentConfig(id="a", name="t", language="en-IN", greeting="Hi", instructions="Be brief.", knowledge="")
    return VoiceAgent(cfg, FakeKB(mode="search"))


def run_node(agent, ctx, monkeypatch):
    seen = {}

    def fake_default(self, chat_ctx, tools, model_settings):
        seen["ctx"] = chat_ctx
        return None

    monkeypatch.setattr(Agent.default, "llm_node", fake_default)
    asyncio.run(agent.llm_node(ctx, [], None))
    return seen["ctx"]


def texts(ctx):
    return [(i.role, i.text_content) for i in ctx.items if getattr(i, "type", None) == "message"]


def test_passages_follow_the_callers_message(monkeypatch):
    agent, ctx = make_agent(), llm.ChatContext()
    ctx.add_message(role="assistant", content="Hi")
    ctx.add_message(role="user", content="Where is your office?")
    out = texts(run_node(agent, ctx, monkeypatch))
    assert out[1] == ("user", "Where is your office?")
    assert out[2][0] == "system" and "English" in out[2][1]   # language hint first
    assert out[3][0] == "system" and "E-42" in out[3][1]      # then the passages
    assert len(texts(ctx)) == 2            # the call's own history is not changed


def test_same_message_is_searched_once(monkeypatch):
    FakeKB.searches = 0
    agent, ctx = make_agent(), llm.ChatContext()
    ctx.add_message(role="user", content="Where is your office?")
    run_node(agent, ctx, monkeypatch)
    ctx.items.append(llm.FunctionCall(call_id="1", name="lookup", arguments="{}"))
    ctx.items.append(llm.FunctionCallOutput(call_id="1", name="lookup", output="ok", is_error=False))
    out = run_node(agent, ctx, monkeypatch)   # the model is asked again after the tool
    assert FakeKB.searches == 1
    assert any("E-42" in (t or "") for _, t in texts(out))


def test_turn_hook_leaves_the_conversation_alone():
    agent, ctx = make_agent(), llm.ChatContext()
    msg = ctx.add_message(role="user", content="Where is your office?")
    before = len(ctx.items)
    asyncio.run(agent.on_user_turn_completed(ctx, msg))
    assert len(ctx.items) == before


def test_reply_timings_come_from_message_metrics():
    import tempfile
    from pathlib import Path
    from agent_worker.call_metrics import CallMetricsLog
    m = CallMetricsLog(Path(tempfile.mkdtemp()), "c", "a")
    m.on_prepared(640)
    m.on_message("user", {"end_of_turn_delay": 0.7, "transcription_delay": 0.35})
    m.on_message("assistant", {"llm_node_ttft": 0.9, "tts_node_ttfb": 0.4, "e2e_latency": 1.6})
    assert m.turn_timings() == [{"wait": 700, "transcript": 350, "search": 640, "first_word": 900, "voice": 400, "total": 1600}]
    assert m.avg_reply_ms() == 1600
