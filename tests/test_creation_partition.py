import copy
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import openai
import pytest

from agent.aigc import creation_planning as planning
from agent.aigc import creation_completion, creation_partition
from agent.aigc.creation_models import PlanningOutputTruncated
from agent.llm.base import LLMResponse, LLMStreamChunk
from agent.trace.store import TraceStore
from tests.test_creation_planning import plan, request


def answer(value, **kwargs):
    return LLMResponse(content=json.dumps(value), model='test-planner', usage={'output': 10}, **kwargs)


def manifest(nodes, **kwargs):
    return dict(reply='分段准备完成，请审阅', title='竹林相逢', summary='一支克制的水墨短片', questions=[],
        nodes=[dict(id=n['id'], kind=n['kind'], instruction='落实当前节点的内容和引用') for n in nodes], **kwargs)


@pytest.mark.asyncio
async def test_large_project_revision_starts_with_manifest_without_waiting_for_truncation(monkeypatch):
    original=plan()
    original['nodes'].extend(dict(id=f'scene{i}',kind='image',title=f'场景{i}',prompt='forest') for i in range(20))
    provider=SimpleNamespace(chat=AsyncMock(side_effect=[answer(manifest([original['nodes'][1]])),
        answer(dict(node=dict(id='video',content='只更新此节点')))]))
    monkeypatch.setattr(planning,'create_provider',lambda:provider)
    result=await planning.propose_creation(request(current_plan=original))
    assert provider.chat.await_count==2
    assert '分段协议' in provider.chat.call_args_list[0].args[0][0].content
    assert result.plan.nodes[1].content=='只更新此节点' and len(result.plan.nodes)==22


@pytest.mark.asyncio
async def test_runaway_stream_is_closed_at_output_budget_without_waiting_for_terminal_chunk():
    closed=[]
    async def stream(*args,**kwargs):
        try:
            for _ in range(1000):yield LLMStreamChunk(text=' ' * 4096)
            pytest.fail('unbounded stream consumed to the end')
        finally:closed.append(True)
    complete=creation_completion.PlanningCompletion(SimpleNamespace(chat_stream_response=stream),AsyncMock(),streaming=True)
    with pytest.raises(PlanningOutputTruncated):await complete([],{},'creation_node')
    assert closed==[True]


@pytest.mark.asyncio
async def test_output_budget_releases_the_underlying_provider_http_stream():
    from agent.llm.openai_provider import OpenAIProvider
    closed=[]
    class Body(httpx.AsyncByteStream):
        async def __aiter__(self):
            for _ in range(100):
                data={'choices':[{'index':0,'delta':{'content':' ' * 4096},'finish_reason':None}]}
                yield ('data: '+json.dumps(data)+'\n\n').encode()
        async def aclose(self):closed.append(True)
    provider=OpenAIProvider(api_key='sk-test',model='test',base_url='https://test/v1')
    await provider.client.close()
    provider.client=openai.AsyncOpenAI(api_key='sk-test',base_url='https://test/v1',
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(lambda req:httpx.Response(200,headers={'content-type':'text/event-stream'},stream=Body()))))
    try:
        complete=creation_completion.PlanningCompletion(provider,AsyncMock(),streaming=True)
        with pytest.raises(PlanningOutputTruncated):await complete([],{},'creation_node')
        assert closed==[True]
    finally:await provider.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['length', 'unfinished_json', 'missing_terminal'])
async def test_incomplete_output_recovers_complete_nodes_and_preserves_usage(monkeypatch, failure):
    value = plan('identity')
    truncated = LLMResponse(content='{"plan":{"nodes":["DO-NOT-SALVAGE',
        finish_reason='length' if failure == 'length' else '', model='test-planner', usage={'output': 7})
    responses = [truncated, answer(manifest(value['nodes'])), *[answer(dict(node=n)) for n in value['nodes']]]
    provider = SimpleNamespace(chat=AsyncMock(side_effect=responses))
    if failure == 'missing_terminal':
        iterator = iter(responses)
        async def stream(*args, **kwargs):
            response = next(iterator)
            yield LLMStreamChunk(text=response.content)
            if response is not truncated:
                yield LLMStreamChunk(response=response)
        provider.chat_stream_response = stream
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    events = []
    async def report(event): events.append(event)
    result = await planning.propose_creation(request(), on_progress=report)
    assert [n.id for n in result.plan.nodes] == ['script', 'video']
    assert result.plan.nodes[1].references[0].asset_id == 'rabbit'
    assert result.plan.nodes[1].prompt
    assert result.tokens_used == {'output': 30 if failure == 'missing_terminal' else 37}
    assert any(e['stage'] == 'partition' for e in events)
    assert 'DO-NOT-SALVAGE' not in json.dumps(events)
    if failure != 'missing_terminal':
        assert provider.chat.await_count == 4
        assert all(c.kwargs['tools'] is None for c in provider.chat.call_args_list[1:])
        assert all('DO-NOT-SALVAGE' not in str(c.args[0]) for c in provider.chat.call_args_list[1:])


