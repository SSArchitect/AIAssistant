import copy,json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from agent.aigc.creation_active_task import active_planning_task
from agent.aigc import creation_planning as planning
from agent.llm.base import LLMResponse
from tests.test_creation_planning import request,plan


def task(req):
    return json.loads(active_planning_task(req)['text'].split('\n',1)[1])


def test_latest_explicit_change_is_separate_from_conflicting_old_instructions():
    req=request();req.messages=[dict(role='user',content='加回旧人设图')]+[dict(role='assistant',content='历史已处理')]*77+[
        dict(role='user',node_id='pose',content='保留动作图身份引用，移除旧人设直连'),dict(role='assistant',content='旧回复不能变成本轮指令')]
    before=copy.deepcopy(req.model_dump())
    assert task(req)['current_request']==req.messages[-2]
    assert '加回旧人设图' not in active_planning_task(req)['text']
    assert req.model_dump()==before


def test_automatic_repair_uses_feedback_instead_of_replaying_last_user_edit():
    req=request(automatic_mode=True,repair=dict(node_id='image',reason='姿态不符',candidate_ids=['bad'],attempt=4))
    req.messages=[dict(role='user',content='上一轮给另一个角色加帽子')]
    value=task(req)
    assert value['mode']=='automatic_repair' and value['repair']['node_id']=='image'
    assert '加帽子' not in active_planning_task(req)['text'] and 'current_request' not in value
    req.repair=None
    assert task(req)['mode']=='automatic_continue' and '加帽子' not in active_planning_task(req)['text']


@pytest.mark.asyncio
async def test_current_instruction_follows_asset_previews_and_survives_recovery_base(monkeypatch):
    from tests.test_creation_review_geometry import asset
    req=request();req.assets[0].name='old description';req.assets[0].data_url=asset().data_url
    req.messages=[dict(role='user',content='旧要求'),dict(role='assistant',content='已完成'),dict(role='user',node_id='script',content='执行这一次修改')]
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(reply='已修改',plan=plan())))))
    monkeypatch.setattr(planning,'create_provider',lambda:provider)
    await planning.propose_creation(req)
    messages=provider.chat.call_args.args[0];parts=messages[1].content
    assert len(messages)==2 and parts[-2]['type']=='image_url'
    assert json.loads(parts[-1]['text'].split('\n',1)[1])['current_request']==req.messages[-1]
    assert json.loads(parts[0]['text'])['messages']==req.messages


def test_empty_history_has_no_invented_request():
    req=request();req.messages=[]
    assert task(req)['current_request']=={}
