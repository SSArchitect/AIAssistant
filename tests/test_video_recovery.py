import asyncio
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent.aigc.progress import progress_scope
from agent.aigc.spark_client import SparkProviderError
from agent.aigc.spark_video_client import SparkVideoClient
from agent.aigc.video_recovery import recover_video_request
from agent.schemas.aigc import VideoGenerationRequest
from agent.schemas.chat import ChatRequest
from agent.trace import TraceStore
from tests.test_spark_reference_video import DATA
from tests.test_spark_video import mp4, task, video_response


def saved_run(store, *, user='owner', conversation='conversation', task_id=None):
    run = store.start_run(user_id=user, conversation_id=conversation, input_text='video',
                          agent_id='super_chat', runtime='self')
    store.append_event(run.run_id, type='context.built', status='completed', payload={
        'final_model_request': {'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'video'},
            {'type': 'text', 'text': 'Attachment 1: first.png'},
            {'type': 'image_url', 'image_url': {'url': DATA[0]}},
            # Indices refer to all attachments, not just images.
            {'type': 'text', 'text': 'Attachment 3: third.png'},
            {'type': 'image_url', 'image_url': {'url': DATA[1]}},
        ]}]}})
    store.append_event(run.run_id, type='media.task.progress', status='running', payload={
        'kind': 'video', 'stage': 'unknown', 'idempotency_key': 'original-key', 'task_id': task_id})
    return run


def arguments(**extra):
    return {'prompt': 'original scene', 'mode': 'reference_to_video',
            'reference_image_attachment_indices': [3, 1], 'idempotency_key': 'original-key', **extra}


def recover(store, **extra):
    return recover_video_request(store, user_id='owner', conversation_id='conversation',
                                  arguments=arguments(**extra))


def test_original_attachment_order_survives_restart_and_empty_followup(tmp_path):
    store = TraceStore(tmp_path / 'trace.db')
    saved_run(store)
    restored, task_id = recover(TraceStore(tmp_path / 'trace.db'))
    assert task_id is None
    assert restored['reference_image_data_urls'] == DATA[::-1]
    assert 'reference_image_attachment_indices' not in restored
    assert restored['idempotency_key'] == 'original-key'
    assert restored['prompt'] == 'original scene'


@pytest.mark.parametrize('user,conversation', [('other', 'conversation'), ('owner', 'other')])
def test_recovery_never_reads_another_owner_or_conversation(user, conversation):
    store = TraceStore()
    saved_run(store, user=user, conversation=conversation, task_id='private-provider-task')
    restored, task_id = recover(store, _resume_task_id='forged-task')
    assert task_id is None
    assert restored == arguments()


def test_acknowledged_task_uses_saved_identity_without_attachment_lookup():
    store = TraceStore()
    saved_run(store, task_id='video-task')
    restored, task_id = recover(store)
    assert task_id == 'video-task'
    assert restored == arguments()


def test_missing_or_ambiguous_inputs_are_not_silently_replaced():
    store = TraceStore()
    saved_run(store)
    with pytest.raises(ValueError, match='Original video attachments'):
        recover(store, reference_image_attachment_indices=[2])
    with pytest.raises(ValueError):
        recover(store, reference_image_attachment_indices=[True])
    with pytest.raises(ValueError):
        recover(store, reference_image_urls=['https://example.com/changed.png'])


@pytest.mark.asyncio
@pytest.mark.parametrize('task_id', [None, 'video-task'])
@pytest.mark.parametrize('denied', [False, True])
async def test_engine_followup_recovery_keeps_governance(engine, task_id, denied):
    saved_run(engine.trace_store, task_id=task_id)
    request = ChatRequest(user_id='owner', conversation_id='conversation', message='继续查原视频',
                          agent_id='super_chat', tool_policies={'generate_video': 'deny' if denied else 'auto'})
    with patch('agent.skills.builtin.generate_video.generate_video',
               new=AsyncMock(return_value=video_response())) as generate:
        result = await engine._execute_skill_with_governance(request=request, run_id='followup',
            skill_name='generate_video', arguments=arguments())
    assert result.success is not denied
    if denied:
        generate.assert_not_called()
        assert engine.trace_store.get_video_request('owner', 'conversation', 'original-key') is None
    elif task_id:
        assert generate.await_args.kwargs == {'resume_task_id': task_id}
    else:
        assert generate.await_args.args[0].reference_image_data_urls == DATA[::-1]


