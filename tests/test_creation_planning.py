"""Director proposals remain read-only until the Gateway review boundary."""
import copy
import json
from io import BytesIO
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
from PIL import Image
import pytest
from pydantic import ValidationError

from agent.aigc import creation_planning as planning
from agent.llm.base import LLMResponse
from agent.trace.store import TraceStore


def plan(reference_role=None):
    storyboard = dict(style='Ink illustration.', shots=[dict(start_seconds=0., description='The rabbit bows. Static medium shot.')],
                      overall_soundscape='Wind in bamboo.', non_diegetic_music='N/A')
    refs = []
    if reference_role:
        refs = [dict(asset_id='rabbit', role=reference_role, note='兔大侠')]
        if reference_role != 'first_frame':
            storyboard.update(subject_definitions='<Subject 1> is the rabbit from <Picture 1>.',
                summary='[reference generation] The rabbit bows.',
                retention_analysis='<Subject 1> (appears in [Shot 1]): fully_preserved - identity.')
    return dict(title='竹林相逢', summary='一支克制的水墨短片', nodes=[
        dict(id='script', kind='text', purpose='script', title='分镜脚本', content='0–5秒：兔大侠拱手，固定中景，竹林风声。'),
        dict(id='video', kind='video', title='最终视频', content='按已确认分镜生成', depends_on=['script'],
             references=refs, storyboard=storyboard)], questions=[])


def request(**kwargs):
    return planning.PlanningRequest(project_id='project', user_id='alice', messages=[dict(role='user', content='做一支短片')],
        assets=[planning.PlanningAsset(id='rabbit', name='人设.png', mime_type='image/png')], **kwargs)


@pytest.mark.parametrize('role,marker', [(None, 'integrated_multimodal_description'), ('first_frame', 'at 0.00 seconds'), ('identity', 'subject_definitions'), ('style', 'subject_definitions')])
def test_director_compiles_video_using_semantic_reference_role(role, marker):
    proposal = planning.parse_proposal(json.dumps(dict(reply='请审阅分镜', plan=plan(role))), request())
    assert marker in proposal.plan.nodes[-1].prompt
    assert proposal.plan.nodes[-1].storyboard.shots[0].start_seconds == 0
    assert not hasattr(proposal.plan.nodes[0], 'approved_revision')


@pytest.mark.parametrize('change', [
    lambda p: p['nodes'][-1].update(depends_on=[]),
    lambda p: p['nodes'][0].update(depends_on=['video']),
    lambda p: p['nodes'][-1]['references'][0].update(asset_id='other-account'),
    lambda p: p['nodes'][-1]['storyboard']['shots'][0].update(start_seconds=1.),
    lambda p: p['nodes'][-1].update(approved=True),
    lambda p: p['nodes'][-1].update(template_id='invented'),
    lambda p: p['nodes'][-1]['references'].append(dict(asset_id='rabbit', role='identity')),
])
def test_invalid_plans_and_forged_approvals_cannot_cross_boundary(change):
    value = plan('identity'); change(value)
    with pytest.raises(ValueError):
        planning.parse_proposal(json.dumps(dict(reply='review', plan=value)), request())


def test_video_validation_identifies_every_bad_node_and_field_for_repair():
    value = plan()
    value['nodes'][-1].update(asset_id='rabbit', count=3, character_style='anime', storyboard=None)
    value['nodes'].append(dict(value['nodes'][-1], id='video_two', count=2))
    with pytest.raises(ValidationError) as error:
        planning.CreativePlan.model_validate(value)
    details = planning.validation_details(error.value)
    assert [entry['loc'] for entry in details] == [('nodes', 1), ('nodes', 2)]
    for ident, entry in zip(['video', 'video_two'], details):
        assert ident in entry['msg']
        assert all(field in entry['msg'] for field in ['asset_id', 'count=1', 'character_style', 'storyboard'])


def test_revision_schema_retains_node_constraints_and_field_guidance():
    patch = planning.RevisionResponse.model_json_schema()['$defs']['CreativeNodePatch']
    assert patch['required'] == ['id']
    schema = patch['properties']
    assert schema['duration_seconds']['minimum'] == 1 and schema['duration_seconds']['maximum'] == 15
    assert schema['count']['maximum'] == 3 and '视频' in schema['count']['description']
    assert schema['id']['maxLength'] == 80
    assert schema['content']['maxLength'] == 8000
    assert '视频' in schema['character_style']['description']


