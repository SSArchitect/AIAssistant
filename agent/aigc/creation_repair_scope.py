"""Automatic repair can fill prerequisites without changing the delivery graph."""


def validate_repair_scope(plan, request):
    if not request.automatic_mode:
        raise ValueError('自动返工需要一键生成上下文')
    original = request.current_plan.get('nodes', [])
    before = {n['id']: n for n in original}
    surviving = [(n.id, n.kind) for n in plan.nodes if n.id in before]
    if surviving != [(n['id'], n['kind']) for n in original]:
        raise ValueError('返工不能删除、重排原有节点或改变产物类型')
    affected = {request.repair.node_id}
    for node in original:
        if any(dep in affected for dep in node.get('depends_on', [])):
            affected.add(node['id'])
    linked = {ref.node_id for n in plan.nodes if n.id in affected and n.id not in request.locked_node_ids
              and n.kind == 'video' for ref in n.references if ref.role == 'reference'}
    rejected = set(request.repair.candidate_ids)
    for node in plan.nodes:
        if node.id not in before and (node.kind != 'image' or node.purpose != 'scene' or node.count != 1 or node.id not in linked):
            raise ValueError('返工只能补充受影响视频实际引用的场景图片，不能新增交付或无关节点：' + node.id)
        if node.asset_id in rejected or any(ref.asset_id in rejected for ref in node.references):
            raise ValueError('返工不能把已拒绝候选作为成品或生成参考：' + node.id)
