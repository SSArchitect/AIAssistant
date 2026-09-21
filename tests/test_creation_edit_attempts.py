import copy,json
import pytest
from agent.aigc import creation_planning as planning
from agent.aigc.creation_active_task import active_planning_task
from tests.test_creation_draft_edit import editing_request,patch


def repeated_edits():
    req=editing_request()
    req.repair.attempt=7
    req.repair.execution=planning.RepairExecution(operation='edit',edit_source_asset_id='draft-6')
    for number,source,output in [(5,'draft-4','draft-5'),(6,'draft-5','draft-6')]:
        finding=req.repair.findings[0].model_copy(update={'candidate_id':output})
        req.repair.previous_attempts.append(planning.RepairAttempt(attempt=number,candidate_ids=[output],findings=[finding],
            execution=planning.RepairExecution(operation='edit',edit_source_asset_id=source)))
    return req


def test_three_edit_failures_switch_operation_without_losing_acceptance():
    req=repeated_edits();before=copy.deepcopy(req.model_dump())
    task=json.loads(active_planning_task(req)['text'].split('\n',1)[1])
    assert task['current_operation']['operation']=='replan_generation'
    assert task['current_operation']['persisting_categories']==['scale']
    with pytest.raises(ValueError,match='连续三次'):
        planning.parse_proposal(patch(edit_source_asset_id='draft',prompt='Shrink again'),req)
    result=planning.parse_proposal(patch(edit_source_asset_id='',prompt='Generate the scene using a different composition'),req)
    assert not result.plan.nodes[1].edit_source_asset_id
    assert result.plan.nodes[1].content==req.current_plan['nodes'][1]['content']
    assert req.model_dump()==before


def test_nested_literal_quotes_match_same_acceptance_requirement():
    from agent.aigc.creation_edit_attempts import exhausted_edit_task
    req=repeated_edits()
    req.repair.previous_attempts[0].findings[0].requirement_quote += '，脚踩飞剑。'
    assert exhausted_edit_task(req)['persisting_categories']==['scale']


@pytest.mark.parametrize('case',['unknown','only_two','generation','different_issue','different_quote','different_source','different_lineage','gap','missing_findings','manual','locked'])
def test_strategy_switch_requires_proven_consecutive_same_issue_edits(case):
    from agent.aigc.creation_edit_attempts import exhausted_edit_task
    req=repeated_edits()
    if case=='unknown':req.repair.previous_attempts[0].execution=None
    if case=='only_two':req.repair.previous_attempts.pop(0)
    if case=='generation':req.repair.previous_attempts[0].execution.operation='generate'
    if case=='different_issue':req.repair.previous_attempts[0].findings[0].category='environment'
    if case=='different_quote':req.repair.previous_attempts[0].findings[0].requirement_quote='Different scale target'
    if case=='different_source':req.repair.previous_attempts[0].findings[0].source_id='another-reference'
    if case=='different_lineage':req.repair.execution.edit_source_asset_id='different'
    if case=='gap':req.repair.previous_attempts[0].attempt=2
    if case=='missing_findings':req.repair.previous_attempts[0].findings=[]
    if case=='manual':req.automatic_mode=False
    if case=='locked':req.locked_node_ids.append('frame')
    assert exhausted_edit_task(req) is None


@pytest.mark.asyncio
async def test_planner_receives_operation_history_and_one_consistent_strategy(monkeypatch):
    from types import SimpleNamespace
    from unittest.mock import AsyncMock
    from agent.llm.base import LLMResponse
    req=repeated_edits()
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=patch(
        edit_source_asset_id='',prompt='Generate a wide composition with tiny rider'))))
    monkeypatch.setattr(planning,'create_provider',lambda:provider)
    await planning.propose_creation(req)
    messages=provider.chat.call_args.args[0]
    assert '连续三次编辑' in messages[0].content
    assert '本轮返工策略：切换为编辑现有草稿' not in messages[0].content
    assert '需要分步准备参考' not in messages[0].content
    assert 'draft-6' in str(messages[1].content) and 'previous_attempts' in str(messages[1].content)
