"""Working drafts retain provenance without becoming approved references."""

DRAFT_EDIT_GUIDANCE = '''
图片返工有两种操作：重新生成，或编辑当前节点的待修草稿。候选已基本符合身份、环境与构图、仅有可局部修正的问题（如人物占比）时，优先考虑局部编辑，避免整张重画丢失正确内容。
局部编辑使用edit_source_asset_id填写本轮repair.candidate_ids中的一张真实候选；prompt仅写基于Picture 1的具体修改、必须保留的内容和原目标。references、depends_on、画幅保持不变，character_style与asset_id为空。系统只向编辑器传该草稿像素，不重新注入原人设或场景；原references继续作为复审依据。无法在现有草稿中可靠修正的身份混淆、整体场景错误应重新生成，明确edit_source_asset_id=""并恢复完整生成prompt。不要承诺像素完全不变，不放宽冻结要求。新图是未审阅候选，不能直接批准，也不能把旧失败图放进其他节点的asset_id或references。
一次编辑集中修正一个主要问题，其他内容显式保留；存在比例问题时先只缩放主体与随身道具整体，保留当前姿态，不同时重塑朝向、表情、服装或重述完整角色设计。比例合格后再改动作，尺寸与背景保持。后续仍按全部原要求复审，未处理的问题不能遗忘、删除或降低标准；编辑未生效时分析实际结果再调整操作，不宣称已完成。
'''


def localized_repair_guidance(request):
    """Choose a different operation after repeated, localized output failures.

    Do not compete with the staged identity strategy when the review reports
    global defects, the source is unavailable, or an edit is already underway.
    """
    repair = request.repair
    if not request.automatic_mode or not repair or repair.attempt < 3 or not repair.findings:
        return ''
    node = next((n for n in request.current_plan.get('nodes', []) if n['id'] == repair.node_id), None)
    if (not node or node.get('kind') != 'image' or node.get('purpose') != 'shot_reference'
            or node['id'] in request.locked_node_ids or node.get('edit_source_asset_id')):
        return ''
    candidates = set(repair.candidate_ids)
    visible = {a.id for a in request.assets if a.data_url}
    if (not candidates or not candidates <= visible
            or {f.candidate_id for f in repair.findings} != candidates
            or any(f.category not in {'scale', 'action', 'composition'} for f in repair.findings)
            or any(f.category == 'composition' and f.source_id.endswith(':environment') for f in repair.findings)):
        return ''
    return ('\n本轮返工策略：切换为编辑现有草稿。此前已多次返工，本次有可见成图，审阅指出的问题仅是主体比例、动作或构图关系，没有身份或环境错误；'
        '不要再次仅给整图生成prompt增加CRITICAL/EXACTLY或否定词。先选本节点一张candidate作为edit_source_asset_id，'
        '通过Picture 1编辑主体的大小、朝向、头部姿态、视线、站位或脚与道具关系，同时明确保留正确场景、身份和其余内容。'
        '比例修正同时写目标占比与相对当前尺寸的缩放关系；不要改画幅或移动摄影机来伪造尺寸达标。'
        '本轮不新增或重做已经确认的姿态前置图，不重接原始人设像素；content与原references/dependencies保持。'
        '编辑完成后仍按全部原要求复审；这只是改变返工操作，不代表草稿已经合格或保证编辑一定成功。')


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
        # The planner often paraphrases reference notes for the current edit.
        # Notes are not editor-owned: retain exact baseline notes when all real
        # bindings/roles are unchanged, instead of asking the model to copy prose.
        if (request.automatic_mode and request.repair and
                [r.model_dump(exclude={'note'}) for r in before.references] ==
                [r.model_dump(exclude={'note'}) for r in node.references]):
            node.references = [r.model_copy(deep=True) for r in before.references]
        for field in ('references', 'depends_on', 'aspect_ratio'):
            if getattr(before, field) != getattr(node, field):
                raise ValueError('节点 ' + node.id + ' 的局部编辑改变了只读字段 ' + field +
                    '；请在patch中将该字段完整恢复为current_plan同节点的原值（包括原note），或清空edit_source_asset_id后重新生成。')
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


def draft_edit_task(request):
    """Separate this edit operation from all remaining acceptance findings."""
    repair = request.repair
    if not request.automatic_mode or not repair or not repair.findings:
        return None
    node = next((n for n in request.current_plan.get('nodes', []) if n['id'] == repair.node_id), None)
    if not node or node['id'] in request.locked_node_ids or node.get('kind') != 'image':
        return None
    if not node.get('edit_source_asset_id') and not localized_repair_guidance(request):
        return None
    candidates = set(repair.candidate_ids)
    if (not candidates or not candidates <= {a.id for a in request.assets if a.data_url}
            or {f.candidate_id for f in repair.findings} != candidates
            or any(f.category not in {'scale', 'action', 'composition'} or f.source_id.endswith(':environment') for f in repair.findings)):
        return None
    focus = next(category for category in ('scale', 'action', 'composition') if any(f.category == category for f in repair.findings))
    return dict(operation='edit_draft', focus=focus, candidate_ids=repair.candidate_ids,
        active_findings=[f.model_dump() for f in repair.findings if f.category == focus],
        deferred_findings=[f.model_dump() for f in repair.findings if f.category != focus],
        instruction='本轮prompt只处理active_findings；deferred_findings保留给下一轮，不能混入本轮编辑指令。'
        'focus=scale时仅等比缩放主体与道具整体，写当前尺寸的缩放比例和目标画高占比，明确保留现有姿态、朝向、表情、身份与场景。'
        '不要因deferred_findings要求旋转或重塑角色，不复述完整人设。不改变原验收内容、参考或画幅。每轮仍复审全部要求。')
