"""Route regional repair to the fields actually consumed by the image tool."""


def region_repair_task(request):
    if not request.automatic_mode or not request.repair:
        return None
    node = next((n for n in request.current_plan.get('nodes', []) if n['id'] == request.repair.node_id), None)
    if not node or not node.get('image_layout'):
        return None
    return dict(operation='regional_image', execution_fields=['image_layout', 'references'],
        instruction='当前实际生图使用image_layout[0].subject_prompt以及位置/比例，普通prompt不参与区域生成。'
        '请针对真实反馈修改有效字段，或更换确有问题的参考；不能只修改普通prompt后声称返工已生效。'
        '主体描述保持局部，仅写角色、道具、姿态和视线方向，不重述画外景物。'
        '需要切换到整图生成须显式清空image_layout=[]并解释原因，不因原图小主体问题回到已失败的同一种策略。'
        '保持冻结验收与已确认节点，结果仍需正常审阅。')


def validate_region_repair(plan, request):
    if not request.automatic_mode or not request.repair:
        return
    from agent.aigc.creation_planning import CreativePlan
    from agent.aigc.creation_output import omit_null_fields
    before = {n.id: n for n in CreativePlan.model_validate(omit_null_fields(request.current_plan)).nodes}
    after = {n.id: n for n in plan.nodes}
    old, new = before.get(request.repair.node_id), after.get(request.repair.node_id)
    if not old or not new or not old.image_layout or not new.image_layout:
        return
    fields = ('image_layout', 'references', 'aspect_ratio', 'depends_on')
    if any(getattr(old, key) != getattr(new, key) for key in fields):
        return
    # An upstream node may produce new reference pixels without changing its ID.
    pending, seen = list(new.depends_on), set()
    while pending:
        ident = pending.pop()
        if ident in seen:
            continue
        seen.add(ident)
        a, b = before.get(ident), after.get(ident)
        if not a or not b or a != b:
            return
        pending.extend(b.depends_on)
    raise ValueError('节点 ' + new.id + ' 使用image_layout区域生成，本次有效执行内容未变。'
        '请修改image_layout中的subject_prompt/位置/比例或有效参考；只修改普通prompt不会生效。')
