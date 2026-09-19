"""Repair video reference bindings without rewriting timing, shots or user choices."""
from __future__ import annotations
import json
import re
from collections import Counter
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agent.aigc.creation_models import PlanningConstraintError
from agent.aigc.creation_output import structured_options, thinking_options, unsupported_schema, validation_details
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


class ReferenceEntry(BaseModel):
    model_config = ConfigDict(extra='forbid')
    kind: Literal['Subject', 'Picture']
    number: int = Field(ge=1, le=99)
    description: str = Field(min_length=1, max_length=1000, pattern=r'^[^\r\n]+$')
    pictures: list[int] = Field(min_length=1, max_length=9)
    shots: list[int] = Field(min_length=1, max_length=12)
    retention: Literal['fully_preserved', 'partially_preserved', 'attribute_transfer', 'weak_reference']
    retained_features: str = Field(min_length=1, max_length=1000, pattern=r'^[^\r\n]+$')


class ReferenceBlueprint(BaseModel):
    """The model chooses roles/indices; code owns labels, lines and punctuation."""
    model_config = ConfigDict(extra='forbid')
    labels: list[LabelChange] = Field(max_length=30)
    entries: list[ReferenceEntry] = Field(max_length=30)
    summary: str | None = Field(max_length=4000)

    def materialize(self, picture_count, shot_count, mode):
        if mode != 'reference_to_video':
            if self.entries or self.summary:
                raise ValueError('非多图参考模式不应新增参考定义')
            return ReferenceRepair(labels=self.labels, subject_definitions=None, summary=None, retention_analysis=None)
        definitions, retention, seen = [], [], set()
        for entry in self.entries:
            label = f'<{entry.kind} {entry.number}>'
            if label in seen or len(set(entry.pictures)) != len(entry.pictures) or len(set(entry.shots)) != len(entry.shots):
                raise ValueError('参考标签、输入图片或出现镜头不能重复')
            seen.add(label)
            if any(not 1 <= i <= picture_count for i in entry.pictures):
                raise ValueError('参考图片编号越界')
            if any(not 1 <= i <= shot_count for i in entry.shots):
                raise ValueError('出现镜头只能使用实际Logical Shot编号，场景/Panel序号不是Shot编号')
            if entry.kind == 'Picture' and entry.pictures != [entry.number]:
                raise ValueError('独立Picture锚点必须对应同号输入图片')
            sources = ', '.join(f'<Picture {i}>' for i in entry.pictures)
            definitions.append(f'{label} {entry.description}' + (f' (from {sources}).' if entry.kind == 'Subject' else ''))
            shots = ', '.join(f'[Shot {i}]' for i in sorted(entry.shots))
            retention.append(f'{label} (appears in {shots}): {entry.retention} - {entry.retained_features}')
        if not definitions or not self.summary:
            raise ValueError('多图参考需要完整定义与叙事摘要')
        summary = self.summary if self.summary.startswith('[reference generation]') else '[reference generation] ' + self.summary
        return ReferenceRepair(labels=self.labels, subject_definitions='\n'.join(definitions), summary=summary, retention_analysis='\n'.join(retention))


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
    inputs = (request.reference_image_asset_ids or request.reference_image_attachment_indices or request.reference_image_urls or request.reference_image_data_urls or [])
    picture_count, shot_count = len(inputs), len(storyboard.shots)
    schema = ReferenceBlueprint.model_json_schema()
    schema['$defs']['ReferenceEntry']['properties']['pictures']['items']['enum'] = list(range(1, picture_count + 1)) or [1]
    schema['$defs']['ReferenceEntry']['properties']['shots']['items']['enum'] = list(range(1, shot_count + 1))
    messages = [LLMMessage(role='system', content='你是创作 Agent 的视频参考绑定修复工具。只修正当前视频内的图片/主体编号和参考定义。图片编号从1开始，以input_images顺序、名称、role和note为权威，禁止沿用其他视频或项目的全局编号。不得新增或删除参考图，不得改变身份/风格/首帧职责。labels给出需要替换的旧编号到新编号；程序只替换标签，不改写镜头、时间、台词、动作、规则或用户选择。entries逐项填写主体或独立Picture锚点的kind、number、单行description、来源pictures、出现的实际shots、retention保留方式与retained_features；程序编译所有标签和协议行，不在description里自行写定义前缀。所有输入图片都须分配职责；Picture锚点的pictures只含自身编号。shots仅能取actual_shots中的编号，场景数量与Panel数量不等于Logical Shot数量；单个连续Shot经过多个环境时，多个环境都出现于Shot 1，用scene_intervals区分时段，严禁虚构Shot 2/3。summary写叙事摘要，程序添加协议前缀。原文对白和引号原文必须原样保留。非reference_to_video模式entries=[]、summary=null。只返回严格JSON。\nJSON schema:\n'+json.dumps(schema,ensure_ascii=False)),
        LLMMessage(role='user', content=json.dumps(dict(mode=request.mode, input_images=images, actual_shots=[dict(number=i, start_seconds=shot.start_seconds) for i, shot in enumerate(storyboard.shots, 1)], storyboard=storyboard.model_dump()), ensure_ascii=False))]
    usage, json_only = {}, False
    for attempt in range(3):
        try:
            response = await provider.chat(messages, tools=None, temperature=.1, **thinking_options(provider),
                **structured_options(provider, schema, 'creation_reference_repair', json_only=json_only))
        except Exception as exc:
            if not json_only and unsupported_schema(exc):
                json_only = True
                continue
            raise
        for key, count in response.usage.items():
            usage[key] = usage.get(key, 0) + count
        try:
            blueprint = ReferenceBlueprint.model_validate_json(response.content)
            fixed = apply_reference_repair(storyboard, blueprint.materialize(picture_count, shot_count, request.mode))
            try:
                compile_storyboard(fixed, request)
            except ValueError as exc:
                if 'Compiled storyboard is' not in str(exc):
                    raise
            return fixed, usage
        except (ValueError, TypeError) as exc:
            # No raw response or user content enters the public error/diagnostic log.
            detail = json.dumps(validation_details(exc),ensure_ascii=False) if hasattr(exc, 'errors') else str(exc)
            messages.extend([LLMMessage(role='assistant', content=response.content),
                LLMMessage(role='user', content='参考绑定仍未通过：'+detail[:600]+'。只修复参考字段与标签映射，返回全部JSON字段。')])
    raise PlanningConstraintError('视频参考图绑定自动整理未完成，已保留你的选择与原方案，请重试这次规划，无需重新选择创作方向', code='video_reference_failed')
