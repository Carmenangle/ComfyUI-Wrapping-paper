from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import TypedDict


@dataclass(frozen=True)
class ModelConfig:
    base_url: str = ""
    api_key: str = ""
    model: str = ""


@dataclass
class RunContext:
    thread_id: str
    message: str
    images: list[str] = field(default_factory=list)
    chat: ModelConfig = field(default_factory=ModelConfig)
    generation: ModelConfig = field(default_factory=ModelConfig)
    embedding: ModelConfig = field(default_factory=ModelConfig)
    size: str = "1024x1024"
    output_dir: str = ""
    repo_id: str = ""
    message_id: str = ""
    proxy_url: str = ""
    route_model: str = ""
    style_template: str = ""
    agent_id: str = ""
    cancel_event: threading.Event = field(default_factory=threading.Event, compare=False)
    agent_cfg: dict | None = field(default=None, compare=False)
    history: list[dict] = field(default_factory=list, compare=False)
    skill_frags: list[str] = field(default_factory=list, compare=False)
    has_mcp: bool = False

    def _legacy(self) -> dict:
        return {
            "thread_id": self.thread_id, "repo_id": self.repo_id or self.thread_id,
            "chat_base": self.chat.base_url, "chat_key": self.chat.api_key, "chat_model": self.chat.model,
            "gen_base": self.generation.base_url, "gen_key": self.generation.api_key, "gen_model": self.generation.model,
            "embed_base": self.embedding.base_url, "embed_key": self.embedding.api_key, "embed_model": self.embedding.model,
            "size": self.size, "output_dir": self.output_dir, "proxy": self.proxy_url,
            "route_model": self.route_model, "style_template": self.style_template,
            "agent_id": self.agent_id, "cancel_event": self.cancel_event,
            "agent_cfg": self.agent_cfg, "history": self.history,
            "skill_frags": self.skill_frags, "has_mcp": self.has_mcp,
        }

    def __getitem__(self, key: str):
        return self._legacy()[key]

    def get(self, key: str, default=None):
        return self._legacy().get(key, default)


class AgentEvent(TypedDict, total=False):
    trace: str
    delta: str
    image: str
    id: str
    insp: dict
    interrupted: bool
    error: str
    done: bool
