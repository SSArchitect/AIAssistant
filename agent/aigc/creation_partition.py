"""Recover oversized proposals with a manifest followed by complete single nodes.

No partial JSON is salvaged or written to the project. The caller still validates
and commits the assembled graph atomically against the original request/locks.
"""
from __future__ import annotations

import copy
import json
from typing import Literal

from pydantic import Field

from agent.aigc.creation_models import PlanningOutputTruncated
from agent.aigc.creation_output import validation_details
from agent.llm.base import LLMMessage


MAX_PARTITION_CALLS = 96


def incomplete_json(text):
    """Recognize an unfinished JSON container; never invent its missing fields."""
    text = text.strip()
    if text.startswith('```'):
        text = text.partition('\n')[2]
    if not text.startswith('{'):
        return False
    stack, quoted, escaped = [], False, False
    for char in text:
        if quoted:
            if escaped:
                escaped = False
            elif char == '\\':
                escaped = True
            elif char == '"':
                quoted = False
        elif char == '"':
            quoted = True
        elif char in '{[':
            stack.append(char)
        elif char in '}]':
            if not stack or stack.pop() != ('{' if char == '}' else '['):
                return False
    return bool(stack or quoted)


async def partition_proposal(request, messages, complete, report, *, checkpoint=None, save_checkpoint=None):
    # Local import keeps wire contracts in one place without a module cycle.
    from agent.aigc.creation_planning import (StrictModel, CreativeQuestion, CreativeNode,
        CreativeNodePatch, decode_proposal)

    class NodeTask(StrictModel):
        id: str = Field(min_length=1, max_length=80, pattern=r'^[a-zA-Z0-9_-]+$')
        kind: Literal['text', 'image', 'video']
        instruction: str = Field(min_length=1, max_length=350)

    class Manifest(StrictModel):
        reply: str = Field(min_length=1, max_length=600)
        title: str | None = Field(default=None, min_length=1, max_length=100)
        summary: str | None = Field(default=None, min_length=1, max_length=1200)
        workflow_template_id: str | None = Field(default=None, max_length=100)
        questions: list[CreativeQuestion] | None = Field(default=None, max_length=2)
        nodes: list[NodeTask] = Field(max_length=64)

    class NodeResponse(StrictModel):
        node: CreativeNodePatch

    checkpoint = checkpoint if checkpoint is not None else {}
    save_checkpoint = save_checkpoint or (lambda: None)
    existing = {n['id']: n for n in request.current_plan.get('nodes', [])}
    revising = bool(existing)
    calls = 0
    # Retain original intent, selected assets, tool observations and repair
    # feedback, but replace the conflicting full-graph response contract.
    base = copy.deepcopy(messages)
    base[0].content = base[0].content.split('\nJSON schema:\n', 1)[0]
    base[0].content += '\n本轮改用系统分段协议；下方的分段schema取代前述reply/plan/patch输出形状。只使用已有资料，禁用检索和生成工具。全部分段结束并通过完整校验前，均未提交或批准。'

    async def piece(model, name, instruction, validate, context=None, schema=None):
        nonlocal calls
        schema = schema or model.model_json_schema()
        current = [*base, LLMMessage(role='system', content=instruction + '\n本段JSON schema:\n' + json.dumps(schema, ensure_ascii=False))]
        if context is not None:
            current.append(LLMMessage(role='user', content=json.dumps(context, ensure_ascii=False)))
        for attempt in range(2):
            if calls >= MAX_PARTITION_CALLS:
                raise PlanningOutputTruncated()
            calls += 1
            try:
                response = await complete(current, schema, name)
                if response.tool_calls:
                    raise ValueError('分段只允许返回本段JSON，不能调用工具')
                value = model.model_validate(decode_proposal(response.content))
                validate(value)
                return value
            except (PlanningOutputTruncated, ValueError, TypeError) as exc:
                if attempt:
                    raise PlanningOutputTruncated() from exc
                await report('retry', '当前分段未完整通过校验，正在缩小输出并自动重试（1/1）')
                details = '输出被截断' if isinstance(exc, PlanningOutputTruncated) else json.dumps(validation_details(exc), ensure_ascii=False)[:2500]
                # Never append a half-written node or ask for a textual continuation.
                current.append(LLMMessage(role='user', content='本段未通过：' + details + '。重新返回本段完整JSON；不输出其他节点、重复背景、生成状态或额外建议。简化叙述但保留用户明确要求、对白和引用。'))

    def validate_manifest(value):
        ids = [n.id for n in value.nodes]
        if len(ids) != len(set(ids)) or len(set(existing) | set(ids)) > 64:
            raise ValueError('节点ID不能重复，完整画布最多64个节点')
        if not revising and (not value.title or not value.summary):
            raise ValueError('新画布必须提供title和summary')
        if revising and value.workflow_template_id is not None:
            raise ValueError('本轮修改不能切换已有工作流模板')
        for node in value.nodes:
            if request.automatic_mode and node.id in request.locked_node_ids:
                raise ValueError('不能修改已确认节点：' + node.id)
            if node.id in existing and node.kind != existing[node.id]['kind']:
                raise ValueError('不能改变已有节点类型：' + node.id)
            if request.repair and node.id not in existing and node.kind != 'image':
                raise ValueError('自动返工只能补充必要的场景图片节点')

    await report('partition', '方案较长，已自动改为分段规划：先确定修改范围，再逐个补齐节点')
    if checkpoint.get('manifest'):
        manifest = Manifest.model_validate(checkpoint['manifest'])
        validate_manifest(manifest)
        await report('partition_resume', f'从中断节点继续规划，保留已完成的{len(checkpoint.get("nodes", []))}个节点和已读取资料')
    else:
        manifest = await piece(Manifest, 'creation_manifest',
            '只输出本轮修改清单与简短回复，不输出任何节点正文、脚本或storyboard。nodes每项仅id、kind、instruction，列全本轮确实需要新增或修改的节点，按依赖顺序排列；已有无关节点、已锁定节点不要列入。不能为了缩短输出省略本轮需要的片段、角色或场景。title/summary/questions仅需修改时提供，新建画布必须有title和summary；已有画布workflow_template_id填null。questions保留尚未解决的新问题，已解决返回[]。', validate_manifest)
        checkpoint.update(manifest=manifest.model_dump(), nodes=[], observations=[m.model_dump() for m in messages[2:] if m.role == 'tool' or m.tool_calls])
        save_checkpoint()
    header = manifest.model_dump(exclude_none=True, exclude={'nodes', 'reply'})
    nodes = []
    for index, task in enumerate(manifest.nodes):
        await report('partition', f'正在补齐创作节点（{index + 1}/{len(manifest.nodes)}）')
        def validate_node(value):
            data = value.node.model_dump(exclude_unset=True)
            if value.node.id != task.id:
                raise ValueError('仅允许当前节点：' + task.id)
            merged = {**existing.get(task.id, {}), **data}
            node = CreativeNode.model_validate(merged)
            if node.kind != task.kind:
                raise ValueError('必须保持清单中的节点类型')
            if node.kind == 'text' and not node.content.strip():
                raise ValueError('文本节点必须包含完整审阅正文')
            if node.kind == 'image' and not node.asset_id and not node.prompt.strip():
                raise ValueError('图片节点必须提供生成提示词或已有资产')
        saved = checkpoint.get('nodes', [])
        if index < len(saved):
            value = NodeResponse.model_validate({'node': saved[index]})
            validate_node(value)
            nodes.append(value.node.model_dump(exclude_unset=True))
            continue
        schema = NodeResponse.model_json_schema()
        from agent.aigc.creation_contract import node_schema
        schema['$defs']['CreativeNodePatch'] = node_schema(schema, task.kind, patch=True, ident=task.id)
        value = await piece(NodeResponse, 'creation_node',
            '只返回{"node":当前一个节点的变更字段}；已有节点保持原id、kind，只写需要修改的字段（其余null）；新增节点必须完整。content和storyboard一旦修改就提供完整字段，不能省略尾部。禁止跨节点输出。视频只写本段storyboard，不重复prompt；简短中文content指向脚本，不复制完整分镜。保持时间线、对白和参考职责，执行文本尽量少于3000字符。文本脚本使用紧凑中文审阅稿，保留明确要求，不逐段重复制作简报。revision_suggestions填null，界面已有修改方向，不在恢复时重复生成。',
            validate_node, context=dict(manifest=manifest.model_dump(exclude_none=True), current_task=task.model_dump(), completed_nodes=nodes), schema=schema)
        nodes.append(value.node.model_dump(exclude_unset=True))
        checkpoint['nodes'] = copy.deepcopy(nodes)
        save_checkpoint()
    checkpoint.clear()
    return json.dumps(dict(reply=manifest.reply, **{('patch' if revising else 'plan'): dict(**header, nodes=nodes)}), ensure_ascii=False)
