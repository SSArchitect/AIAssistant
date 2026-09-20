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