@pytest.mark.asyncio
async def test_partition_keeps_locks_latest_choice_and_completed_segments_during_retry(monkeypatch):
    original = plan()
    original['questions'] = [dict(question='画幅？', options=['横屏', '竖屏'])]
    before = copy.deepcopy(original)
    header = manifest([original['nodes'][1]])
    header.pop('questions')  # Existing exact option reply resolves the old question.
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(finish_reason='length'), answer(header),
        answer(dict(node=dict(id='script', content='不允许串改已确认脚本'))),
        answer(dict(node=dict(id='video', aspect_ratio='9:16')))]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    req = request(current_plan=original, automatic_mode=True, locked_node_ids=['script'])
    req.messages.append(dict(role='user', content='关于“画幅？”，我选择：竖屏'))
    result = await planning.propose_creation(req)
    assert original == before
    assert result.plan.nodes[0].content == original['nodes'][0]['content']
    assert result.plan.nodes[1].aspect_ratio == '9:16' and result.plan.questions == []
    assert provider.chat.await_count == 4


@pytest.mark.asyncio
async def test_partition_manifest_cannot_target_locks_duplicate_ids_or_grow_graph(monkeypatch):
    original = plan()
    for header in [manifest([original['nodes'][0]]), manifest([original['nodes'][1]] * 2)]:
        provider = SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(finish_reason='length'), answer(header), answer(header)]))
        monkeypatch.setattr(planning, 'create_provider', lambda: provider)
        with pytest.raises(PlanningOutputTruncated):
            await planning.propose_creation(request(current_plan=original, automatic_mode=True, locked_node_ids=['script']))
        assert provider.chat.await_count == 3


@pytest.mark.asyncio
async def test_partition_retries_only_failed_node_and_returns_nothing_if_exhausted(monkeypatch):
    value = plan()
    responses = [LLMResponse(finish_reason='length'), answer(manifest(value['nodes'])), answer(dict(node=value['nodes'][0])),
        LLMResponse(content='{"node":', finish_reason='length'), LLMResponse(content='{"node":', finish_reason='length')]
    provider = SimpleNamespace(chat=AsyncMock(side_effect=responses))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    req, trace = request(), TraceStore()
    with pytest.raises(PlanningOutputTruncated):
        await planning.propose_creation(req, trace)
    assert req.current_plan == {} and provider.chat.await_count == 5
    assert all(r.status == 'failed' for r in trace._runs.values())
    diagnostics = [e for r in trace._runs.values() for e in r.events if e.type == 'creation.planning_diagnostics']
    assert diagnostics[0].payload['partitioned'] is True
    assert diagnostics[0].payload['tokens_used'] == {'output': 20}
    for call in provider.chat.call_args_list[-2:]:
        payload = next(json.loads(m.content) for m in call.args[0] if m.role == 'user' and isinstance(m.content, str) and 'completed_nodes' in m.content)
        assert [n['id'] for n in payload['completed_nodes']] == ['script']


@pytest.mark.asyncio
async def test_recovered_graph_still_requires_valid_asset_ownership_and_dependencies(monkeypatch):
    value = plan('identity')
    value['nodes'][1]['references'][0]['asset_id'] = 'foreign'
    correction = dict(reply='无权引用', patch=dict(nodes=[]))
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(finish_reason='length'),
        answer(manifest(value['nodes'])), *[answer(dict(node=n)) for n in value['nodes']], answer(correction)]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    original = plan()
    with pytest.raises(ValueError, match='video.*未提供的图片资产'):
        await planning.propose_creation(request(current_plan=original))
    assert original['nodes'][1]['references'] == []


@pytest.mark.asyncio
async def test_partition_call_budget_is_global_not_per_node(monkeypatch):
    monkeypatch.setattr(creation_partition, 'MAX_PARTITION_CALLS', 2)
    value = plan()
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(finish_reason='length'),
        answer(manifest(value['nodes'])), answer(dict(node=value['nodes'][0]))]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    with pytest.raises(PlanningOutputTruncated):
        await planning.propose_creation(request())
    assert provider.chat.await_count == 3