def test_image_workflows_and_clarifying_questions_are_supported():
    value = dict(title='二次创作', summary='先画原图，再调整风格', nodes=[
        dict(id='a', kind='image', title='原图', prompt='白色陶瓷杯'),
        dict(id='b', kind='image', title='水彩', prompt='转为水彩', depends_on=['a'], references=[dict(node_id='a', role='reference')])])
    assert len(planning.CreativePlan.model_validate(value).nodes) == 2
    value['nodes'][1]['references'].append(dict(asset_id='rabbit', role='identity'))
    with pytest.raises(ValidationError): planning.CreativePlan.model_validate(value)
    question = planning.CreativePlan(title='创作方向', summary='确定结尾', questions=[dict(question='结尾？', options=['反转', '悬疑'])])
    assert not question.nodes


def test_image_preview_is_resized_and_strips_large_original():
    import base64
    source = BytesIO(); Image.new('RGB', (1600, 1000), 'red').save(source, format='PNG')
    output = planning.image_preview('data:image/png;base64,' + base64.b64encode(source.getvalue()).decode())
    with Image.open(BytesIO(base64.b64decode(output.split(',')[1]))) as image:
        assert image.size == (768, 480) and image.format == 'JPEG'


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
async def test_cold_provider_config_failure_is_not_reported_as_invalid_plan(monkeypatch, streaming):
    def missing_provider():
        raise ValueError('API key not configured SECRET-UPSTREAM')
    monkeypatch.setattr(planning, 'create_provider', missing_provider)
    from agent.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/agent/creation/plan' + ('/stream' if streaming else ''), json=request().model_dump())
    error = json.loads(response.text.splitlines()[-1]) if streaming else response.json()['detail']
    assert error['code'] == 'provider_config_missing'
    assert '配置' in error['message'] and '格式' not in error['message']
    assert 'SECRET' not in response.text
    if not streaming:
        assert response.status_code == 502


@pytest.mark.asyncio
async def test_real_provider_boundary_repairs_once_tracks_usage_and_cannot_generate(monkeypatch):
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(content='not json', model='configured-model', usage={'input_tokens': 10}),
        LLMResponse(content=json.dumps(dict(reply='分镜已准备好，请审阅', plan=plan())), model='configured-model', usage={'input_tokens': 20, 'output_tokens': 15})]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    trace = TraceStore()
    result = await planning.propose_creation(request(), trace)
    assert provider.chat.await_count == 2
    assert all({tool.name for tool in call.kwargs['tools']} == {'ls_drive', 'search_drive', 'read_drive'} for call in provider.chat.call_args_list)
    assert result.tokens_used == dict(input_tokens=30, output_tokens=15)
    assert result.model_used == 'configured-model' and result.run_id
    system = provider.chat.call_args.args[0][0].content
    assert '创作项目必须经过画布审阅与明确提交' in system
    assert '普通短片无需额外确认' not in system


@pytest.mark.asyncio
async def test_provider_failure_is_sanitized_and_trace_finishes(monkeypatch):
    provider = SimpleNamespace(chat=AsyncMock(side_effect=RuntimeError('SECRET-KEY')))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    trace = TraceStore()
    with pytest.raises(RuntimeError): await planning.propose_creation(request(), trace)
    assert all(run.status == 'failed' for run in trace._runs.values())
    from agent.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/agent/creation/plan', json=request().model_dump())
    assert response.status_code == 502 and 'SECRET' not in response.text


@pytest.mark.asyncio
async def test_invalid_model_response_fails_after_one_repair(monkeypatch):
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content='{}')))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    with pytest.raises(ValueError, match='格式校验失败'): await planning.propose_creation(request())
    assert provider.chat.await_count == 2


