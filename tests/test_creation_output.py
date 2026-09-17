import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest
from agent.aigc.creation_output import strict_schema, omit_null_fields, structured_options
from agent.aigc.creation_planning import PlanProposal, RevisionResponse, parse_proposal
from agent.llm.base import LLMMessage
from agent.llm.base import LLMResponse
from agent.llm.doubao_provider import DoubaoProvider
from tests.test_creation_planning import plan, request


def test_strict_contract_closes_all_objects_and_null_means_no_patch():
    for model in [PlanProposal, RevisionResponse]:
        schema = strict_schema(model.model_json_schema())
        assert 'title' in schema['$defs']['CreativePlan']['properties'] if model is PlanProposal else 'nodes' in schema['$defs']['CreativePlanPatch']['properties']
        def check(value):
            if isinstance(value, list):
                for item in value: check(item)
            if not isinstance(value, dict): return
            if value.get('type') == 'object':
                assert value['additionalProperties'] is False
                assert set(value['required']) == set(value['properties'])
            assert 'default' not in value
            for item in value.values(): check(item)
        check(schema)
    original = plan()
    value = {'reply':'完成', 'patch':{'nodes':[{'id':'script','content':'新的脚本','storyboard':None,'depends_on':None}], 'title':None,'questions':None}}
    result = parse_proposal(json.dumps(value), request(current_plan=original))
    assert result.plan.title == original['title']
    assert result.plan.nodes[0].content == '新的脚本'
    assert result.plan.nodes[1].storyboard.shots[0].description == original['nodes'][1]['storyboard']['shots'][0]['description']


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
async def test_schema_sent_on_wire_with_tools_without_affecting_normal_chat(streaming):
    provider = DoubaoProvider(api_key='test', model='doubao-seed-2.1-turbo')
    calls=[]
    def handler(req):
        payload=json.loads(req.content);calls.append(payload)
        if streaming:
            chunk={'choices':[{'delta':{'content':'{}'},'finish_reason':'stop'}]}
            return httpx.Response(200, text='data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n',headers={'content-type':'text/event-stream'})
        return httpx.Response(200,json={'model':'test','choices':[{'message':{'role':'assistant','content':'{}'},'finish_reason':'stop'}]})
    await provider.client.close()
    provider.client=openai.AsyncOpenAI(api_key='test',http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        options=structured_options(provider,RevisionResponse.model_json_schema(),'creation_revision')
        messages=[LLMMessage(role='user',content='Return JSON')]
        if streaming:
            _=[x async for x in provider.chat_stream_response(messages,**options)]
            _=[x async for x in provider.chat_stream_response(messages)]
        else:
            await provider.chat(messages,**options);await provider.chat(messages)
        assert calls[0]['response_format']['json_schema']['strict'] is True
        assert 'response_format' not in calls[1]
    finally:await provider.client.close()


def test_automatic_replanning_cannot_modify_user_locked_nodes():
    original=plan()
    req=request(current_plan=original,automatic_mode=True,locked_node_ids=['script'])
    value={'reply':'修改完成','patch':{'nodes':[{'id':'script','content':'擅自覆盖'}]}}
    with pytest.raises(ValueError,match='已确认节点'):
        parse_proposal(json.dumps(value),req)
    value['patch']['nodes']=[];value['patch']['questions']=[]
    assert parse_proposal(json.dumps(value),req).plan.nodes[0].content==original['nodes'][0]['content']


@pytest.mark.asyncio
@pytest.mark.parametrize('unsupported', [True, False])
async def test_planner_only_downgrades_explicit_unsupported_schema_and_keeps_json_constraint(monkeypatch, unsupported):
    from agent.aigc import creation_planning as planning
    provider=DoubaoProvider(api_key='test',model='glm-5.3')
    error=openai.BadRequestError('unsupported',response=httpx.Response(400,request=httpx.Request('POST','https://example.test')),
        body={'error':{'message':'response_format json_schema is not supported' if unsupported else 'Invalid credentials parameter'}})
    provider.chat=AsyncMock(side_effect=[error,LLMResponse(content=json.dumps({'reply':'请审阅','plan':plan()}))])
    monkeypatch.setattr(planning,'create_provider',lambda:provider)
    try:
        if unsupported:
            result=await planning.propose_creation(request())
            assert result.plan.nodes[-1].kind=='video'
            assert [c.kwargs['response_format']['type'] for c in provider.chat.call_args_list]==['json_schema','json_object']
        else:
            with pytest.raises(openai.BadRequestError): await planning.propose_creation(request())
            assert provider.chat.await_count==1
    finally:await provider.client.close()


@pytest.mark.asyncio
async def test_semantic_timeline_failure_is_distinct_from_json_format_error(monkeypatch):
    from agent.aigc import creation_planning as planning
    from agent.aigc.creation_models import PlanningConstraintError,planning_error
    value=plan()
    value['nodes'][-1]['storyboard']['shots'][0]['panels']=[dict(start_seconds=1.,end_seconds=5.,description='A rabbit bows.')]
    provider=SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps({'reply':'review','plan':value}))))
    monkeypatch.setattr(planning,'create_provider',lambda:provider)
    with pytest.raises(PlanningConstraintError) as caught:await planning.propose_creation(request())
    code,message=planning_error(caught.value)
    assert code=='plan_constraint_failed' and '分镜时间' in message and '格式校验失败' not in message
    assert provider.chat.await_count==2
