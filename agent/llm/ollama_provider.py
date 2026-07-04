from __future__ import annotations
import json
from typing import AsyncIterator

import ollama

from .base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    PromptCacheOptions,
    ToolCall,
    ToolDefinition,
)
from .multimodal import content_to_plain_text


class OllamaProvider(LLMProvider):
    def __init__(self, model: str = "llama3", base_url: str = "http://localhost:11434"):
        self.client = ollama.AsyncClient(host=base_url)
        self.model = model

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict]:
        converted = []
        for msg in messages:
            content = content_to_plain_text(msg.content)
            converted.append({"role": msg.role, "content": content})
        return converted

    def _convert_tools(self, tools: list[ToolDefinition] | None) -> list[dict] | None:
        if not tools:
            return None
        return [
            {
                "type": "function",
                "function": {
                    "name": t.name,
                    "description": t.description,
                    "parameters": t.parameters,
                },
            }
            for t in tools
        ]

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
    ) -> LLMResponse:
        converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "messages": converted,
            "options": {"temperature": temperature},
        }
        ollama_tools = self._convert_tools(tools)
        if ollama_tools:
            kwargs["tools"] = ollama_tools

        response = await self.client.chat(**kwargs)

        tool_calls = []
        msg = response.message
        if msg and msg.tool_calls:
            for i, tc in enumerate(msg.tool_calls):
                func = tc.function
                tool_calls.append(
                    ToolCall(
                        id=f"ollama_{i}",
                        name=func.name if func else "",
                        arguments=func.arguments if func else {},
                    )
                )

        return LLMResponse(
            content=msg.content if msg else "",
            tool_calls=tool_calls,
            model=self.model,
            usage={
                "input": getattr(response, "prompt_eval_count", 0) or 0,
                "output": getattr(response, "eval_count", 0) or 0,
            },
        )

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
    ) -> AsyncIterator[str]:
        converted = self._convert_messages(messages)
        response = await self.client.chat(
            model=self.model,
            messages=converted,
            stream=True,
            options={"temperature": temperature},
        )
        async for chunk in response:
            msg = chunk.message if hasattr(chunk, "message") else None
            content = msg.content if msg else ""
            if content:
                yield content