@pytest.mark.asyncio
async def test_stream_reports_real_activity_before_result_without_raw_reasoning(monkeypatch):
    from agent.llm.base import LLMStreamChunk
    steps = []
    async def stream(*args, **kwargs):
        assert {tool.name for tool in kwargs['tools']} == {'ls_drive', 'search_drive', 'read_drive'}
        yield LLMStreamChunk(reasoning='PRIVATE-REASONING')
        assert steps[-1]['stage'] == 'thinking'
        content = json.dumps(dict(reply='请提供 E04 的脚本', plan=dict(title='E04', summary='等待剧情', nodes=[], questions=[dict(question='从哪里开始？', options=['提供已有脚本', '一起构思剧情'])])))
        yield LLMStreamChunk(text=content[:30])
        assert steps[-1]['stage'] == 'draft'
        yield LLMStreamChunk(text=content[30:])
        yield LLMStreamChunk(response=LLMResponse(content=content, model='model', usage={'output_tokens': 12}))
    monkeypatch.setattr(planning, 'create_provider', lambda: SimpleNamespace(chat_stream_response=stream))
    async def report(event): steps.append(event)
    result = await planning.propose_creation(request(), on_progress=report)
    assert [e['stage'] for e in steps] == ['context', 'model', 'thinking', 'draft', 'validate']
    assert 'PRIVATE' not in json.dumps(steps) and '"nodes"' not in json.dumps(steps)
    assert result.plan.nodes == [] and result.plan.questions and result.tokens_used['output_tokens'] == 12


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['format', 'provider', 'timeout', 'truncated'])
async def test_stream_terminal_errors_are_visible_and_sanitized(monkeypatch, failure):
    from agent.llm.base import LLMStreamChunk
    async def stream(*args, **kwargs):
        if failure == 'provider': raise RuntimeError('SECRET-KEY')
        if failure == 'timeout':
            import asyncio
            await asyncio.sleep(1)
        yield LLMStreamChunk(text='{}')
        if failure != 'truncated': yield LLMStreamChunk(response=LLMResponse(content='{}'))
    monkeypatch.setattr(planning, 'create_provider', lambda: SimpleNamespace(chat_stream_response=stream))
    monkeypatch.setattr(planning, 'PLANNING_TIMEOUT', .01 if failure == 'timeout' else 1)
    from agent.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/agent/creation/plan/stream', json=request().model_dump())
    events = [json.loads(line) for line in response.text.splitlines()]
    assert events[0]['type'] == 'progress' and events[-1]['type'] == 'error'
    assert 'SECRET' not in response.text and 'result' not in [e['type'] for e in events]
    if failure == 'format': assert any(e.get('stage') == 'repair' for e in events)
    if failure == 'timeout': assert '超时' in events[-1]['message']


@pytest.mark.asyncio
async def test_director_agent_loop_researches_script_then_returns_reviewable_plan(monkeypatch):
    from agent.llm.base import ToolCall
    from agent.skills.base import SkillResult
    from agent.aigc.creation_tools import director_tools
    skills = director_tools()
    search = AsyncMock(return_value=SkillResult(success=True, data={'results': [{'item': {'id': 'e04', 'name': 'E04.md'}}]}))
    read = AsyncMock(return_value=SkillResult(success=True, data={'content': 'E04：兔大侠在竹林与朋友相逢'}))
    monkeypatch.setattr(skills['search_drive'], 'execute', search)
    monkeypatch.setattr(skills['read_drive'], 'execute', read)
    monkeypatch.setattr(planning, 'director_tools', lambda: skills)
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[
        LLMResponse(tool_calls=[ToolCall(id='find', name='search_drive', arguments={'query': 'E04', '_user_id': 'victim'})], usage={'input_tokens': 2}),
        LLMResponse(tool_calls=[ToolCall(id='read', name='read_drive', arguments={'item_id': 'e04'})], usage={'input_tokens': 3}),
        LLMResponse(content=json.dumps(dict(reply='找到 E04，请审阅分镜', plan=plan())), usage={'input_tokens': 4}),
    ]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    trace, events = TraceStore(), []
    async def report(event): events.append(event)
    result = await planning.propose_creation(request(), trace, report)
    assert result.tokens_used == {'input_tokens': 9}
    assert search.call_args.kwargs['_user_id'] == 'alice' and read.call_args.kwargs['_user_id'] == 'alice'
    assert len([e for e in events if e['stage'] == 'tool_start']) == 2
    messages = provider.chat.call_args.args[0]
    assert any(m.role == 'tool' and m.tool_call_id == 'read' and 'E04' in m.content for m in messages)
    run = trace._runs[result.run_id]
    assert run.skills_used == ['search_drive', 'read_drive']
    assert len([event for event in run.events if event.type == 'tool.completed']) == 2


