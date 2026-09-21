import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from agent.aigc import creation_planning as planning
from agent.aigc.creation_active_task import active_planning_task
from agent.llm.base import LLMResponse
from tests.test_creation_draft_edit import editing_request,patch
from tests.test_creation_image_layout import PLACEMENT


def request():
    req=editing_request()
    req.assets.append(planning.PlanningAsset(id='scene',name='环境',mime_type='image/png'))
    req.current_plan['nodes'][1]['references'].append(dict(asset_id='scene',role='environment'))
    req.current_plan['nodes'][1]['image_layout']=[PLACEMENT]
    return req


@pytest.mark.parametrize('changes',[{},dict(prompt='Add long white ears'),dict(title='New title'),dict(count=2)])
def test_inactive_field_or_empty_repair_cannot_trigger_same_regional_generation(changes):
    with pytest.raises(ValueError,match='image_layout.*普通prompt'):
        planning.parse_proposal(patch(**changes),request())


@pytest.mark.parametrize('changes',[
    dict(image_layout=[{**PLACEMENT,'subject_prompt':'A rear-view rabbit with complete long white ears'}]),
    dict(image_layout=[{**PLACEMENT,'center_x_percent':40}]),
    dict(image_layout=[]),
])
def test_real_local_changes_and_explicit_operation_switch_are_allowed(changes):
    assert planning.parse_proposal(patch(**changes),request()).plan.nodes[1].id=='frame'


def test_upstream_reference_generation_change_is_effective_repair():
    from agent.aigc.creation_region_repair import validate_region_repair
    req=request()
    req.current_plan['nodes'].insert(1,dict(id='scene',kind='image',purpose='scene',title='环境',prompt='old environment'))
    n=req.current_plan['nodes'][2];n['depends_on']=['scene'];n['references'][1]=dict(node_id='scene',role='environment')
    plan=planning.CreativePlan.model_validate(req.current_plan)
    plan.nodes[1].prompt='Corrected environment'
    validate_region_repair(plan,req)


def test_active_instruction_names_real_field_and_manual_regeneration_is_unchanged():
    req=request();task=json.loads(active_planning_task(req)['text'].split('\n',1)[1])
    assert task['current_operation']['operation']=='regional_image'
    assert 'subject_prompt' in task['current_operation']['instruction']
    req.automatic_mode=False;req.repair=None
    assert planning.parse_proposal(patch(prompt='Manual fallback prompt'),req)


@pytest.mark.asyncio
async def test_planner_corrects_inactive_prompt_patch_before_returning_an_executable_plan(monkeypatch):
    req=request();original=copy.deepcopy(req.model_dump())
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content=patch(prompt='Make ears longer')),
        LLMResponse(content=patch(image_layout=[{**PLACEMENT,'subject_prompt':'Complete long white rabbit ears and rear view'}]))
    ]))
    monkeypatch.setattr(planning,'create_provider',lambda:provider)
    result=await planning.propose_creation(req)
    assert provider.chat.await_count==2
    assert result.plan.nodes[1].image_layout[0].subject_prompt.startswith('Complete long')
    assert req.model_dump()==original
