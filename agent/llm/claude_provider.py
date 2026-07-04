from __future__ import annotations
from typing import AsyncIterator

import anthropic

from .base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    PromptCacheOptions,
    RateLimitError,
    ToolCall,
    ToolDefinition,
)
from .multimodal import content_to_plain_text, data_url_bytes, normalize_content_parts


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-20250514"):
        self.client = anthropic.AsyncAnthropic(api_key=api_key)
        self.model = model

    def _convert_messages(
        self, messages: list[LLMMessage]
    ) -> tuple[str, list[dict]]:
        """Extract system prompt and convert messages to Anthropic format."""
        system = ""
        converted = []

        for msg in messages:
            if msg.role == "system":
                system = content_to_plain_text(msg.content)
                continue

            if msg.role == "tool":
                converted.append({
                    "role": "user",
                    "content": [
                        {
                            "type": "tool_result",
                            "tool_use_id": msg.tool_call_id,
                            "content": content_to_plain_text(msg.content),
                        }
                    ],
                })
            elif msg.role == "assistant" and msg.tool_calls:
                content = []
                if msg.content:
                    text = content_to_plain_text(msg.content)
                    if text:
                        content.append({"type": "text", "text": text})
                for tc in msg.tool_calls:
                    content.append({
                        "type": "tool_use",
                        "id": tc["id"],
                        "name": tc["name"],
                        "input": tc["arguments"],
                    })
                converted.append({"role": "assistant", "content": content})
            else:
                content = msg.content
                if not isinstance(content, str):
                    content = self._convert_content_parts(content)
                converted.append({
                    "role": msg.role,
                    "content": content,
                })

        return system, converted

    def _convert_content_parts(self, content: list[dict]) -> list[dict]:
        parts = []
        for item in normalize_content_parts(content):
            if item["type"] == "text":
                parts.append({"type": "text", "text": item["text"]})
                continue
            image_url = item["image_url"]["url"]
            parsed = data_url_bytes(image_url)
            if parsed:
                mime_type, _ = parsed
                parts.append(
                    {
                        "type": "image",
                        "source": {
                            "type": "base64",
                            "media_type": mime_type,
                            "data": image_url.split(",", 1)[1],
                        },
                    }
                )
            else:
                parts.append({"type": "text", "text": f"[image URL: {image_url}]"})
        return parts

    def _convert_tools(self, tools: list[ToolDefinition] | None) -> list[dict] | None:
        if not tools:
            return None
        return [
            {
                "name": t.name,
                "description": t.description,
                "input_schema": t.parameters,
            }
            for t in tools
        ]

    def _system_payload(
        self,
        system: str,
        cache: PromptCacheOptions | None,
    ) -> str | list[dict]:
        if not system:
            return system
        if not cache or not cache.enabled or not cache.cache_system_prompt:
            return system
        stable_chars = int(cache.metadata.get("stable_prompt_chars") or 0)
        if 0 < stable_chars < len(system):
            stable_text = system[:stable_chars].rstrip()
            dynamic_text = system[stable_chars:].lstrip()
            blocks = [
                {
                    "type": "text",
                    "text": stable_text,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
            if dynamic_text:
                blocks.append({"type": "text", "text": dynamic_text})
            return blocks
        return [
            {
                "type": "text",
                "text": system,
                "cache_control": {"type": "ephemeral"},
            }
        ]

    def _tools_payload(
        self,
        tools: list[dict] | None,
        cache: PromptCacheOptions | None,
    ) -> list[dict] | None:
        if not tools:
            return None
        if not cache or not cache.enabled or not cache.cache_tools:
            return tools
        cached_tools = [dict(tool) for tool in tools]
        cached_tools[-1]["cache_control"] = {"type": "ephemeral"}
        return cached_tools

    def _usage_payload(self, usage) -> dict[str, int]:
        payload = {
            "input": getattr(usage, "input_tokens", 0),
            "output": getattr(usage, "output_tokens", 0),
        }
        cache_read = getattr(usage, "cache_read_input_tokens", None)
        cache_creation = getattr(usage, "cache_creation_input_tokens", None)
        if cache_read is not None:
            payload["input_cached"] = cache_read
        if cache_creation is not None:
            payload["input_cache_creation"] = cache_creation
        return payload

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
    ) -> LLMResponse:
        system, converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": converted,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = self._system_payload(system, cache)
        anthropic_tools = self._convert_tools(tools)
        if anthropic_tools:
            kwargs["tools"] = self._tools_payload(anthropic_tools, cache)

        try:
            response = await self.client.messages.create(**kwargs)
        except anthropic.RateLimitError as e:
            raise RateLimitError(
                provider="claude",
                message="Claude API rate limit exceeded. Please wait a moment and try again.",
            ) from e

        content = ""
        tool_calls = []
        for block in response.content:
            if block.type == "text":
                content += block.text
            elif block.type == "tool_use":
                tool_calls.append(
                    ToolCall(id=block.id, name=block.name, arguments=block.input)
                )

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=response.model,
            usage=self._usage_payload(response.usage),
        )

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
    ) -> AsyncIterator[str]:
        system, converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": converted,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = self._system_payload(system, cache)
        anthropic_tools = self._convert_tools(tools)
        if anthropic_tools:
            kwargs["tools"] = self._tools_payload(anthropic_tools, cache)

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