@pytest.mark.asyncio
async def test_director_agent_cannot_execute_generation_or_loop_forever(monkeypatch):
    from agent.llm.base import ToolCall
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(tool_calls=[ToolCall(id='forged', name='generate_video', arguments={})])))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    with pytest.raises(ValueError, match='上限'):
        await planning.propose_creation(request())
    assert provider.chat.await_count == 7
    messages = provider.chat.call_args.args[0]
    assert all('画布确认' in m.content for m in messages if m.role == 'tool')
    assert provider.chat.call_args.kwargs['tools'] is None


@pytest.mark.asyncio
async def test_director_tool_failure_returns_safe_observation_for_next_iteration(monkeypatch):
    from agent.llm.base import ToolCall
    from agent.aigc.creation_tools import director_tools, execute_director_tool
    skills = director_tools()
    monkeypatch.setattr(skills['read_drive'], 'execute', AsyncMock(side_effect=RuntimeError('SECRET')))
    events = []
    async def report(stage, message, **extra): events.append(dict(stage=stage, message=message, **extra))
    result = await execute_director_tool(skills, ToolCall(id='read', name='read_drive', arguments={'item_id': 'bad'}), 'alice', report)
    assert not result['success'] and 'SECRET' not in json.dumps(result)
    assert [event['stage'] for event in events] == ['tool_start', 'tool_end']


def image_request(count=5):
    import base64
    source = BytesIO(); Image.new('RGB', (32, 32), 'red').save(source, format='PNG')
    url = 'data:image/png;base64,' + base64.b64encode(source.getvalue()).decode()
    return planning.PlanningRequest(project_id='image-project', user_id='alice', messages=[dict(role='user', content='参考这些图片创作')],
        assets=[planning.PlanningAsset(id=f'image-{i}', name=f'reference-{i}.png', mime_type='image/png', data_url=url) for i in range(count)])


def model_bad_request(message='Model only support text input', status=400):
    import openai
    response = httpx.Response(status, request=httpx.Request('POST', 'https://provider.example/chat/completions'))
    cls = openai.BadRequestError if status == 400 else openai.APIStatusError
    return cls(message, response=response, body={'code': 'InvalidParameter', 'message': message})


@pytest.mark.asyncio
async def test_five_image_creation_routes_text_only_glm_to_same_service_vision_model(monkeypatch):
    from agent.aigc.creation_models import VISION_PLAN_MODEL
    text = SimpleNamespace(provider_name='doubao', model='glm-5.3', client=SimpleNamespace(base_url='https://ark.cn-beijing.volces.com/api/plan/v3/', close=AsyncMock()), chat=AsyncMock(side_effect=model_bad_request()))
    vision = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(reply='素材已理解，请审阅', plan=plan())), model=VISION_PLAN_MODEL)))
    choices, events = [], []
    def factory(name=None):
        choices.append(name)
        return text if name is None else vision
    monkeypatch.setattr(planning, 'create_provider', factory)
    async def report(event): events.append(event)
    result = await planning.propose_creation(image_request(), on_progress=report)
    assert choices == [None, 'doubao:' + VISION_PLAN_MODEL]
    assert text.chat.await_count == 0 and text.client.close.await_count == 1
    assert result.model_used == VISION_PLAN_MODEL
    inputs = vision.chat.call_args.args[0][1].content
    assert len([part for part in inputs if part['type'] == 'image_url']) == 5
    assert events[0]['stage'] == 'model_selection'


@pytest.mark.asyncio
async def test_text_only_creation_keeps_default_glm_model(monkeypatch):
    provider = SimpleNamespace(provider_name='doubao', model='glm-5.3', chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(reply='请审阅', plan=plan())), model='glm-5.3')))
    choices = []
    def factory(name=None): choices.append(name); return provider
    monkeypatch.setattr(planning, 'create_provider', factory)
    result = await planning.propose_creation(request())
    assert choices == [None] and result.model_used == 'glm-5.3'


