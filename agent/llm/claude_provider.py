from __future__ import annotations
from typing import AsyncIterator

import anthropic

from .base import LLMMessage, LLMProvider, LLMResponse, RateLimitError, ToolCall, ToolDefinition
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

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
    ) -> LLMResponse:
        system, converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": converted,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        anthropic_tools = self._convert_tools(tools)
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

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
            usage={
                "input": response.usage.input_tokens,
                "output": response.usage.output_tokens,
            },
        )

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        system, converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "messages": converted,
            "temperature": temperature,
        }
        if system:
            kwargs["system"] = system
        anthropic_tools = self._convert_tools(tools)
        if anthropic_tools:
            kwargs["tools"] = anthropic_tools

        async with self.client.messages.stream(**kwargs) as stream:
            async for text in stream.text_stream:
                yield text
