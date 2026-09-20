import copy,json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from agent.aigc import creation_planning as planning
from agent.aigc.creation_repair_strategy import reference_preparation_guidance,bind_prepared_identity
from agent.llm.base import LLMResponse
from tests.test_creation_planning import request
from tests.test_creation_shot_references import with_shot


def repeated():
    original=with_shot();original['nodes'][2]['content']='白兔站在剑上，背侧仰望'
    return request(current_plan=original,automatic_mode=True,locked_node_ids=['script','scene'],repair=dict(
        node_id='shot_frame',reason='身份和动作连续未成功',candidate_ids=[],attempt=3,previous_feedback=['正面而非背侧'],
        findings=[dict(candidate_id='failed',category='action',source_id='target',requirement_quote='背侧仰望',observation='正面平视')]))


@pytest.mark.parametrize('case',['manual','first_try','environment','no_identity','locked','character'])
def test_reference_preparation_does_not_expand_unrelated_or_early_repairs(case):
    req=repeated()
    if case=='manual':req.automatic_mode=False
    if case=='first_try':req.repair.attempt=1
    if case=='environment':req.repair.findings[0].category='environment'
    if case=='no_identity':req.current_plan['nodes'][2]['references']=[]
    if case=='locked':req.locked_node_ids.append('shot_frame')
    if case=='character':req.current_plan['nodes'][2]['purpose']='character'
    assert not reference_preparation_guidance(req)


@pytest.mark.asyncio
@pytest.mark.parametrize('model_role',['identity','composition'])
async def test_repeated_pose_failure_can_prepare_reusable_character_before_same_shot(monkeypatch,model_role):
    req=repeated();before=copy.deepcopy(req.model_dump())
    helper=dict(id='pose_ready',kind='image',purpose='character',title='单角色动作参考',content='单个白兔背侧仰望并踩剑，中性背景',
        prompt='One rabbit stands on the sword and looks upward, rear three-quarter view, plain background',
        count=1,aspect_ratio='9:16',references=[dict(asset_id='rabbit',role='identity')])
    shot=copy.deepcopy(req.current_plan['nodes'][2]);shot['references'][0]=dict(node_id='pose_ready',role=model_role);shot['depends_on'].append('pose_ready')
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(reply='先准备动作再组合场景',patch=dict(nodes=[helper,shot])))) ))
    monkeypatch.setattr(planning,'create_provider',lambda:provider)
    result=await planning.propose_creation(req)
    ids=[n.id for n in result.plan.nodes]
    assert ids.index('pose_ready')<ids.index('shot_frame')
    final=next(n for n in result.plan.nodes if n.id=='shot_frame')
    assert final.content=='白兔站在剑上，背侧仰望' and final.references[0].node_id=='pose_ready'
    assert final.references[0].role=='identity'
    assert final.references[1].node_id=='scene' and req.model_dump()==before
    assert '前置图让人物足够清楚' in provider.chat.call_args.args[0][0].content
    assert len([n for n in result.plan.nodes if n.kind=='video'])==1


@pytest.mark.parametrize('case',['old_helper','different_identity','another_identity_present','manual','missing_target'])
def test_binding_never_promotes_unrelated_existing_or_user_selected_identity(case):
    req=repeated()
    reference=SimpleNamespace(node_id='pose_ready',asset_id='',role='composition')
    helper=SimpleNamespace(id='pose_ready',purpose='character',references=[SimpleNamespace(asset_id='rabbit',node_id='',role='identity')])
    target=SimpleNamespace(id='shot_frame',references=[reference])
    proposed=SimpleNamespace(nodes=[helper,target])
    if case=='old_helper':helper.id='scene';reference.node_id='scene'
    if case=='different_identity':helper.references[0].asset_id='other-character'
    if case=='another_identity_present':target.references.append(SimpleNamespace(node_id='',asset_id='rabbit',role='identity'))
    if case=='manual':req.automatic_mode=False
    if case=='missing_target':proposed.nodes=[helper]
    bind_prepared_identity(proposed,req)
    assert reference.role=='composition'