@pytest.mark.asyncio
@pytest.mark.parametrize('base_url,fallback', [('https://ark.cn-beijing.volces.com/api/plan/v3/', True), ('https://custom.example/v1/', False)])
async def test_explicit_image_rejection_can_fallback_once_only_within_configured_plan_service(monkeypatch, base_url, fallback):
    error = model_bad_request()
    text = SimpleNamespace(provider_name='doubao', model='unknown-text-model', client=SimpleNamespace(base_url=base_url, close=AsyncMock()), chat=AsyncMock(side_effect=error))
    vision = SimpleNamespace(provider_name='doubao', model='doubao-seed-2.1-turbo', client=SimpleNamespace(base_url=base_url), chat=AsyncMock(side_effect=error))
    choices = []
    def factory(name=None): choices.append(name); return text if name is None else vision
    monkeypatch.setattr(planning, 'create_provider', factory)
    with pytest.raises(type(error)):
        await planning.propose_creation(image_request(1))
    assert len(choices) == (2 if fallback else 1)
    assert text.chat.await_count == 1 and vision.chat.await_count == (1 if fallback else 0)


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code,label', [(400, 'model_image_unsupported', '不支持图片'), (401, 'provider_auth_failed', '鉴权'), (429, 'provider_rate_limited', '额度'), (503, 'provider_unavailable', '连接')])
async def test_planning_errors_explain_provider_cause_without_leaking_response_body(monkeypatch, status, code, label):
    error = model_bad_request('Model only support text input SECRET-KEY' if status == 400 else 'SECRET-KEY', status)
    provider = SimpleNamespace(chat=AsyncMock(side_effect=error))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    trace = TraceStore()
    with pytest.raises(type(error)): await planning.propose_creation(request(), trace)
    run = next(iter(trace._runs.values()))
    assert run.error_type == code and label in run.error_message
    from agent.main import app
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
        response = await client.post('/agent/creation/plan/stream', json=request().model_dump())
    terminal = json.loads(response.text.splitlines()[-1])
    assert terminal['type'] == 'error' and terminal['code'] == code and label in terminal['message']
    assert 'SECRET-KEY' not in response.text


def test_conversational_reply_without_artifacts_is_valid_and_never_clears_existing_canvas():
    value = dict(reply='五张图片分别为红绿蓝黄紫。你想用它们创作什么？', plan=dict(title='色彩创作', summary='等待创作意图', nodes=[], questions=[]))
    result = planning.parse_proposal(json.dumps(value), request())
    assert result.plan.nodes == [] and not result.plan.questions
    previous = plan()
    result = planning.parse_proposal(json.dumps(value), request(current_plan=previous))
    assert [node.id for node in result.plan.nodes] == ['script', 'video']
    assert result.plan.nodes[0].content == previous['nodes'][0]['content']


def test_clarification_accepts_four_options_including_freeform_choice_but_stays_bounded():
    value = dict(question='创作什么？', options=['图片', '视频', '组图', '其他想法'])
    assert len(planning.CreativeQuestion(**value).options) == 4
    value['options'].append('过多选项')
    with pytest.raises(ValidationError): planning.CreativeQuestion(**value)


def test_node_revision_directions_are_optional_nonblocking_and_survive_planning():
    value=plan()
    value['nodes'][0]['revision_suggestions']=[dict(label=f'方向{i}',instruction=f'仅优化当前节点的第{i}个方面') for i in range(10)]
    result=planning.parse_proposal(json.dumps(dict(reply='选择方向继续调整',plan=value)),request())
    assert len(result.plan.nodes[0].revision_suggestions)==10
    assert result.plan.nodes[0].revision_suggestions[0].instruction=='仅优化当前节点的第0个方面'
    assert result.plan.questions==[] and result.plan.nodes[-1].prompt
    value['nodes'][0]['revision_suggestions'].extend([dict(label='extra',instruction='修改')]*3)
    with pytest.raises(ValidationError): planning.CreativePlan.model_validate(value)
    value['nodes'][0]['revision_suggestions']=[dict(label=' ',instruction='修改')]
    with pytest.raises(ValidationError): planning.CreativePlan.model_validate(value)


def test_director_output_budget_is_local_to_official_plan_provider():
    from agent.aigc.creation_models import configure_planning_output
    def provider(url, maximum=None, name='doubao'):
        return SimpleNamespace(provider_name=name, client=SimpleNamespace(base_url=url), max_tokens=maximum)
    selected = provider('https://ark.cn-beijing.volces.com/api/plan/v3')
    configure_planning_output(selected)
    assert selected.max_tokens == 16384
    for value in [provider('https://example.com'), provider('https://ark.cn-beijing.volces.com/api/plan/v3', 2048)]:
        before = value.max_tokens
        configure_planning_output(value)
        assert value.max_tokens == before


