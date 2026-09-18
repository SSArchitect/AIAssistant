"""Repair video reference bindings without rewriting timing, shots or user choices."""
from __future__ import annotations
import json
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.aigc.creation_models import PlanningConstraintError
from agent.aigc.creation_output import structured_options, thinking_options, unsupported_schema
from agent.aigc.video_prompting import VideoStoryboard, compile_storyboard
from agent.llm.base import LLMMessage


class LabelChange(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['Subject', 'Picture']
    source: int = Field(ge=1, le=99)
    target: int = Field(ge=1, le=99)


class ReferenceRepair(BaseModel):
    model_config = ConfigDict(extra='forbid')
    labels: list[LabelChange] = Field(max_length=30)
    subject_definitions: str | None = Field(max_length=4000)
    summary: str | None = Field(max_length=4000)
    retention_analysis: str | None = Field(max_length=4000)


def reference_error(error):
    return any(marker in str(error) for marker in ('<Picture', '<Subject', 'subject_definitions', 'Reference storyboard',
        'Reference summary', 'Define each reference', 'retention_analysis', 'Reference definitions'))


def apply_reference_repair(storyboard, repair):
    mapping = {}
    for label in repair.labels:
        key = (label.kind, str(label.source))
        if key in mapping:
            raise ValueError('同一来源标签只能映射一次')
        mapping[key] = f'<{label.kind} {label.target}>'

    def replace(value):
        if isinstance(value, str):
            return re.sub(r'<(Subject|Picture)\s+(\d+)>', lambda m: mapping.get(m.groups(), m.group()), value)
        if isinstance(value, list):
            return [replace(item) for item in value]
        if isinstance(value, dict):
            return {key: replace(item) for key, item in value.items()}
        return value

    value = replace(storyboard.model_dump())
    for field in ('subject_definitions', 'summary', 'retention_analysis'):
        value[field] = getattr(repair, field)
    # Check literal speech and on-screen text across the complete storyboard.
    def literals(data):
        if isinstance(data, str):
            return Counter(re.findall(r'<d>[\s\S]*?</d>|"(?:[^"\\]|\\.)*"', data))
        result = Counter()
        for item in data.values() if isinstance(data, dict) else data if isinstance(data, list) else []:
            result.update(literals(item))
        return result
    if literals(value) != literals(storyboard.model_dump()):
        raise ValueError('参考修复不得增加、删除或改动对白及引号原文')
    return VideoStoryboard.model_validate(value)


async def repair_reference_storyboard(storyboard, request, images, provider):
    messages = [LLMMessage(role='system', content='你是创作 Agent 的视频参考绑定修复工具。只修正当前视频内的图片/主体编号和参考定义。图片编号从1开始，以input_images顺序、名称、role和note为权威，禁止沿用其他视频或项目的全局编号。不得新增或删除参考图，不得改变身份/风格/首帧职责。labels给出需要替换的旧编号到新编号；程序只替换这些标签，不会改写镜头、时间、台词、动作、规则或用户选择。返回三份完整参考字段：subject_definitions每行定义一个Subject并关联实际Picture，所有实际输入图都须分配职责；风格/构图图可独立定义为Picture锚点。summary以[reference generation]开头；retention_analysis每个定义一行，含实际[Shot N]与合法保留标记。原文对白和引号原文必须原样保留。非reference_to_video模式三字段返回null。只返回严格JSON。'),
        LLMMessage(role='user', content=json.dumps(dict(mode=request.mode, input_images=images, storyboard=storyboard.model_dump()), ensure_ascii=False))]
    usage, json_only = {}, False
    for attempt in range(3):
        try:
            response = await provider.chat(messages, tools=None, temperature=.1, **thinking_options(provider),
                **structured_options(provider, ReferenceRepair.model_json_schema(), 'creation_reference_repair', json_only=json_only))
        except Exception as exc:
            if not json_only and unsupported_schema(exc):
                json_only = True
                continue
            raise
        for key, count in response.usage.items():
            usage[key] = usage.get(key, 0) + count
        try:
            fixed = apply_reference_repair(storyboard, ReferenceRepair.model_validate_json(response.content))
            try:
                compile_storyboard(fixed, request)
            except ValueError as exc:
                if 'Compiled storyboard is' not in str(exc):
                    raise
            return fixed, usage
        except (ValueError, TypeError) as exc:
            # No raw response or user content enters the public error/diagnostic log.
            detail = type(exc).__name__ if hasattr(exc, 'errors') else str(exc)
            messages.extend([LLMMessage(role='assistant', content=response.content),
                LLMMessage(role='user', content='参考绑定仍未通过：'+detail[:600]+'。只修复参考字段与标签映射，返回全部JSON字段。')])
    raise PlanningConstraintError('视频参考图绑定自动整理未完成，已保留你的选择与原方案，请重试这次规划，无需重新选择创作方向', code='video_reference_failed')
