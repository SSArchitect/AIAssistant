import copy
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.aigc import creation_planning as planning, creation_checkpoint as checkpoint
from agent.aigc.creation_models import PlanningOutputTruncated
from agent.llm.base import LLMResponse, ToolCall
from agent.skills.base import SkillResult
from tests.test_creation_planning import request, plan
from tests.test_creation_partition import answer, manifest


@pytest.fixture(autouse=True)
def clean_cache(monkeypatch):
    monkeypatch.setattr(checkpoint, '_CACHE', checkpoint.OrderedDict())


@pytest.mark.asyncio
async def test_outer_retry_resumes_failed_node_without_repeating_completed_nodes_or_reads(monkeypatch):
    original = plan(); original['workflow_template_id'] = ''
    read=AsyncMock(return_value=SkillResult(success=True,data={'content':'SOURCE: original script'}))
    skills=planning.director_tools();monkeypatch.setattr(skills['read_drive'],'execute',read)
    monkeypatch.setattr(planning,'director_tools',lambda:skills)
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(tool_calls=[ToolCall(id='read',name='read_drive',arguments={'item_id':'source'})]),
        LLMResponse(finish_reason='length'),answer(manifest(original['nodes'])),answer({'node':original['nodes'][0]}),
        LLMResponse(finish_reason='length'),LLMResponse(finish_reason='length')]))
    monkeypatch.setattr(planning,'create_provider',lambda:provider)
    req=request()
    with pytest.raises(PlanningOutputTruncated): await planning.propose_creation(req)
    retry=req.model_copy(update={'recovery':planning.PlanningRecovery(attempt=1,error_code='planning_output_truncated',max_seconds=240)})
    assert len(checkpoint.load(retry)['nodes'])==1
    provider.chat=AsyncMock(return_value=answer({'node':original['nodes'][1]}))
    events=[]
    async def report(event):events.append(event)
    result=await planning.propose_creation(retry,on_progress=report)
    assert provider.chat.await_count==1 and read.await_count==1
    dialogue=provider.chat.call_args.args[0]
    assert 'SOURCE: original script' in str(dialogue)
    assert [n.id for n in result.plan.nodes]==['script','video']
    assert any(e['stage']=='partition_resume' for e in events)
    assert not checkpoint.load(retry)


@pytest.mark.parametrize('change', ['user_id','project_id','messages','assets','locked_node_ids','current_plan'])
def test_checkpoint_is_bound_to_account_and_complete_request(change):
    req=request();checkpoint.save(req,{'manifest':{'nodes':[]},'nodes':[]})
    value=copy.deepcopy(req.model_dump());value['recovery']={'attempt':1,'error_code':'invalid_plan','max_seconds':200}
    if change in ('user_id','project_id'):value[change]='other'
    elif change=='messages':value[change]=[{'role':'user','content':'different choice'}]
    elif change=='assets':value[change]=[]
    elif change=='locked_node_ids':value[change]=['script']
    else:value[change]=plan()
    assert checkpoint.load(planning.PlanningRequest.model_validate(value))=={}


def test_fresh_request_drops_previous_checkpoint_and_expired_or_oversized_entries_are_not_reused(monkeypatch):
    req=request();checkpoint.save(req,{'nodes':[{'id':'script'}]})
    retry=req.model_copy(update={'recovery':planning.PlanningRecovery(attempt=1,error_code='invalid_plan')})
    assert checkpoint.load(retry)
    assert checkpoint.load(req)=={} and checkpoint.load(retry)=={}
    checkpoint.save(req,{'nodes':[]});monkeypatch.setattr(checkpoint,'TTL_SECONDS',0)
    assert checkpoint.load(retry)=={}
    monkeypatch.setattr(checkpoint,'MAX_ENTRY_BYTES',10)
    checkpoint.save(req,{'nodes':['long draft over cache limit']})
    assert not checkpoint._CACHE


def test_cache_evicts_old_entries_and_copies_values(monkeypatch):
    monkeypatch.setattr(checkpoint,'MAX_TOTAL_BYTES',60)
    first=request(); second=request().model_copy(update={'project_id':'other'})
    data={'nodes':['12345678901234567890']}
    checkpoint.save(first,data);data['nodes'].append('changed after save')
    retry=first.model_copy(update={'recovery':planning.PlanningRecovery(attempt=1,error_code='invalid_plan')})
    assert checkpoint.load(retry)['nodes']==['12345678901234567890']
    checkpoint.save(second,{'nodes':['12345678901234567890']})
    assert not checkpoint.load(retry) and len(checkpoint._CACHE)==1