@pytest.mark.asyncio
async def test_transient_model_error_retries_with_backoff_but_auth_does_not(monkeypatch):
    sleep = AsyncMock()
    monkeypatch.setattr(creation_completion.asyncio, 'sleep', sleep)
    for status, expected in [(503, 3), (401, 1), (400, 1), (429, 1)]:
        error = openai.APIStatusError('private-provider-message', response=httpx.Response(status, request=httpx.Request('POST', 'https://test')), body={})
        provider = SimpleNamespace(chat=AsyncMock(side_effect=error))
        monkeypatch.setattr(planning, 'create_provider', lambda: provider)
        with pytest.raises(openai.APIStatusError):
            await planning.propose_creation(request())
        assert provider.chat.await_count == expected
    assert [c.args[0] for c in sleep.call_args_list] == [1, 2]
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[httpx.ReadError('private'), answer(dict(reply='完成', plan=plan()))]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    assert (await planning.propose_creation(request())).plan.nodes
    assert provider.chat.await_count == 2


@pytest.mark.parametrize('text,expected', [
    ('{"node":{"content":"unfinished', True), ('{"x":[1,', True),
    ('{"x":"braces \\" }"}', False), ('{} extra', False), ('not json', False), ('{"x":]}', False),
])
def test_incomplete_json_only_detects_unfinished_containers(text, expected):
    assert creation_partition.incomplete_json(text) is expected


@pytest.mark.asyncio
@pytest.mark.parametrize('finish', ['length', None])
async def test_real_stream_protocol_uses_strict_single_node_schema_and_recovers_disconnect(monkeypatch, finish):
    from agent.llm.doubao_provider import DoubaoProvider
    provider = DoubaoProvider(api_key='test', model='doubao-seed-2.1-turbo')
    value = plan()
    responses = [None, manifest(value['nodes']), *[dict(node=n) for n in value['nodes']]]
    calls = []
    def handler(req):
        payload = json.loads(req.content)
        calls.append(payload)
        value = responses[len(calls) - 1]
        content = json.dumps(value) if value is not None else '{"reply":"unfinished'
        chunk = dict(model='test-wire', choices=[dict(delta=dict(content=content), finish_reason=finish if value is None else 'stop')])
        return httpx.Response(200, text='data: '+json.dumps(chunk)+'\n\ndata: [DONE]\n\n', headers={'content-type': 'text/event-stream'})
    await provider.client.close()
    provider.client = openai.AsyncOpenAI(api_key='test', base_url='https://ark.cn-beijing.volces.com/api/plan/v3',
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    try:
        result = await planning.propose_creation(request(), on_progress=AsyncMock())
        assert result.plan.nodes[-1].kind == 'video' and len(calls) == 4
        assert all(c['max_tokens'] == 16384 and c['thinking']['type'] == 'disabled' for c in calls)
        assert all(c['response_format']['json_schema']['strict'] for c in calls)
        assert all('tools' not in c for c in calls[1:])
        for payload, ident in zip(calls[2:], ['script', 'video']):
            schema = payload['response_format']['json_schema']['schema']
            assert schema['$defs']['CreativeNodePatch']['properties']['id']['enum'] == [ident]
    finally:
        await provider.client.close()


@pytest.mark.asyncio
async def test_six_video_recovery_keeps_all_clips_and_shared_script_context(monkeypatch):
    nodes = [dict(id='brief', kind='text', purpose='brief', title='制作简报', content='交付六条独立视频，每条5秒')]
    for i in range(6):
        script, video = copy.deepcopy(plan()['nodes'])
        script.update(id=f'script{i}', depends_on=['brief'], content=f'第{i+1}条5秒脚本')
        video.update(id=f'video{i}', depends_on=[script['id']])
        nodes.extend([script, video])
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(finish_reason='length'), answer(manifest(nodes)),
        *[answer(dict(node=n)) for n in nodes]]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    result = await planning.propose_creation(request())
    assert len(result.plan.nodes) == 13
    assert sum(n.kind == 'video' for n in result.plan.nodes) == 6
    assert [n.depends_on for n in result.plan.nodes if n.kind == 'video'] == [[f'script{i}'] for i in range(6)]
    assert provider.chat.await_count == 15


@pytest.mark.asyncio
async def test_cancelling_partition_stops_without_committing_draft(monkeypatch):
    import asyncio
    entered, closed = asyncio.Event(), []
    count = 0
    async def respond(*args, **kwargs):
        nonlocal count
        count += 1
        if count == 1:
            return LLMResponse(finish_reason='length')
        entered.set()
        try:
            await asyncio.Event().wait()
        finally:
            closed.append(True)
    monkeypatch.setattr(planning, 'create_provider', lambda: SimpleNamespace(chat=respond))
    req, trace = request(), TraceStore()
    task = asyncio.create_task(planning.run_planning(req, trace))
    await asyncio.wait_for(entered.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert closed == [True] and count == 2 and req.current_plan == {}
    assert all(r.status == 'failed' for r in trace._runs.values())
