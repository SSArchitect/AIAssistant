from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Optional

from pydantic import BaseModel, Field


class LLMMessage(BaseModel):
    role: str  # "system", "user", "assistant", "tool"
    content: str | list[dict[str, Any]]
    tool_call_id: Optional[str] = None
    tool_calls: Optional[list[dict[str, Any]]] = None


class ToolDefinition(BaseModel):
    name: str
    description: str
    parameters: dict[str, Any]  # JSON Schema


class PromptCacheOptions(BaseModel):
    enabled: bool = True
    key: str | None = None
    cache_system_prompt: bool = True
    cache_tools: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class ToolCall(BaseModel):
    id: str
    name: str
    arguments: dict[str, Any]


class LLMResponse(BaseModel):
    content: str = ""
    tool_calls: list[ToolCall] = []
    model: str = ""
    usage: dict[str, int] = {}


class RateLimitError(Exception):
    """Raised when a provider returns a rate limit / quota exceeded error."""

    def __init__(self, provider: str, message: str, retry_after: float | None = None):
        self.provider = provider
        self.retry_after = retry_after
        super().__init__(message)


class LLMProvider(ABC):
    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
    ) -> LLMResponse:
        ...

    @abstractmethod
    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
    ) -> AsyncIterator[str]:
        ...
