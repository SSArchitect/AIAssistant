"""Bounded, observable model calls used only by the creation planner."""
import asyncio
import time

import httpx
import openai

from agent.aigc.creation_models import configure_planning_output, PlanningOutputTruncated
from agent.aigc.creation_output import structured_options, thinking_options, unsupported_schema
from agent.llm.openai_provider import OpenAIProvider


class PlanningCompletion:
    def __init__(self, provider, report, *, streaming=False):
        self.provider, self.report, self.streaming = provider, report, streaming
        self.usage, self.model = {}, ''
        self.json_only = False
        # Shared across normal planning and every recovery segment, not per node.
        self.transport_retries = 0

    async def __call__(self, messages, schema, name, *, tools=None):
        configure_planning_output(self.provider)
        while True:
            options = dict(tools=tools, temperature=.4,
                **thinking_options(self.provider),
                **structured_options(self.provider, schema, name, json_only=self.json_only))
            try:
                if self.streaming and callable(getattr(self.provider, 'chat_stream_response', None)):
                    response = None
                    parts, chars, last_report, last_stage = [], 0, 0., ''
                    async for chunk in self.provider.chat_stream_response(messages, **options):
                        if chunk.text:
                            parts.append(chunk.text)
                            chars += len(chunk.text)
                        stage = 'draft' if chars else 'thinking'
                        if (chunk.text or chunk.reasoning) and (stage != last_stage or time.monotonic() - last_report >= 1):
                            await self.report(stage, '正在编排创作方案与待审阅内容' if chars else '模型正在分析需求与素材', output_chars=chars)
                            last_report, last_stage = time.monotonic(), stage
                        if chunk.response is not None:
                            response = chunk.response
                    if response is None:
                        raise PlanningOutputTruncated()
                    if not response.content and parts:
                        response = response.model_copy(update={'content': ''.join(parts)})
                    if isinstance(self.provider, OpenAIProvider) and not response.finish_reason:
                        raise PlanningOutputTruncated()
                else:
                    response = await self.provider.chat(messages, **options)
            except Exception as exc:
                if not self.json_only and unsupported_schema(exc):
                    self.json_only = True
                    await self.report('format', '当前模型使用 JSON 输出约束，继续执行完整结构校验')
                    continue
                transient = isinstance(exc, (httpx.TransportError, openai.APIConnectionError, asyncio.TimeoutError)) or getattr(exc, 'status_code', None) in (502, 503, 504)
                if not transient or self.transport_retries >= 2:
                    raise
                self.transport_retries += 1
                await self.report('retry', f'模型连接暂时中断，正在自动重试（{self.transport_retries}/2）')
                await asyncio.sleep(self.transport_retries)
                continue
            self.model = response.model or self.model
            for key, count in response.usage.items():
                self.usage[key] = self.usage.get(key, 0) + count
            if response.finish_reason == 'length':
                raise PlanningOutputTruncated()
            return response
