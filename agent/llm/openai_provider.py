from __future__ import annotations
import json
from typing import AsyncIterator

import openai

from .base import LLMMessage, LLMProvider, LLMResponse, RateLimitError, ToolCall, ToolDefinition
from .multimodal import content_to_plain_text, normalize_content_parts


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        provider_label: str = "OpenAI",
    ):
        api_key = (api_key or "").strip()
        if not api_key:
            raise ValueError(f"{provider_label} API key not configured")

        kwargs = {"api_key": api_key, "max_retries": 0}
        if base_url:
            kwargs["base_url"] = base_url
        if timeout_seconds and timeout_seconds > 0:
            kwargs["timeout"] = openai.Timeout(
                timeout_seconds,
                connect=timeout_seconds,
                read=timeout_seconds,
                write=timeout_seconds,
                pool=timeout_seconds,
            )
        self.client = openai.AsyncOpenAI(**kwargs)
        self.model = model
        self.provider_name = "openai"

    def _convert_messages(self, messages: list[LLMMessage]) -> list[dict]:
        converted = []
        for msg in messages:
            if msg.role == "tool":
                converted.append({
                    "role": "tool",
                    "tool_call_id": msg.tool_call_id,
                    "content": content_to_plain_text(msg.content),
                })
            elif msg.role == "assistant" and msg.tool_calls:
                entry = {
                    "role": "assistant",
                    "content": content_to_plain_text(msg.content),
                }
                entry["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": "function",
                        "function": {
                            "name": tc["name"],
                            "arguments": json.dumps(tc["arguments"]),
                        },
                    }
                    for tc in msg.tool_calls
                ]
                converted.append(entry)
            else:
                content = msg.content if isinstance(msg.content, str) else normalize_content_parts(msg.content)
                converted.append({
                    "role": msg.role,
                    "content": content,
                })
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

    def _extra_chat_kwargs(self) -> dict:
        return {}

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "messages": converted,
            "temperature": temperature,
        }
        kwargs.update(self._extra_chat_kwargs())
        openai_tools = self._convert_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools

        try:
            response = await self.client.chat.completions.create(**kwargs)
        except openai.RateLimitError as e:
            provider_name = self.provider_name
            if self.client.base_url and "deepseek" in str(self.client.base_url):
                provider_name = "deepseek"
            raise RateLimitError(
                provider=provider_name,
                message=f"{provider_name.title()} API rate limit exceeded. Please wait a moment and try again.",
            ) from e

        choice = response.choices[0]
        message = choice.message

        tool_calls = []
        if message.tool_calls:
            for tc in message.tool_calls:
                tool_calls.append(
                    ToolCall(
                        id=tc.id,
                        name=tc.function.name,
                        arguments=json.loads(tc.function.arguments),
                    )
                )

        return LLMResponse(
            content=message.content or "",
            tool_calls=tool_calls,
            model=response.model,
            usage={
                "input": response.usage.prompt_tokens if response.usage else 0,
                "output": response.usage.completion_tokens if response.usage else 0,
            },
        )

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "messages": converted,
            "temperature": temperature,
            "stream": True,
        }
        kwargs.update(self._extra_chat_kwargs())
        openai_tools = self._convert_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools

        stream = await self.client.chat.completions.create(**kwargs)
        async for chunk in stream:
            if chunk.choices and chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
