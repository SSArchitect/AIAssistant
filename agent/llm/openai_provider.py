from __future__ import annotations
import json
from typing import AsyncIterator

import openai

from .base import (
    LLMMessage,
    LLMProvider,
    LLMResponse,
    LLMStreamChunk,
    PromptCacheOptions,
    RateLimitError,
    ToolCall,
    ToolDefinition,
)
from .multimodal import content_to_plain_text, normalize_content_parts


class OpenAIProvider(LLMProvider):
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o",
        base_url: str | None = None,
        timeout_seconds: float | None = None,
        provider_label: str = "OpenAI",
        max_tokens: int | None = None,
        streaming_enabled: bool = True,
        supports_streaming_tool_calls: bool = False,
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
        self.max_tokens = max_tokens if max_tokens and max_tokens > 0 else None
        self.streaming_enabled = streaming_enabled
        self.supports_streaming_tool_calls = supports_streaming_tool_calls
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

    def _extra_chat_kwargs(self, *, thinking_enabled: bool | None = None) -> dict:
        return {}

    def _supports_prompt_cache_key(self) -> bool:
        if self.provider_name != "openai":
            return False
        base_url = str(getattr(self.client, "base_url", "") or "")
        return not base_url or "api.openai.com" in base_url

    def _apply_cache_options(
        self,
        kwargs: dict,
        cache: PromptCacheOptions | None,
    ) -> None:
        if not cache or not cache.enabled or not cache.key:
            return
        if not self._supports_prompt_cache_key():
            return
        extra_body = dict(kwargs.get("extra_body") or {})
        extra_body["prompt_cache_key"] = cache.key
        kwargs["extra_body"] = extra_body

    def _usage_payload(self, usage) -> dict[str, int]:
        if not usage:
            return {"input": 0, "output": 0}
        payload = {
            "input": usage.prompt_tokens,
            "output": usage.completion_tokens,
        }
        prompt_details = getattr(usage, "prompt_tokens_details", None)
        cached_tokens = getattr(prompt_details, "cached_tokens", None)
        if cached_tokens is not None:
            payload["input_cached"] = cached_tokens
        return payload

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
        thinking_enabled: bool | None = None,
    ) -> LLMResponse:
        converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "messages": converted,
            "temperature": temperature,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        kwargs.update(self._extra_chat_kwargs(thinking_enabled=thinking_enabled))
        openai_tools = self._convert_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools
        self._apply_cache_options(kwargs, cache)

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
            reasoning=(
                getattr(message, "reasoning", None)
                or getattr(message, "reasoning_content", None)
                or ""
            ),
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
        thinking_enabled: bool | None = None,
    ) -> AsyncIterator[str]:
        async for chunk in self.chat_stream_response(
            messages,
            tools=tools,
            temperature=temperature,
            cache=cache,
            thinking_enabled=thinking_enabled,
        ):
            if chunk.text:
                yield chunk.text

    async def chat_stream_response(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
        thinking_enabled: bool | None = None,
    ) -> AsyncIterator[LLMStreamChunk]:
        """Stream text while retaining OpenAI tool-call deltas for the final response."""
        converted = self._convert_messages(messages)
        kwargs = {
            "model": self.model,
            "messages": converted,
            "temperature": temperature,
            "stream": True,
        }
        if self.max_tokens is not None:
            kwargs["max_tokens"] = self.max_tokens
        kwargs.update(self._extra_chat_kwargs(thinking_enabled=thinking_enabled))
        openai_tools = self._convert_tools(tools)
        if openai_tools:
            kwargs["tools"] = openai_tools
        self._apply_cache_options(kwargs, cache)

        stream = await self.client.chat.completions.create(**kwargs)
        content_parts: list[str] = []
        reasoning_parts: list[str] = []
        tool_call_parts: dict[int, dict[str, str]] = {}
        response_model = self.model
        usage: dict[str, int] = {}
        async for chunk in stream:
            response_model = getattr(chunk, "model", None) or response_model
            chunk_usage = getattr(chunk, "usage", None)
            if chunk_usage:
                usage = self._usage_payload(chunk_usage)
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            reasoning = (
                getattr(delta, "reasoning", None)
                or getattr(delta, "reasoning_content", None)
                or ""
            )
            if reasoning:
                reasoning_parts.append(reasoning)
                yield LLMStreamChunk(reasoning=reasoning)
            text = delta.content or ""
            if text:
                content_parts.append(text)
                yield LLMStreamChunk(text=text)
            for tool_delta in getattr(delta, "tool_calls", None) or []:
                index = int(getattr(tool_delta, "index", 0) or 0)
                part = tool_call_parts.setdefault(
                    index,
                    {"id": "", "name": "", "arguments": ""},
                )
                part["id"] += getattr(tool_delta, "id", None) or ""
                function = getattr(tool_delta, "function", None)
                if function:
                    part["name"] += getattr(function, "name", None) or ""
                    part["arguments"] += getattr(function, "arguments", None) or ""

        tool_calls: list[ToolCall] = []
        for index in sorted(tool_call_parts):
            part = tool_call_parts[index]
            raw_arguments = part["arguments"] or "{}"
            try:
                arguments = json.loads(raw_arguments)
            except json.JSONDecodeError:
                arguments = {"_raw": raw_arguments}
            tool_calls.append(
                ToolCall(
                    id=part["id"] or f"stream_tool_{index}",
                    name=part["name"],
                    arguments=arguments,
                )
            )

        yield LLMStreamChunk(
            response=LLMResponse(
                content="".join(content_parts),
                reasoning="".join(reasoning_parts),
                tool_calls=tool_calls,
                model=response_model,
                usage=usage,
            )
        )
