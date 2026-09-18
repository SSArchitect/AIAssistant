"""Bounded node-level execution editing; timing, reference rules and locks stay fixed."""
import copy
import json
import re
from collections import Counter

from agent.aigc.creation_models import PlanningConstraintError
from agent.aigc.creation_output import structured_options, thinking_options, unsupported_schema
from agent.aigc.video_prompting import VideoStoryboard, compile_storyboard, render_storyboard
from agent.llm.base import LLMMessage


def prose_paths(value):
    for key in ('style', 'summary', 'overall_soundscape', 'non_diegetic_music'):
        if value.get(key) and value[key] != 'N/A':
            yield (key,)
    for i, shot in enumerate(value['shots']):
        yield ('shots', i, 'description')
        for j, _ in enumerate(shot.get('panels', [])):
            yield ('shots', i, 'panels', j, 'description')


def at(value, path):
    for key in path:
        value = value[key]
    return value


def put(value, path, text):
    target = value
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = text


def protected(text):
    return Counter(re.findall(r'<d>[\s\S]*?</d>|"(?:[^"\\]|\\.)*"|<(?:Subject|Picture)\s+\d+>', text))


async def compact_storyboard(storyboard, request, provider):
    original = storyboard.model_dump()
    paths = list(prose_paths(original))
    blank = copy.deepcopy(original)
    for path in paths:
        put(blank, path, 'x')
    # Keep 100 characters of headroom; rendered overhead is measured exactly.
    fixed = len(render_storyboard(VideoStoryboard.model_validate(blank), request.mode)) - len(paths)
    available = 3900 - fixed
    texts = [at(original, path) for path in paths]
    minimum = [max(24, sum(len(s) * count for s, count in protected(text).items()) + 12) for text in texts]
    if available < sum(minimum):
        raise PlanningConstraintError('视频的必要对白与连续性约束已超出执行长度，请精简该片内容；原有审阅稿保留')
    weights = [max(1, len(text) - floor) for text, floor in zip(texts, minimum)]
    spare = available - sum(minimum)
    budgets = [floor + spare * weight // sum(weights) for floor, weight in zip(minimum, weights)]
    schema = dict(type='object', properties={f'text_{i}': dict(type='string', minLength=1, maxLength=limit)
        for i, limit in enumerate(budgets)}, required=[f'text_{i}' for i in range(len(paths))], additionalProperties=False)
    payload = {f'text_{i}': dict(path=list(path), text=text, max_characters=limit)
        for i, (path, text, limit) in enumerate(zip(paths, texts, budgets))}
    messages = [LLMMessage(role='system', content='你是创作 Agent 的视频执行稿压缩工具。只缩写给出的各段文字，保留可见动作、因果、人物、运镜、声音与结尾状态。优先使用紧凑中文压缩描述；<Subject N>/<Picture N>、英文协议标记、所有<d>对白块和双引号内原文必须逐字保留且次数不变。summary仍以[reference generation]开头。不要改变时间线、参考职责或创造新内容。每个text_i严格不超过max_characters个字符。只返回text_i到字符串的JSON对象，不返回解释或其他结构。'),
        LLMMessage(role='user', content=json.dumps(payload, ensure_ascii=False))]
    usage = {}
    max_tokens = getattr(provider, 'max_tokens', None)
    if hasattr(provider, 'max_tokens'):
        provider.max_tokens = 4096
    json_only = False
    try:
        for attempt in range(3):
            try:
                response = await provider.chat(messages, tools=None, temperature=.1, **thinking_options(provider),
                    **structured_options(provider, schema, 'creation_execution_prose', json_only=json_only))
            except Exception as exc:
                if not json_only and unsupported_schema(exc):
                    json_only = True
                    continue
                raise
            for key, count in response.usage.items():
                usage[key] = usage.get(key, 0) + count
            try:
                replacement = json.loads(response.content)
                if not isinstance(replacement, dict) or set(replacement) != set(schema['properties']):
                    raise ValueError('必须提供且只提供全部text_i字段')
                value = copy.deepcopy(original)
                for i, (path, text, limit) in enumerate(zip(paths, texts, budgets)):
                    new = replacement[f'text_{i}']
                    if not isinstance(new, str) or not new.strip() or len(new) > limit:
                        raise ValueError(f'text_{i}必须为1–{limit}字符的非空字符串')
                    if protected(new) != protected(text):
                        raise ValueError(f'text_{i}改动了对白、引号原文或主体/图片标记，必须完整保留')
                    put(value, path, new)
                compacted = VideoStoryboard.model_validate(value)
                compile_storyboard(compacted, request)
                return compacted, usage
            except (ValueError, TypeError) as exc:
                if attempt == 2:
                    break
                messages.extend([LLMMessage(role='assistant', content=response.content),
                    LLMMessage(role='user', content='未通过校验：' + str(exc)[:500] + '。缩短叙述文字，不截断对白或标记，重新输出全部text_i。')])
        raise PlanningConstraintError('视频执行稿仍超出长度或改动了必要原文，未提交生成；原有审阅稿保留')
    finally:
        if hasattr(provider, 'max_tokens'):
            provider.max_tokens = max_tokens