@pytest.mark.asyncio
async def test_truncated_long_plan_is_not_rewritten_at_same_limit(monkeypatch):
    from agent.aigc.creation_models import PlanningOutputTruncated, planning_error
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(
        content='{"reply":"review","plan":{"nodes":[' + ' ' * 13000, finish_reason='length')))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    trace = TraceStore()
    with pytest.raises(PlanningOutputTruncated) as failure:
        await planning.propose_creation(request(), trace)
    assert provider.chat.await_count == 1
    assert planning_error(failure.value)[0] == 'planning_output_truncated'
    assert all(run.status == 'failed' for run in trace._runs.values())


def test_six_shot_plan_keeps_independent_clips_and_missing_character_dependency():
    """Six scene clips fit the graph without squeezing the story into 15 seconds."""
    value = dict(title='六段武侠短片', summary='逐段审阅生成', nodes=[
        dict(id='turtle', kind='image', purpose='shot_reference', title='慢慢人设', prompt='灰衣老龟人设')])
    for i in range(6):
        segment = plan('identity')['nodes']
        segment[0].update(id=f'script_{i}', content=f'镜头{i+1}：0–10秒，本段动作与声音。')
        segment[1].update(id=f'video_{i}', duration_seconds=10, depends_on=[f'script_{i}', 'turtle'])
        segment[1]['references'] = [dict(node_id='turtle',role='identity')]
        value['nodes'].extend(segment)
    parsed = planning.parse_proposal(json.dumps(dict(reply='请逐段审阅',plan=value)), request())
    videos = [n for n in parsed.plan.nodes if n.kind=='video']
    assert len(videos)==6 and sum(n.duration_seconds for n in videos)==60
    assert all(n.references[0].node_id=='turtle' and n.storyboard for n in videos)
    value['nodes'][2]['depends_on'].remove('turtle')
    with pytest.raises(ValueError):
        planning.parse_proposal(json.dumps(dict(reply='review',plan=value)), request())


def test_revision_patch_merges_changed_fields_and_keeps_references_and_other_nodes():
    original = plan('identity')
    before = copy.deepcopy(original)
    result = planning.parse_proposal(json.dumps(dict(reply='已优化', patch=dict(nodes=[dict(id='script', content='0–5秒：推近兔大侠拱手，风声渐弱。')]))), request(current_plan=original))
    assert result.plan.nodes[0].content.startswith('0–5秒：推近')
    assert result.plan.nodes[1].references[0].asset_id == 'rabbit'
    assert result.plan.nodes[1].storyboard.model_dump() == planning.CreativeNode.model_validate(original['nodes'][1]).storyboard.model_dump()
    assert result.plan.title == original['title'] and original == before


@pytest.mark.asyncio
@pytest.mark.parametrize('locked', [False, True])
async def test_revision_repair_preserves_draft_decisions_and_checks_original_locks(monkeypatch, locked):
    original = plan()
    original['questions'] = [dict(question='画幅？', options=['横屏', '竖屏'])]
    before = copy.deepcopy(original)
    draft = dict(reply='已采用竖屏并确定后续节点', patch=dict(questions=[], nodes=[
        dict(id='script', content='已按用户选择优化的脚本'),
        dict(id='video', aspect_ratio='9:16'),
        dict(id='visual', kind='image', title='主视觉', purpose='scene', prompt='ink forest')]))
    correction = dict(reply='修正主视觉用途', patch=dict(nodes=[dict(id='visual', purpose='key_visual')]))
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps(draft)), LLMResponse(content=json.dumps(correction))]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    req = request(current_plan=original, automatic_mode=True, locked_node_ids=['script'] if locked else [])
    if locked:
        with pytest.raises(ValueError):
            await planning.propose_creation(req)
    else:
        result = await planning.propose_creation(req)
        assert not result.plan.questions
        assert result.plan.nodes[0].content == '已按用户选择优化的脚本'
        assert result.plan.nodes[1].aspect_ratio == '9:16'
        assert result.plan.nodes[2].purpose == 'key_visual'
    assert provider.chat.await_count == 2
    assert original == before


@pytest.mark.asyncio
async def test_revision_repair_does_not_drop_invalid_foreign_asset_from_prior_draft(monkeypatch):
    original = plan()
    draft = dict(reply='修改', patch=dict(nodes=[dict(id='visual', kind='image', title='参考', purpose='scene', asset_id='foreign')]))
    correction = dict(reply='修正', patch=dict(nodes=[dict(id='visual', purpose='key_visual')]))
    provider = SimpleNamespace(chat=AsyncMock(side_effect=[LLMResponse(content=json.dumps(draft)), LLMResponse(content=json.dumps(correction))]))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    with pytest.raises(ValueError):
        await planning.propose_creation(request(current_plan=original))
    assert all(n['id'] != 'visual' for n in original['nodes'])


