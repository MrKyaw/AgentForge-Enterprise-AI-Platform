"""Provider contracts independent of any vendor SDK."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any

from agentforge.models import Message, TokenUsage, ToolCall, ToolSchema


@dataclass(slots=True)
class CompletionRequest:
    messages: list[Message]
    model: str
    temperature: float = 0.0
    max_tokens: int = 800
    tools: list[ToolSchema] = field(default_factory=list)
    timeout_seconds: float = 30.0


@dataclass(slots=True)
class ProviderResponse:
    content: str
    model: str
    provider: str
    usage: TokenUsage = field(default_factory=TokenUsage)
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: str = "stop"
    raw: dict[str, Any] | None = None


class ModelProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, request: CompletionRequest) -> ProviderResponse:
        """Return a completion or raise ``ProviderError``."""

    @abstractmethod
    def available(self) -> bool:
        """Whether credentials and configuration are present."""

    async def aclose(self) -> None:  # pragma: no cover - optional lifecycle hook
        return None
