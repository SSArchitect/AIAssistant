"""Working drafts retain provenance without becoming approved references."""

DRAFT_EDIT_GUIDANCE = '''
图片返工有两种操作：重新生成，或编辑当前节点的待修草稿。候选已基本符合身份、环境与构图、仅有可局部修正的问题（如人物占比）时，优先考虑局部编辑，避免整张重画丢失正确内容。
局部编辑使用edit_source_asset_id填写本轮repair.candidate_ids中的一张真实候选；prompt仅写基于Picture 1的具体修改、必须保留的内容和原目标。references、depends_on、画幅保持不变，character_style与asset_id为空。系统只向编辑器传该草稿像素，不重新注入原人设或场景；原references继续作为复审依据。无法在现有草稿中可靠修正的身份混淆、整体场景错误应重新生成，明确edit_source_asset_id=""并恢复完整生成prompt。不要承诺像素完全不变，不放宽冻结要求。新图是未审阅候选，不能直接批准，也不能把旧失败图放进其他节点的asset_id或references。
'''


def validate_edit_sources(plan, request):
    from agent.aigc.creation_planning import CreativePlan
    from agent.aigc.creation_output import omit_null_fields
    if not any(n.edit_source_asset_id for n in plan.nodes):
        return
    previous = {n.id: n for n in CreativePlan.model_validate(omit_null_fields(request.current_plan)).nodes}
    proposed = {n.id: n for n in plan.nodes}
    for node in plan.nodes:
        source = node.edit_source_asset_id
        if not source:
            continue
        before = previous.get(node.id)
        if not before or before.kind != 'image':
            raise ValueError('编辑草稿必须来自当前已有图片节点：' + node.id)
        for field in ('references', 'depends_on', 'aspect_ratio'):
            if getattr(before, field) != getattr(node, field):
                raise ValueError('局部编辑不能同时改变原参考关系或画幅，请清空edit_source_asset_id后重新生成：' + node.id)
        pending, seen = list(node.depends_on), set()
        while pending:
            dep = pending.pop()
            if dep in seen:
                continue
            seen.add(dep)
            old, new = previous.get(dep), proposed.get(dep)
            if not old or not new or old.model_dump(exclude={'revision_suggestions'}) != new.model_dump(exclude={'revision_suggestions'}):
                raise ValueError('局部编辑不能同时更换上游内容，请清空edit_source_asset_id后重新生成：' + node.id)
            pending.extend(new.depends_on)
        if source == before.edit_source_asset_id:
            continue
        if node.id in request.locked_node_ids:
            raise ValueError('不能编辑已确认节点的草稿：' + node.id)
        if request.repair:
            allowed = request.repair.candidate_ids if request.automatic_mode and request.repair.node_id == node.id else []
        else:
            state = request.node_context.get(node.id, {})
            allowed = [state.get('selected_asset_id', '')] + state.get('candidate_asset_ids', [])
        if source not in allowed:
            raise ValueError('待修草稿必须是当前节点自己的候选：' + node.id)