@pytest.mark.asyncio
async def test_accepted_video_resumes_with_get_only_without_reupload(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        assert request.method == 'GET'
        if '/artifacts/' in request.url.path:
            return httpx.Response(200, content=mp4(), headers={'Content-Type': 'video/mp4'})
        return httpx.Response(200, json=task())
    client = SparkVideoClient('https://spark.test', 'secret', output_dir=tmp_path,
                              transport=httpx.MockTransport(handler))
    result = await client.generate(VideoGenerationRequest(**arguments()), resume_task_id='video-task')
    assert result.id == 'video-task'
    assert len(calls) == 2
    assert calls[0].url.path == '/v1/tasks/video-task'
    assert calls[0].extensions['timeout']['read'] == 30
    assert calls[1].extensions['timeout']['read'] == 300
    assert (tmp_path / result.videos[0].url.rsplit('/', 1)[1]).read_bytes() == mp4()


@pytest.mark.asyncio
async def test_missing_saved_task_never_falls_back_to_generation(tmp_path):
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(404, json={'error': {'code': 'task_not_found'}})
    client = SparkVideoClient('https://spark.test', 'secret', output_dir=tmp_path,
                              transport=httpx.MockTransport(handler))
    with pytest.raises(SparkProviderError) as exc:
        await client.generate(VideoGenerationRequest(**arguments()), resume_task_id='expired-task')
    assert exc.value.code == 'task_not_found'
    assert [r.method for r in calls] == ['GET']


@pytest.mark.asyncio
async def test_video_submission_outlasts_image_deadline(tmp_path, monkeypatch):
    monkeypatch.setattr('agent.aigc.spark_client.SUBMISSION_TIMEOUT', .01)
    monkeypatch.setattr('agent.aigc.spark_video_client.VIDEO_SUBMISSION_TIMEOUT', .2)
    calls = []
    async def handler(request):
        calls.append(request)
        if request.method == 'POST':
            await asyncio.sleep(.03)
            return httpx.Response(202, json=task())
        return httpx.Response(200, content=mp4(), headers={'Content-Type': 'video/mp4'})
    client = SparkVideoClient('https://spark.test', 'secret', output_dir=tmp_path,
                              transport=httpx.MockTransport(handler))
    with progress_scope(lambda _: None, background=True):
        result = await client.generate(VideoGenerationRequest(prompt='scene', idempotency_key='same-key'))
    assert result.id == 'video-task'
    assert calls[0].headers['idempotency-key'] == 'same-key'


def test_video_deadlines_leave_governance_cleanup_margin():
    from agent.skills.builtin.generate_video import GenerateVideoSkill
    client = SparkVideoClient('https://spark.test', 'secret')
    assert client.submission_timeout() == 900
    assert client.timeout == 1800
    assert GenerateVideoSkill().metadata().timeout_seconds >= client.timeout + 120
    with pytest.raises(ValueError):
        GenerateVideoSkill().metadata().__class__(name='unbounded', description='test', timeout_seconds=3601)


def add_legacy_input_record(store, run):
    store.append_event(run.run_id, type='tool.started', status='running', step_id='original-call', payload={
        'name': 'generate_video', 'arguments': arguments(prompt='<redacted>', width=480, height=864,
                                                       duration_seconds=15)})
    store.append_event(run.run_id, type='tool.governance.allowed', status='completed', step_id='original-call', payload={
        'tool_name': 'generate_video', 'arguments': {'prompt': '<redacted>', 'mode': 'reference_to_video',
            'reference_image_data_urls': '<redacted>', 'width': 480, 'height': 864, 'duration_seconds': 15,
            'fps': 24, 'idempotency_key': 'original-key'}})


def test_legacy_replay_restores_original_selectors_and_options_not_new_model_values():
    store = TraceStore()
    add_legacy_input_record(store, saved_run(store))
    # Later failed retries must not become the replay template.
    later = saved_run(store)
    store.append_event(later.run_id, type='tool.started', status='running', payload={
        'name': 'generate_video', 'arguments': arguments(reference_image_attachment_indices=[1, 3])})
    restored, task_id = recover(store, reference_image_attachment_indices=[1, 3],
                                width=864, height=480, duration_seconds=5, seed='123')
    assert restored['reference_image_data_urls'] == DATA[::-1]
    assert (restored['width'], restored['height'], restored['duration_seconds']) == (480, 864, 15)
    assert 'seed' not in restored and task_id is None
    assert restored['prompt'] == 'original scene'


@pytest.mark.asyncio
async def test_new_video_revision_reuses_conversation_images_with_new_prompt(engine):
    saved_run(engine.trace_store)
    request = ChatRequest(user_id='owner', conversation_id='conversation', message='补上切菜镜头',
                          agent_id='super_chat')
    with patch('agent.skills.builtin.generate_video.generate_video',
               new=AsyncMock(return_value=video_response())) as generate:
        result = await engine._execute_skill_with_governance(request=request, run_id='revision',
            skill_name='generate_video', arguments=arguments(idempotency_key='new-key', prompt='include chopping scene'))
    assert result.success, result.error
    actual = generate.await_args.args[0]
    assert actual.reference_image_data_urls == DATA[::-1]
    assert actual.prompt == 'include chopping scene'
    assert actual.idempotency_key == 'new-key'


@pytest.mark.asyncio
async def test_new_uploads_take_precedence_over_historical_video_images(engine):
    from tests.test_spark_reference_video import attachments
    saved_run(engine.trace_store)
    request = ChatRequest(user_id='owner', conversation_id='conversation', message='use new images',
                          agent_id='super_chat', attachments=attachments())
    with patch('agent.skills.builtin.generate_video.generate_video',
               new=AsyncMock(return_value=video_response())) as generate:
        result = await engine._execute_skill_with_governance(request=request, run_id='revision',
            skill_name='generate_video', arguments=arguments(idempotency_key='new-key',
                                                           reference_image_attachment_indices=[1, 2]))
    assert result.success, result.error
    assert generate.await_args.args[0].reference_image_data_urls == DATA


def test_conversation_image_recovery_uses_latest_set_and_never_mixes_sets(tmp_path):
    store = TraceStore(tmp_path / 'trace.db')
    saved_run(store)
    latest = store.start_run(user_id='owner', conversation_id='conversation', input_text='new reference',
                             agent_id='super_chat', runtime='self')
    store.append_event(latest.run_id, type='context.built', status='completed', payload={
        'final_model_request': {'messages': [{'role': 'user', 'content': [
            {'type': 'text', 'text': 'Attachment 1: new.png'},
            {'type': 'image_url', 'image_url': {'url': DATA[1]}},
        ]}]}})
    restored_store = TraceStore(tmp_path / 'trace.db')
    opts = dict(user_id='owner', conversation_id='conversation', allow_conversation_images=True)
    result, task_id = recover_video_request(restored_store, **opts,
        arguments=arguments(idempotency_key='new-key', reference_image_attachment_indices=[1]))
    assert result['reference_image_data_urls'] == [DATA[1]] and task_id is None
    with pytest.raises(ValueError, match='latest'):
        recover_video_request(restored_store, **opts, arguments=arguments(idempotency_key='new-key'))


@pytest.mark.parametrize('user,conversation', [('other', 'conversation'), ('owner', 'other')])
def test_conversation_image_recovery_is_owner_and_conversation_scoped(user, conversation):
    store = TraceStore()
    saved_run(store, user=user, conversation=conversation)
    source = arguments(idempotency_key='new-key')
    result, task_id = recover_video_request(store, user_id='owner', conversation_id='conversation',
        arguments=source, allow_conversation_images=True)
    assert result == source and task_id is None


@pytest.mark.asyncio
async def test_legacy_reordered_followup_replays_provider_asset_keys_without_conflict(engine, tmp_path):
    import base64, json
    from tests.test_spark_reference_video import IDS
    add_legacy_input_record(engine.trace_store, saved_run(engine.trace_store))
    uploads = []
    def handler(request):
        if request.url.path == '/v1/assets':
            slot = len(uploads)
            uploads.append(request)
            expected = base64.b64decode(DATA[::-1][slot].split(',', 1)[1])
            if request.content != expected:
                return httpx.Response(409, json={'error': {'code': 'idempotency_conflict'}})
            return httpx.Response(201, json={'id': IDS[slot], 'status': 'ready'})
        if request.method == 'POST':
            body = json.loads(request.content)
            assert body['input']['reference_image_asset_ids'] == IDS
            assert body['input']['duration_seconds'] == 15
            return httpx.Response(202, json=task())
        return httpx.Response(200, content=mp4(), headers={'Content-Type': 'video/mp4'})
    client = SparkVideoClient('https://spark.test', 'secret', output_dir=tmp_path,
                              transport=httpx.MockTransport(handler))
    request = ChatRequest(user_id='owner', conversation_id='conversation', message='继续查原视频', agent_id='super_chat')
    with patch('agent.aigc.video_service.SparkVideoClient', return_value=client):
        result = await engine._execute_skill_with_governance(request=request, run_id='replay',
            skill_name='generate_video', arguments=arguments(reference_image_attachment_indices=[1, 3]))
    assert result.success, result.error
    assert len(uploads) == 2


@pytest.mark.asyncio
async def test_full_request_is_frozen_before_failure_and_restored_after_restart(engine, tmp_path):
    from tests.test_spark_reference_video import attachments
    from agent.skills.governance import ToolGovernance
    engine.trace_store = TraceStore(tmp_path / 'trace.db')
    engine.tool_governance = ToolGovernance(engine.trace_store)
    request = ChatRequest(user_id='owner', conversation_id='conversation', message='generate',
                          agent_id='super_chat', attachments=attachments())
    initial = arguments(reference_image_attachment_indices=[2, 1], duration_seconds=15)
    with patch('agent.skills.builtin.generate_video.generate_video', new=AsyncMock(
            side_effect=SparkProviderError('timeout', code='wait_timeout'))) as generate:
        failed = await engine._execute_skill_with_governance(request=request, run_id='first',
            skill_name='generate_video', arguments=initial)
    assert not failed.success
    original = generate.await_args.args[0].model_dump()
    engine.trace_store = TraceStore(tmp_path / 'trace.db')
    engine.tool_governance = ToolGovernance(engine.trace_store)
    followup = request.model_copy(update={'attachments': []})
    changed = arguments(prompt='model rewrote prompt', reference_image_attachment_indices=[1, 2],
                         duration_seconds=5, seed='999')
    with patch('agent.skills.builtin.generate_video.generate_video', new=AsyncMock(return_value=video_response())) as generate:
        result = await engine._execute_skill_with_governance(request=followup, run_id='second',
            skill_name='generate_video', arguments=changed)
    assert result.success
    assert generate.await_args.args[0].model_dump() == original


@pytest.mark.parametrize('persisted', [False, True])
def test_private_replay_inputs_are_immutable_scoped_and_purged(tmp_path, persisted):
    path = tmp_path / 'trace.db' if persisted else None
    store = TraceStore(path)
    original = {'idempotency_key': 'key', 'prompt': 'private prompt', 'reference_image_data_urls': DATA}
    frozen = store.freeze_video_request('owner', 'conversation', original)
    frozen['prompt'] = 'mutated caller result'
    assert store.freeze_video_request('owner', 'conversation', {'idempotency_key': 'key', 'prompt': 'changed'}) == original
    assert store.get_video_request('other', 'conversation', 'key') is None
    assert store.get_video_request('owner', 'other', 'key') is None
    store.freeze_video_request('other', 'conversation', original)
    store.purge_user('owner')
    if persisted:
        store = TraceStore(path)
    assert store.get_video_request('owner', 'conversation', 'key') is None
    assert store.get_video_request('other', 'conversation', 'key') == original
    assert 'private prompt' not in store.list_runs_page(user_id='other').model_dump_json()


@pytest.mark.asyncio
async def test_approval_freezes_video_only_after_user_allows(engine):
    from tests.test_spark_reference_video import attachments
    request = ChatRequest(user_id='owner', conversation_id='conversation', message='看看状态',
                          agent_id='super_chat', attachments=attachments(), tool_policies={'generate_video': 'confirm'})
    with patch('agent.skills.builtin.generate_video.generate_video', new=AsyncMock(return_value=video_response())) as generate:
        result = await engine._execute_skill_with_governance(request=request, run_id='approval-run',
            skill_name='generate_video', arguments=arguments(reference_image_attachment_indices=[2, 1]))
        assert not result.success and result.error_code == 'explicit_confirmation_required'
        assert engine.trace_store.get_video_request('owner', 'conversation', 'original-key') is None
        engine.tool_governance.seal_run_approvals('approval-run')
        resolved = await engine.tool_governance.resolve_approval(result.data['governance']['approval_id'],
            user_id='owner', decision='allow_once')
    assert resolved['succeeded_count'] == 1
    assert generate.await_count == 1
    assert engine.trace_store.get_video_request('owner', 'conversation', 'original-key')['reference_image_data_urls'] == DATA[::-1]
