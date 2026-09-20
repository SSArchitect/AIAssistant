"""Choose a staged reference workflow after repeated identity or action failures."""


def reference_preparation_guidance(request):
    repair=request.repair
    if not request.automatic_mode or not repair or repair.attempt<3:return ''
    node=next((n for n in request.current_plan.get('nodes',[]) if n['id']==repair.node_id),None)
    if not node or node['id'] in request.locked_node_ids or node.get('kind')!='image' or node.get('purpose')!='shot_reference':return ''
    if not any(r.get('role')=='identity' for r in node.get('references',[])):return ''
    if not any(f.category in {'identity','action'} for f in repair.findings):return ''
    return ('\n当前分镜已多次因身份或动作不符返工，需要分步准备参考，不能继续只堆叠否定词：'
        '先查看是否已有符合目标姿态的单角色参考。没有时优先新增一个实际被本分镜引用的character前置图片节点，count=1、同画幅、character_style为空，'
        '仅引用已确认人物身份，在中性无场景背景中先生成目标机位、动作、视线、脚与道具接触的单角色参考。'
        '前置图让人物足够清楚以审阅身份和动作；不要把最终场景的极小占比要求加在这张动作准备图上。'
        '最终分镜改以该已审阅前置图为identity参考，并与自己的environment组合，补齐depends_on；原人物身份来源保留在前置节点的依赖链。'
        '最终分镜的原始动作、比例和场景验收要求不变。不要继续同时输入原多视图稿来抵消已准备的姿态。'
        '已有相应前置节点时优先复用或修正未确认节点，不为同一问题重复增加辅助图。只提交真实节点和依赖，不宣称辅助图已生成。')


def bind_prepared_identity(plan,request):
    """Keep identity pixels when a new pose helper replaces the same identity.

    The existing composition+environment path intentionally extracts semantics
    from a different scene. A new single-character prerequisite inherits the
    original identity instead; it must not lose its pixels through that path.
    Keep a previously established identity helper across later repairs too.
    Never reinterpret a user's composition reference or a different identity.
    """
    retain_prepared_identity(plan,request)
    if not reference_preparation_guidance(request):return
    originals={n['id']:n for n in request.current_plan.get('nodes',[])}
    target=next((n for n in plan.nodes if n.id==request.repair.node_id),None)
    if not target:return
    if any(r.role=='identity' for r in target.references):return
    original_sources={(r.get('asset_id') or '',r.get('node_id') or '') for r in originals[target.id].get('references',[]) if r.get('role')=='identity'}
    nodes={n.id:n for n in plan.nodes}
    for reference in target.references:
        helper=nodes.get(reference.node_id)
        if not helper or helper.id in originals or helper.purpose!='character' or reference.role!='composition':continue
        sources={(r.asset_id,r.node_id) for r in helper.references if r.role=='identity'}
        if sources and sources==original_sources:
            reference.role='identity'


def retain_prepared_identity(plan,request):
    """An automatic replan must not undo the staged reference it already uses.

    Only an existing identity binding establishes provenance. A character node
    that was previously composition remains composition. The original sheet is
    retained in the helper's dependency chain, not redundantly reintroduced to
    the final shot. Independently present identities stay intact.
    """
    if not request.automatic_mode or not request.repair or request.repair.node_id in request.locked_node_ids:return
    originals={n['id']:n for n in request.current_plan.get('nodes',[])}
    nodes={n.id:n for n in plan.nodes}
    before=originals.get(request.repair.node_id);target=nodes.get(request.repair.node_id)
    if not before or not target or before.get('purpose')!='shot_reference':return
    source_key=lambda r:(r.get('asset_id') or '',r.get('node_id') or '')
    previous={source_key(r):r for r in before.get('references',[]) if r.get('role')=='identity'}
    redundant=set()
    for ref in target.references:
        helper_before=originals.get(ref.node_id);helper_after=nodes.get(ref.node_id)
        if ('',ref.node_id) not in previous or not helper_before or not helper_after:continue
        if helper_before.get('purpose')!='character' or helper_after.purpose!='character' or ref.role not in {'identity','composition'}:continue
        sources={source_key(r) for r in helper_before.get('references',[]) if r.get('role')=='identity'}
        if not sources or sources!={(r.asset_id,r.node_id) for r in helper_after.references if r.role=='identity'}:continue
        if ref.role=='composition':
            ref.role='identity'
            ref.note=previous[('',ref.node_id)].get('note','')
        redundant.update(sources-set(previous))
    if redundant:
        target.references=[r for r in target.references if r.role!='identity' or (r.asset_id,r.node_id) not in redundant]