@pytest.mark.parametrize('category',['scale','action'])
def test_later_repairs_keep_prepared_identity_pixels_and_do_not_reintroduce_its_original_sheet(category):
    from agent.aigc.creation_planning import CreativePlan
    req=repeated();req.repair.findings[0].category=category
    helper=dict(id='pose_ready',kind='image',purpose='character',title='动作参考',prompt='背侧站剑',references=[dict(asset_id='rabbit',role='identity')])
    req.current_plan['nodes'].insert(2,helper)
    target=next(n for n in req.current_plan['nodes'] if n['id']=='shot_frame')
    target['references'][0]=dict(node_id='pose_ready',role='identity',note='单个角色的身份和已准备姿态');target['depends_on'].append('pose_ready')
    changed=copy.deepcopy(req.current_plan)
    shot=next(n for n in changed['nodes'] if n['id']=='shot_frame')
    shot['references'][0]['role']='composition'
    shot['references'][0]['note']='只抽取构图语义，不带入身份或道具'
    shot['references'].append(dict(asset_id='rabbit',role='identity'))
    proposal=CreativePlan.model_validate(changed)
    bind_prepared_identity(proposal,req)
    result=next(n for n in proposal.nodes if n.id=='shot_frame')
    assert [(r.node_id,r.asset_id,r.role) for r in result.references]==[('pose_ready','','identity'),('scene','','environment')]
    assert 'pose_ready' in result.depends_on
    assert result.references[0].note=='单个角色的身份和已准备姿态'


def test_existing_prepared_identity_does_not_remove_an_unrelated_character():
    from agent.aigc.creation_planning import CreativePlan
    req=repeated()
    helper=dict(id='pose_ready',kind='image',purpose='character',title='动作参考',prompt='背侧站剑',references=[dict(asset_id='rabbit',role='identity')])
    req.current_plan['nodes'].insert(2,helper)
    target=next(n for n in req.current_plan['nodes'] if n['id']=='shot_frame')
    target['references'][0]=dict(node_id='pose_ready',role='identity');target['depends_on'].append('pose_ready')
    changed=copy.deepcopy(req.current_plan)
    shot=next(n for n in changed['nodes'] if n['id']=='shot_frame');shot['references'][0]['role']='composition'
    # An actual second identity must not disappear while restoring the first.
    shot['references'].append(dict(asset_id='asset-img',role='identity'))
    proposal=CreativePlan.model_validate(changed);bind_prepared_identity(proposal,req)
    result=next(n for n in proposal.nodes if n.id=='shot_frame')
    assert result.references[0].role=='identity'
    assert result.references[-1].asset_id=='asset-img'


@pytest.mark.parametrize('case',['manual','locked','different_source','previous_composition'])
def test_continuity_does_not_override_user_roles_locks_or_changed_identity(case):
    from agent.aigc.creation_planning import CreativePlan
    req=repeated()
    helper=dict(id='pose_ready',kind='image',purpose='character',title='动作',prompt='站剑',references=[dict(asset_id='rabbit',role='identity')])
    req.current_plan['nodes'].insert(2,helper)
    shot=next(n for n in req.current_plan['nodes'] if n['id']=='shot_frame')
    shot['references'][0]=dict(node_id='pose_ready',role='composition' if case=='previous_composition' else 'identity')
    shot['depends_on'].append('pose_ready')
    proposal=CreativePlan.model_validate(copy.deepcopy(req.current_plan))
    target=next(n for n in proposal.nodes if n.id=='shot_frame');target.references[0].role='composition'
    if case=='manual':req.automatic_mode=False
    if case=='locked':req.locked_node_ids.append('shot_frame')
    if case=='different_source':next(n for n in proposal.nodes if n.id=='pose_ready').references[0].asset_id='asset-img'
    bind_prepared_identity(proposal,req)
    assert target.references[0].role=='composition'
