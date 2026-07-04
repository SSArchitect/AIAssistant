from __future__ import annotations
import json
from typing import AsyncIterator

from google import genai
from google.genai import types

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


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model

    def _convert_messages(
        self, messages: list[LLMMessage]
    ) -> tuple[str | None, list[types.Content]]:
        """Extract system prompt and convert messages to Gemini format."""
        system = None
        converted: list[types.Content] = []

        for msg in messages:
            if msg.role == "system":
                system = content_to_plain_text(msg.content)
                continue

            if msg.role == "tool":
                # Tool result → function response
                content_str = content_to_plain_text(msg.content)
                try:
                    result_data = json.loads(content_str)
                except (json.JSONDecodeError, TypeError):
                    result_data = {"result": content_str}

                converted.append(types.Content(
                    role="user",
                    parts=[types.Part.from_function_response(
                        name=msg.tool_call_id or "unknown",
                        response=result_data,
                    )],
                ))
            elif msg.role == "assistant" and msg.tool_calls:
                parts = []
                if msg.content:
                    text = content_to_plain_text(msg.content)
                    if text:
                        parts.append(types.Part.from_text(text=text))
                for tc in msg.tool_calls:
                    parts.append(types.Part.from_function_call(
                        name=tc["name"],
                        args=tc["arguments"],
                    ))
                converted.append(types.Content(role="model", parts=parts))
            elif msg.role == "assistant":
                converted.append(types.Content(
                    role="model",
                    parts=self._convert_content_parts(msg.content),
                ))
            else:
                # user message
                converted.append(types.Content(
                    role="user",
                    parts=self._convert_content_parts(msg.content),
                ))

        return system, converted

    def _convert_content_parts(self, content: str | list[dict]) -> list[types.Part]:
        if isinstance(content, str):
            return [types.Part.from_text(text=content)]

        parts: list[types.Part] = []
        for item in normalize_content_parts(content):
            if item["type"] == "text":
                parts.append(types.Part.from_text(text=item["text"]))
                continue
            image_url = item["image_url"]["url"]
            parsed = data_url_bytes(image_url)
            if parsed:
                mime_type, data = parsed
                parts.append(types.Part.from_bytes(data=data, mime_type=mime_type))
            else:
                parts.append(types.Part.from_text(text=f"[image URL: {image_url}]"))
        return parts or [types.Part.from_text(text="")]

    def _convert_tools(self, tools: list[ToolDefinition] | None) -> list[types.Tool] | None:
        if not tools:
            return None

        declarations = []
        for t in tools:
            # Convert JSON Schema parameters to Gemini format
            params = t.parameters.copy() if t.parameters else {}
            declarations.append(types.FunctionDeclaration(
                name=t.name,
                description=t.description,
                parameters=params,
            ))
        return [types.Tool(function_declarations=declarations)]

    async def chat(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
    ) -> LLMResponse:
        system, converted = self._convert_messages(messages)

        config = types.GenerateContentConfig(
            temperature=temperature,
        )
        if system:
            config.system_instruction = system

        gemini_tools = self._convert_tools(tools)
        if gemini_tools:
            config.tools = gemini_tools

        try:
            response = await self.client.aio.models.generate_content(
                model=self.model,
                contents=converted,
                config=config,
            )
        except Exception as e:
            self._check_rate_limit(e)
            raise

        content = ""
        tool_calls = []

        if response.candidates and response.candidates[0].content:
            for part in response.candidates[0].content.parts:
                if part.text:
                    content += part.text
                elif part.function_call:
                    fc = part.function_call
                    tool_calls.append(
                        ToolCall(
                            id=f"gemini_{fc.name}",
                            name=fc.name,
                            arguments=dict(fc.args) if fc.args else {},
                        )
                    )

        usage = {}
        if response.usage_metadata:
            usage = {
                "input": response.usage_metadata.prompt_token_count or 0,
                "output": response.usage_metadata.candidates_token_count or 0,
            }

        return LLMResponse(
            content=content,
            tool_calls=tool_calls,
            model=self.model,
            usage=usage,
        )

    @staticmethod
    def _check_rate_limit(exc: Exception) -> None:
        """Detect Gemini rate limit errors and raise RateLimitError."""
        msg = str(exc).lower()
        if "resource_exhausted" in msg or "quota" in msg or "rate" in msg:
            # Try to extract retry delay
            import re
            retry_after = None
            m = re.search(r'retry\s+in\s+([\d.]+)', str(exc))
            if m:
                retry_after = float(m.group(1))
            raise RateLimitError(
                provider="gemini",
                message=f"Gemini API rate limit exceeded. {f'Please retry in {int(retry_after)}s.' if retry_after else 'Please wait a moment and try again.'}",
                retry_after=retry_after,
            ) from exc

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        tools: list[ToolDefinition] | None = None,
        temperature: float = 0.7,
        cache: PromptCacheOptions | None = None,
    ) -> AsyncIterator[str]:
        system, converted = self._convert_messages(messages)

        config = types.GenerateContentConfig(
            temperature=temperature,
        )
        if system:
            config.system_instruction = system

        async for chunk in await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=converted,
            config=config,
        ):
            if chunk.text:
                yield chunk.text
