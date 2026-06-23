from __future__ import annotations

import html
import re
from uuid import uuid4

from .base import LLMResponse, ToolCall
from .openai_provider import OpenAIProvider


class MiniMaxProvider(OpenAIProvider):
    """MiniMax provider using the OpenAI-compatible Chat Completions API."""

    disable_stream_after_tools = True

    def __init__(
        self,
        api_key: str,
        model: str = "MiniMax-M3",
        base_url: str = "https://api.minimaxi.com/v1",
        thinking: str = "disabled",
        timeout_seconds: float | None = 60,
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
        )
        self.thinking = thinking
        self.provider_name = "minimax"

    def _extra_chat_kwargs(self) -> dict:
        if self.model != "MiniMax-M3" or not self.thinking:
            return {}
        return {
            "extra_body": {
                "thinking": {"type": self.thinking},
            },
        }

    async def chat(self, *args, **kwargs) -> LLMResponse:
        response = await super().chat(*args, **kwargs)
        if response.tool_calls:
            return response

        content, tool_calls = self._extract_text_tool_calls(response.content)
        if not tool_calls:
            return response
        return response.model_copy(
            update={
                "content": content,
                "tool_calls": tool_calls,
            }
        )

    def _extract_text_tool_calls(self, content: str) -> tuple[str, list[ToolCall]]:
        normalized = re.sub(r"\]<\]minimax\[>\[", "", content or "")
        match = re.search(r"<tool_call>(.*?)</tool_call>", normalized, flags=re.DOTALL)
        if not match:
            return content, []

        prefix = normalized[: match.start()].strip()
        body = match.group(1)
        calls: list[ToolCall] = []
        for index, invoke in enumerate(
            re.finditer(
                r"<invoke\s+name=[\"']([^\"']+)[\"']\s*>(.*?)</invoke>",
                body,
                flags=re.DOTALL,
            ),
            start=1,
        ):
            name = invoke.group(1).strip()
            args: dict[str, object] = {}
            for arg in re.finditer(
                r"<([A-Za-z_][\w-]*)>(.*?)</\1>",
                invoke.group(2),
                flags=re.DOTALL,
            ):
                key = arg.group(1)
                value = html.unescape(arg.group(2).strip())
                args[key] = self._coerce_tool_argument(value)
            calls.append(
                ToolCall(
                    id=f"minimax_call_{uuid4().hex}_{index}",
                    name=name,
                    arguments=args,
                )
            )
        return prefix, calls

    def _coerce_tool_argument(self, value: str) -> object:
        if re.fullmatch(r"-?\d+", value):
            try:
                return int(value)
            except ValueError:
                return value
        if re.fullmatch(r"-?\d+\.\d+", value):
            try:
                return float(value)
            except ValueError:
                return value
        if value.lower() == "true":
            return True
        if value.lower() == "false":
            return False
        return value
