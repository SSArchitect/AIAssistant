"""Bound unsuccessful edit chains using actual execution and review history."""


def exhausted_edit_task(request):
    repair = request.repair
    if not request.automatic_mode or not repair or len(repair.previous_attempts) < 2:
        return None
    node = next((n for n in request.current_plan.get('nodes', []) if n['id'] == repair.node_id), None)
    if not node or node.get('kind') != 'image' or node['id'] in request.locked_node_ids:
        return None
    chain = [*repair.previous_attempts[-2:], repair]
    persisting = None
    for index, attempt in enumerate(chain):
        execution = attempt.execution
        candidates = set(attempt.candidate_ids)
        if (not execution or execution.operation != 'edit' or not execution.edit_source_asset_id
                or not candidates or {f.candidate_id for f in attempt.findings} != candidates):
            return None
        if index and (attempt.attempt != chain[index - 1].attempt + 1
                or execution.edit_source_asset_id not in chain[index - 1].candidate_ids):
            return None
        # A category alone can describe unrelated requirements. A reviewer may
        # quote a sentence or its exact subclause; match nested literal quotes.
        issues = {(f.category, f.source_id, f.requirement_quote) for f in attempt.findings}
        persisting = issues if persisting is None else {
            (old[0], old[1], min((old[2], new[2]), key=len))
            for old in persisting for new in issues
            if old[:2] == new[:2] and old[2] and new[2]
            and (old[2] in new[2] or new[2] in old[2])}
    if not persisting:
        return None
    return dict(operation='replan_generation',
        persisting_categories=sorted({issue[0] for issue in persisting}),
        instruction='连续三次编辑仍未通过同一验收要求。本轮必须更换操作：清空该节点edit_source_asset_id，'
        '基于原始验收要求、已确认参考和实际失败历史重新设计生成方案，必要时增加明确分工的前置参考。'
        '不能再把上一张失败图作为编辑来源重复提交，不能只把原编辑指令换一种说法。'
        '保留冻结content、锁定节点及交付数量，不放宽验收、不把失败图提升为参考。新候选仍需完整复审。')
