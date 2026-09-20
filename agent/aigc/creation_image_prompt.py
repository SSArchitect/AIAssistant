"""Fit image execution prose into the measured provider budget without truncation."""
import asyncio
from collections import Counter
import hashlib
import json
import logging
import os
from pathlib import Path
import re
import tempfile

from agent.aigc.creation_models import create_creation_provider, can_use_plan_vision, use_plan_vision, planning_error
from agent.aigc.creation_output import structured_options, thinking_options, unsupported_schema
from agent.llm.base import LLMMessage
from agent.llm.factory import create_provider

CONTEXT_DIR = Path(__file__).resolve().parents[2] / 'data/creation-image-contexts'
logger = logging.getLogger(__name__)
LITERAL = re.compile(r'“[^”]*”|「[^」]*」|"(?:[^"\\]|\\.)*"|<?Picture\s+\d+>?|\d+(?:[./:]\d+)*(?:[%％]|[A-Za-z]+)?')


class ImagePromptError(ValueError):
    def __init__(self, code='media_image_prompt_compaction_failed', *, reason='compaction_failed'):
        super().__init__('图片执行稿自动整理未完成，原有方案与资产保留，尚未提交生成')
        self.code = code
        self.reason = reason


def check_compacted(original, result, budget):
    if not isinstance(result, str) or not result.strip() or len(result) > budget:
        raise ImagePromptError(reason='over_budget_or_empty')
    if Counter(LITERAL.findall(original)) != Counter(LITERAL.findall(result)):
        raise ImagePromptError(reason='protected_text_changed')
    return result


async def compact_image_prompt(prompt, budget):
    # Code owns literal placement. The model rewrites only prose fragments and
    # never needs to reproduce placeholders, numbers, quotes or picture labels.
    pieces, segments, cursor = [], [], 0
    for match in [*LITERAL.finditer(prompt), None]:
        end=match.start() if match else len(prompt)
        fragment=prompt[cursor:end]
        if len(fragment.strip())>16:
            leading=fragment[:len(fragment)-len(fragment.lstrip())]
            trailing=fragment[len(fragment.rstrip()):]
            pieces.append((len(segments),leading,trailing))
            segments.append(fragment.strip())
        elif fragment:
            pieces.append(fragment)
        if match:
            pieces.append(match.group())
            cursor=match.end()
    def assemble(texts):
        return ''.join(piece if isinstance(piece,str) else piece[1]+texts[piece[0]].strip()+piece[2] for piece in pieces)
    fixed=len(assemble(['']*len(segments)))
    available=budget-fixed
    if not segments or available<8*len(segments):
        raise ImagePromptError('media_image_prompt_capacity')
    total=sum(map(len,segments))
    budgets=[8+(available-8*len(segments))*len(text)//total for text in segments]
    properties={f'text_{i}':dict(type='string',minLength=1,maxLength=limit) for i,limit in enumerate(budgets)}
    schema=dict(type='object',properties=properties,required=list(properties),additionalProperties=False)
    payload=dict(segments={f'text_{i}':dict(text=text,max_characters=budgets[i]) for i,text in enumerate(segments)},
        sequence=[piece if isinstance(piece,str) else dict(segment=f'text_{piece[0]}') for piece in pieces])
    messages=[LLMMessage(role='system',content='你是创作Agent的图片执行稿精简工具。只精简segments中的文字片段，保留身份、数量、动作、姿态、接触关系、视线、比例、景别、位置、场景和光线约束。优先用紧凑中文合并冗余，不改变目标。'
        'sequence仅供理解上下文，程序已锁住其中的数字、Picture编号、引号原文及短片段，会按原位置拼回。不要将这些数字、编号或引号文字重复写进text_i，不新增引号或数字。参考职责另外完整保留，不需要补写。'
        '按schema返回全部text_i到非空字符串的JSON对象，各字段按预算精简。'),
        LLMMessage(role='user',content=json.dumps(payload,ensure_ascii=False))]
    provider=create_creation_provider(create_provider)
    if getattr(provider,'model','')=='glm-5.3' and can_use_plan_vision(provider):
        provider=await use_plan_vision(provider,create_provider)
    if hasattr(provider,'max_tokens'):
        provider.max_tokens=8192
    json_only=False
    try:
        for attempt in range(3):
            try:
                response=await provider.chat(messages,tools=None,temperature=.1,**thinking_options(provider),
                    **structured_options(provider,schema,'creation_image_prose',json_only=json_only))
            except Exception as exc:
                if not json_only and unsupported_schema(exc):
                    json_only=True
                    continue
                raise
            try:
                value=json.loads(response.content)
                if response.finish_reason=='length' or not isinstance(value,dict) or set(value)!=set(properties):
                    raise ImagePromptError(reason='incomplete_or_invalid_object')
                texts=[value[f'text_{i}'] for i in range(len(segments))]
                if any(not isinstance(text,str) or not text.strip() for text in texts):
                    raise ImagePromptError(reason='empty_segment')
                if any(LITERAL.search(text) for text in texts):
                    raise ImagePromptError(reason='new_literal_in_prose')
                return check_compacted(prompt,assemble(texts),budget)
            except (ValueError,TypeError) as exc:
                reason=getattr(exc,'reason','invalid_json')
                logger.warning('Creation image compaction rejected: attempt=%s reason=%s',attempt+1,reason)
                if attempt==2:
                    raise ImagePromptError(reason=reason) from None
                messages.append(LLMMessage(role='user',content='未通过校验：'+reason+'。重新精简全部text_i；不要重复数字、Picture编号或引号内容，程序会按原位置保留。确保总长度满足预算。'))
        raise ImagePromptError()
    finally:
        client=getattr(provider,'client',None)
        if client:
            await client.close()


async def fit_image_prompt(prompt, budget, key):
    if len(prompt)<=budget:
        return prompt
    if budget<40:
        raise ImagePromptError('media_image_prompt_capacity')
    fingerprint=hashlib.sha256(json.dumps(dict(version=2,prompt=prompt,budget=budget),sort_keys=True).encode()).hexdigest()
    cache=CONTEXT_DIR/(hashlib.sha256((key+':image-prose').encode()).hexdigest()+'.json')
    def read():
        record=json.loads(cache.read_text())
        if record['fingerprint']!=fingerprint:
            raise ImagePromptError('media_idempotency_conflict')
        return check_compacted(prompt,record['prompt'],budget)
    if cache.exists():
        return read()
    try:
        result=await asyncio.wait_for(compact_image_prompt(prompt,budget),timeout=90)
        result=check_compacted(prompt,result,budget)
    except ImagePromptError:
        raise
    except Exception as exc:
        reason=planning_error(exc)[0]
        logger.warning('Creation image compaction failed: code=%s',reason)
        raise ImagePromptError(reason=reason) from None
    CONTEXT_DIR.mkdir(parents=True,exist_ok=True,mode=0o700)
    fd,temporary=tempfile.mkstemp(dir=CONTEXT_DIR,suffix='.pending')
    try:
        with os.fdopen(fd,'w') as target:
            json.dump(dict(fingerprint=fingerprint,prompt=result),target)
        try:
            os.link(temporary,cache)
        except FileExistsError:
            pass
    finally:
        os.unlink(temporary)
    return read()
