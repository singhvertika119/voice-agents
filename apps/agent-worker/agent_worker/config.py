"""Agent config loading. An agent is data, not code (see docs/decision.md D-006)."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import re

import yaml

REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass
class AgentConfig:
    id: str
    name: str
    language: str
    greeting: str
    instructions: str
    knowledge: str
    voice: dict = field(default_factory=dict)
    stt: dict = field(default_factory=dict)
    llm: dict = field(default_factory=dict)
    turn_detection: str = "vad"
    knowledge_sources: list = field(default_factory=list)
    tool_ids: list = field(default_factory=list)   # custom tools (tools.id), pinned per version

    @property
    def system_prompt(self) -> str:
        # Static prefix first (prompt-cache friendly); per-caller context would be appended after.
        return f"{self.instructions.strip()}\n\nKnowledge:\n{self.knowledge.strip()}"


def from_dict(agent_id: str, name: str, data: dict) -> AgentConfig:
    allowed = {k: v for k, v in data.items() if k in AgentConfig.__dataclass_fields__ and k not in ("id", "name")}
    return AgentConfig(id=agent_id, name=name, **allowed)


def load_agent(agent_id: str | None = None, path: Path | None = None) -> AgentConfig:
    path = path or REPO_ROOT / "agents" / f"{(agent_id or 'sunrise_clinic').replace('-', '_')}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return AgentConfig(**data)


_DISCLOSES_AI = re.compile(r"(?<![A-Za-z])(?:ai|a\.i\.|artificial|assistant|bot|virtual|automated)(?![A-Za-z])|एआई|असिस्टेंट|रोबोट", re.I)


def ensure_disclosure(greeting: str) -> str:
    """Every call must tell the caller they are talking to an AI and that the call may be recorded (PRD FR-11, TRAI).
    If the owner's greeting does not say so, the platform adds the sentence rather than trusting the text."""
    g = greeting.strip()
    if _DISCLOSES_AI.search(g):
        return g
    return "Namaste, main ek AI assistant hoon aur yeh call record ho sakti hai. " + g
