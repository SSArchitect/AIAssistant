"""Compact prose while code preserves timing, protocol and verbatim user text."""
import copy
import json
import re
import logging
from collections import Counter

from agent.aigc.creation_models import PlanningConstraintError
from agent.aigc.creation_output import structured_options, thinking_options, unsupported_schema
from agent.aigc.video_prompting import VideoStoryboard, compile_storyboard, render_storyboard
from agent.llm.base import LLMMessage

logger = logging.getLogger(__name__)
# Retention line prefixes, dialogue and visible text never go through rewriting.
LITERAL = re.compile(r'<d>[\s\S]*?</d>|"(?:[^"\\]|\\.)*"|^\s*<(?:Subject|Picture)\s+\d+>[^\n]*?:\s*(?:fully_preserved|partially_preserved|attribute_transfer|weak_reference)\s*-\s*|<(?:Subject|Picture)\s+\d+>|\[reference generation\]|\[Shot \d+\]', re.MULTILINE)


def prose_paths(value):
    for key in ('style', 'summary', 'subject_definitions', 'retention_analysis', 'overall_soundscape', 'non_diegetic_music'):
        if value.get(key) and value[key] != 'N/A':
            yield (key,)
    for key in ('reference_rules', 'continuity_locks', 'execution_constraints'):
        for i, _ in enumerate(value.get(key, [])):
            yield (key, i)
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


async def compact_storyboard(storyboard, request, provider, *, reserved_chars=0):
    original = storyboard.model_dump()
    paths = list(prose_paths(original))
    segments, fields = [], {}
    for path in paths:
        text = at(original, path)
        pieces, cursor = [], 0
        for match in [*LITERAL.finditer(text), None]:
            end = match.start() if match else len(text)
            fragment = text[cursor:end]
            if len(fragment.strip()) > 24:
                index = len(segments)
                # Retain whitespace around labels, especially definition line starts.
                leading = fragment[:len(fragment)-len(fragment.lstrip())]
                trailing = fragment[len(fragment.rstrip()):]
                segments.append((path, fragment.strip()))
                pieces.append((index, leading, trailing))
            elif fragment:
                pieces.append(fragment)
            if match:
                pieces.append(match.group())
                cursor = match.end()
        fields[path] = pieces

    def assemble(texts):
        value = copy.deepcopy(original)
        for path, pieces in fields.items():
            put(value, path, ''.join(piece if isinstance(piece, str) else piece[1]+texts[piece[0]].strip()+piece[2] for piece in pieces))
        return value

    blank = assemble(['x'] * len(segments))
    # Keep 100 characters of headroom; rendered overhead is measured exactly.
    fixed = len(render_storyboard(VideoStoryboard.model_validate(blank), request.mode)) - len(segments)
    available = 3900 - reserved_chars - fixed
    texts = [text for _, text in segments]
    minimum = [min(24, len(text)) for text in texts]
    if available < sum(minimum):
        raise PlanningConstraintError('视频的原文与执行标记超出单次生成容量，需要缩短或拆分该片；已保留你的选择与原方案', code='execution_capacity_exceeded')
    if not segments:
        compile_storyboard(storyboard, request)
        return storyboard, {}
    weights = [max(1, len(text) - floor) for text, floor in zip(texts, minimum)]
    spare = available - sum(minimum)
    budgets = [floor + spare * weight // sum(weights) for floor, weight in zip(minimum, weights)]
    schema = dict(type='object', properties={f'text_{i}': dict(type='string', minLength=1, maxLength=limit)
        for i, limit in enumerate(budgets)}, required=[f'text_{i}' for i in range(len(segments))], additionalProperties=False)
    payload = {f'text_{i}': dict(path=list(path), text=text, max_characters=limit)
        for i, ((path, _), text, limit) in enumerate(zip(segments, texts, budgets))}
    messages = [LLMMessage(role='system', content='你是创作 Agent 的视频执行稿压缩工具。只缩写给出的文字片段，使用紧凑中文，保留动作、因果、人物特征、运镜、声音、参考职责与约束含义。程序已提取并锁定对白、引号原文和协议标记，会在原位置自动拼回；不要补写、重复或新增对白、引号、Subject/Picture标签、时间或其他协议。片段按path和顺序提供，可能只是标签之间的短语，不需补成完整句子。短片段可原样返回；每个text_i必须非空，严格不超过max_characters。只返回全部text_i到字符串的JSON对象。'),
        LLMMessage(role='user', content=json.dumps(payload, ensure_ascii=False))]
    usage = {}
    max_tokens = getattr(provider, 'max_tokens', None)
    if hasattr(provider, 'max_tokens'):
        provider.max_tokens = 8192
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
                rewritten = []
                for i, (text, limit) in enumerate(zip(texts, budgets)):
                    new = replacement[f'text_{i}']
                    if not isinstance(new, str) or not new.strip() or len(new) > limit:
                        raise ValueError(f'text_{i}必须为1–{limit}字符的非空字符串')
                    if LITERAL.search(new):
                        raise ValueError(f'text_{i}不得新增对白或协议标记；程序会恢复原文')
                    rewritten.append(new)
                value = assemble(rewritten)
                if any(protected(at(value, path)) != protected(at(original, path)) for path in paths):
                    raise ValueError('压缩改变了原文或协议边界')
                compacted = VideoStoryboard.model_validate(value)
                compile_storyboard(compacted, request)
                return compacted, usage
            except (ValueError, TypeError) as exc:
                logger.warning('Creation execution compaction rejected: attempt=%s reason=%s', attempt + 1, type(exc).__name__ if hasattr(exc, 'errors') else str(exc)[:300])
                if attempt == 2:
                    break
                messages.extend([LLMMessage(role='assistant', content=response.content),
                    LLMMessage(role='user', content='未通过校验：' + str(exc)[:500] + '。缩短叙述文字，不截断对白或标记，重新输出全部text_i。')])
        raise PlanningConstraintError('视频执行稿自动整理未完成，已保留你的选择与原方案，请重试这次规划，无需重新选择创作方向', code='execution_compaction_failed')
    finally:
        if hasattr(provider, 'max_tokens'):
            provider.max_tokens = max_tokens
