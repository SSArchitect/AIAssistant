from __future__ import annotations

import html
import re
from uuid import uuid4

from .base import LLMResponse, LLMStreamChunk, ToolCall
from .openai_provider import OpenAIProvider


class _ThinkingPrefixSplitter:
    """Separate a leading think block without leaking partial stream delimiters."""

    def __init__(self):
        self.pending = ""
        self.state = "prefix"

    def feed(self, text: str, *, final: bool = False) -> tuple[str, str]:
        self.pending += text
        reasoning = ""
        openings = ("<think>", "<mm:think>")
        closings = ("</think>", "</mm:think>")
        if self.state == "prefix":
            candidate = self.pending.lstrip()
            opening = next((tag for tag in openings if candidate.startswith(tag)), None)
            closing = next((tag for tag in closings if candidate.startswith(tag)), None)
            if opening:
                self.pending = candidate[len(opening):]
                self.state = "thinking"
            elif closing:
                self.pending = candidate[len(closing):]
                self.state = "answer_start"
            elif not final and (not candidate or any(tag.startswith(candidate) for tag in openings + closings)):
                return "", ""
            else:
                self.state = "answer"
        if self.state == "thinking":
            matches = [(self.pending.find(tag), tag) for tag in closings if tag in self.pending]
            end, closing = min(matches) if matches else (-1, "")
            if end < 0:
                keep = 0
                if not final:
                    for tag in closings:
                        for size in range(1, len(tag)):
                            if self.pending.endswith(tag[:size]):
                                keep = max(keep, size)
                end = len(self.pending) - keep
                reasoning, self.pending = self.pending[:end], self.pending[end:]
                return "", reasoning
            reasoning, self.pending = self.pending[:end], self.pending[end + len(closing):]
            self.state = "answer_start"
        if self.state == "answer_start":
            self.pending = self.pending.lstrip()
            if self.pending:
                self.state = "answer"
        answer, self.pending = self.pending, ""
        return answer, reasoning


class MiniMaxProvider(OpenAIProvider):
    """MiniMax provider using the OpenAI-compatible Chat Completions API."""

    disable_stream_after_tools = True

    def __init__(
        self,
        api_key: str,
        model: str = "MiniMax-M3",
        base_url: str = "https://api.minimaxi.com/v1",
        thinking: str = "disabled",
        timeout_seconds: float | None = 1800,
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            timeout_seconds=timeout_seconds,
            provider_label="MiniMax",
        )
        self.thinking = thinking
        self.provider_name = "minimax"
        self.supports_streaming_tool_calls = model == "MiniMax-M3"
        self.disable_stream_after_tools = not self.supports_streaming_tool_calls

    def _extra_chat_kwargs(self, *, thinking_enabled: bool | None = None) -> dict:
        if self.model != "MiniMax-M3":
            return {}
        thinking = self.thinking
        if thinking_enabled is not None:
            thinking = "adaptive" if thinking_enabled else "disabled"
        elif thinking == "enabled":
            # Accept the legacy setting while using MiniMax M3's API enum.
            thinking = "adaptive"
        return {
            "extra_body": {
                "reasoning_split": True,
                **({"thinking": {"type": thinking}} if thinking else {}),
            },
        }

    def _extract_reasoning(self, message) -> str:
        reasoning = super()._extract_reasoning(message)
        if reasoning:
            return reasoning
        return "".join(
            detail["text"]
            for detail in (getattr(message, "reasoning_details", None) or [])
            if isinstance(detail, dict) and isinstance(detail.get("text"), str)
        )

    def _normalize_response(self, response: LLMResponse) -> LLMResponse:
        content, reasoning = _ThinkingPrefixSplitter().feed(response.content, final=True)
        response = response.model_copy(update={
            "content": content,
            "reasoning": response.reasoning or reasoning,
        })

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

    async def chat(self, *args, **kwargs) -> LLMResponse:
        return self._normalize_response(await super().chat(*args, **kwargs))

    async def chat_stream_response(self, *args, **kwargs):
        splitter = _ThinkingPrefixSplitter()
        has_separate_reasoning = False
        async for chunk in super().chat_stream_response(*args, **kwargs):
            if chunk.reasoning:
                has_separate_reasoning = True
                yield LLMStreamChunk(reasoning=chunk.reasoning)
            text, reasoning = splitter.feed(chunk.text, final=chunk.response is not None)
            if reasoning and not has_separate_reasoning:
                yield LLMStreamChunk(reasoning=reasoning)
            if text:
                yield LLMStreamChunk(text=text)
            if chunk.response is not None:
                yield LLMStreamChunk(response=self._normalize_response(chunk.response))

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
