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
    restored, task_id = recover(store, reference_image_attachment_indices=[2])
    assert restored['reference_image_attachment_indices'] == [2]
    assert task_id is None
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