@pytest.mark.parametrize('nodes', [
    [dict(id='script', approved=True)],
    [dict(id='script', content='a'), dict(id='script', content='b')],
    [dict(id='script', depends_on=['video'])],
    [dict(id='video', references=[dict(asset_id='foreign', role='identity')])],
    [dict(id='unknown', content='缺少节点类型')],
])
def test_revision_patch_cannot_bypass_whole_graph_validation(nodes):
    original = plan('identity'); before = copy.deepcopy(original)
    with pytest.raises(ValueError):
        planning.parse_proposal(json.dumps(dict(reply='updated', patch=dict(nodes=nodes))), request(current_plan=original))
    assert original == before


@pytest.mark.asyncio
async def test_revision_uses_compact_schema_and_direct_output_without_repeating_compiled_prompts(monkeypatch):
    original = plan(); original['nodes'][1]['prompt'] = 'UNNECESSARY-COMPILED-PROMPT'
    provider = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(content=json.dumps(dict(reply='待审阅', patch=dict(nodes=[dict(id='script', content='优化后的脚本')]))))))
    monkeypatch.setattr(planning, 'create_provider', lambda: provider)
    result = await planning.propose_creation(request(current_plan=original))
    assert provider.chat.call_args.kwargs['thinking_enabled'] is False
    system, user = provider.chat.call_args.args[0]
    assert 'CreativeNodePatch' in system.content and '未变更字段和节点由系统保留' in system.content
    assert 'UNNECESSARY-COMPILED-PROMPT' not in user.content[0]['text']
    assert original['nodes'][1]['prompt'] == 'UNNECESSARY-COMPILED-PROMPT'
    assert len(result.plan.nodes) == 2


@pytest.mark.asyncio
async def test_active_planning_outlives_idle_budget_but_keeps_absolute_limit(monkeypatch):
    import asyncio
    monkeypatch.setattr(planning, 'PLANNING_TIMEOUT', .08)
    monkeypatch.setattr(planning, 'PLANNING_MAX_TIME', .5)
    async def active(req, trace, report):
        for i in range(6):
            await asyncio.sleep(.025)
            await report(dict(stage='draft', output_chars=i+1))
        return 'completed'
    monkeypatch.setattr(planning, 'propose_creation', active)
    assert await planning.run_planning(request()) == 'completed'
    monkeypatch.setattr(planning, 'PLANNING_MAX_TIME', .07)
    with pytest.raises(asyncio.TimeoutError):
        await planning.run_planning(request())


@pytest.mark.asyncio
async def test_stalled_planning_cancels_stream_and_records_timeout_in_trace(monkeypatch):
    import asyncio
    from agent.llm.base import LLMStreamChunk
    closed = []
    async def stalled(*args, **kwargs):
        try:
            yield LLMStreamChunk(text='partial')
            await asyncio.sleep(1)
        finally:
            closed.append(True)
    monkeypatch.setattr(planning, 'create_provider', lambda: SimpleNamespace(chat_stream_response=stalled))
    monkeypatch.setattr(planning, 'PLANNING_TIMEOUT', .03)
    trace = TraceStore()
    with pytest.raises(asyncio.TimeoutError):
        await planning.run_planning(request(), trace)
    assert closed == [True]
    assert all(r.status == 'failed' and r.error_type == 'planning_timeout' for r in trace._runs.values())


def test_complete_revision_with_redundant_closing_brace_does_not_require_another_model_call():
    value=json.dumps(dict(reply='已优化',patch=dict(nodes=[dict(id='script',content='优化后的完整脚本')])) ,ensure_ascii=False)
    result=planning.parse_proposal(value+'}',request(current_plan=plan()))
    assert result.plan.nodes[0].content=='优化后的完整脚本' and len(result.plan.nodes)==2
    for broken in (value[:-1], value+'{}', value+' explanatory text', value+']', value+'}}}}'):
        with pytest.raises(ValueError):
            planning.parse_proposal(broken,request(current_plan=plan()))
    with pytest.raises(ValueError):
        planning.parse_proposal('{"reply":"review","patch":{"nodes":[{"id":"script","approved":true}]}}}',request(current_plan=plan()))
