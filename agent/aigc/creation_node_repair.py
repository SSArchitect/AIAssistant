"""Repair individual draft nodes, preserving every other pending edit atomically."""
import copy
import json
import re

from agent.aigc.creation_contract import node_schema
from agent.aigc.creation_models import PlanningConstraintError, PlanningOutputTruncated
from agent.aigc.creation_output import validation_details
from agent.llm.base import LLMMessage


async def repair_draft_nodes(content, request, messages, completion, report, check, error):
    from agent.aigc.creation_planning import decode_proposal, assemble_proposal, RevisionResponse
    wire = decode_proposal(content)
    key = 'patch' if 'patch' in wire else 'plan'
    container = wire.get(key, {})
    drafts = container.get('nodes', [])
    if not isinstance(drafts, list) or not drafts or any(not isinstance(n, dict) or not n.get('id') for n in drafts):
        raise error
    existing = {n['id']: n for n in request.current_plan.get('nodes', [])}
    by_id = {n['id']: n for n in drafts}
    if len(by_id) != len(drafts):
        raise error
    merged = {ident: copy.deepcopy(node) for ident, node in existing.items()}
    for ident, node in by_id.items():
        merged[ident] = {**merged.get(ident, {}), **node}
    counts = {}
    # Original context and tool observations stay; failed giant assistant replies
    # do not get copied into every single-node request.
    base = copy.deepcopy(messages[:2] + [m for m in messages[2:] if m.role == 'tool' or m.tool_calls])
    base[0].content = base[0].content.split('\nJSON schema:\n', 1)[0]
    for _ in range(8):
        details = validation_details(error)
        targets = []
        for detail in details:
            loc = list(detail.get('loc', []))
            if 'nodes' in loc:
                i = loc.index('nodes')
                if i + 1 < len(loc) and isinstance(loc[i + 1], int):
                    # patch indices address the wire; full-plan indices include unchanged nodes.
                    source = drafts
                    if key == 'patch' and 'patch' not in loc:
                        try:
                            source = assemble_proposal(json.dumps(wire), request)['plan']['nodes']
                        except (ValueError, TypeError):
                            source = list(merged.values())
                    if loc[i + 1] < len(source):
                        targets.append(source[loc[i + 1]]['id'])
            targets.extend(ident for ident in by_id if re.search(r'(?<![\w-])' + re.escape(ident) + r'(?![\w-])', detail['msg']))
        targets = list(dict.fromkeys(targets)) or list(by_id)
        target = next((ident for ident in targets if ident in by_id and ident not in request.locked_node_ids and counts.get(ident, 0) < 3), None)
        if target is None:
            break
        kind = merged[target].get('kind')
        if kind not in ('text', 'image', 'video'):
            break
        counts[target] = counts.get(target, 0) + 1
        schema = RevisionResponse.model_json_schema()
        patch = schema['$defs']['CreativePlanPatch']
        patch['properties'] = {'nodes': {'type': 'array', 'minItems': 1, 'maxItems': 1,
            'items': node_schema(schema, kind, patch=True, ident=target,
                asset_ids=[a.id for a in request.assets if a.mime_type.startswith('image/')])}}
        patch['required'] = ['nodes']
        await report('node_repair', f'正在单独修正节点 {target}（{counts[target]}/3），保留其他修改')
        current = [*base, LLMMessage(role='system', content=
            '进入单节点修复协议，取代前述整图输出要求。仅返回reply和patch.nodes中的指定节点；只改错误字段，其他字段null。'
            '不改其他节点、项目标题、问题或交付。资产来源与节点来源二选一；文本节点没有媒体引用；场景时段仅属于视频的场景reference。'
            '新增场景已经在待提交草案中，不要重复创建。未显示图片只有目录，不能声称看过。\nJSON schema:\n' + json.dumps(schema, ensure_ascii=False)),
            LLMMessage(role='user', content=json.dumps(dict(target_node=merged[target], validation_errors=details,
                draft_nodes=list(merged.values())), ensure_ascii=False))]
        try:
            response = await completion(current, schema, 'creation_node_repair')
            if response.tool_calls:
                raise ValueError('单节点修复不能调用其他工具')
            correction = decode_proposal(response.content)
            validated = RevisionResponse.model_validate(correction)
            if validated.patch.model_fields_set != {'nodes'} or len(validated.patch.nodes) != 1 or validated.patch.nodes[0].id != target:
                raise ValueError('仅允许修正指定节点：' + target)
            change = validated.patch.nodes[0].model_dump(exclude_unset=True)
            if change.get('kind', kind) != kind:
                raise ValueError('不能改变节点类型：' + target)
            by_id[target].update(change)
            merged[target].update(change)
            wire['reply'] = validated.reply
            repaired, result = await check(json.dumps(wire, ensure_ascii=False))
            return repaired, result
        except (ValueError, TypeError, PlanningOutputTruncated) as exc:
            error = exc
    labels = '、'.join(counts)[:160]
    issue = '分镜时间' if 'Panels must cover' in str(error) else '节点内容与引用关系'
    raise PlanningConstraintError(f'节点 {labels} 的{issue}自动修复后仍未通过校验，修改草案未提交；已确认内容与资产保留，可继续创作或调整该节点') from error
