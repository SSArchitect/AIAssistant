import asyncio

import httpx
import pytest

from agent.trace import TraceStore
from agent.aigc.progress import progress_scope, tool_timeout
from agent.aigc.spark_client import SparkImageClient
from agent.schemas.aigc import ImageGenerationRequest


def test_trace_survives_restart_and_marks_unfinished_work(tmp_path):
    path = tmp_path / 'runs.db'
    store = TraceStore(path)
    done = store.start_run(conversation_id='c', user_id='a', input_text='done', agent_id='super_chat', runtime='self')
    store.complete_run(done.run_id, output='result', artifacts=[{'url': '/result.png'}])
    pending = store.start_run(conversation_id='c', user_id='b', input_text='pending', agent_id='super_chat', runtime='self')
    store.append_event(pending.run_id, type='media.task.progress', status='running', payload={'stage': 'queued', 'task_id': 'provider-1'})
    restored = TraceStore(path)
    assert restored.get_run(done.run_id).output == 'result'
    assert restored.get_run(done.run_id).artifacts == [{'url': '/result.png'}]
    assert restored.get_run(pending.run_id).status == 'interrupted'
    assert restored.get_run(pending.run_id).events[-2].payload['task_id'] == 'provider-1'
    assert [r.run_id for r in restored.list_runs(user_id='a')] == [done.run_id]
    restored.purge_user('a')
    assert TraceStore(path).get_run(done.run_id) is None
    assert TraceStore(path).get_run(pending.run_id) is not None


@pytest.mark.asyncio
async def test_soft_deadline_tracks_same_provider_task_without_resubmitting(tmp_path):
    calls = []
    events = []
    async def handler(request):
        calls.append(request.method)
        return httpx.Response(200, json={'id': 'provider-1', 'status': 'queued'})
    client = SparkImageClient('https://spark.test', 'secret', output_dir=tmp_path,
        timeout=.015, poll_interval=.005, transport=httpx.MockTransport(handler))
    with progress_scope(events.append, background=True):
        work = asyncio.create_task(client.generate(ImageGenerationRequest(prompt='cat', idempotency_key='same-key')))
        await asyncio.sleep(.055)
        assert not work.done()
        work.cancel()
        with pytest.raises(asyncio.CancelledError):
            await work
    assert calls.count('POST') == 1
    assert calls.count('GET') > 1
    assert any(e['stage'] == 'queued' for e in events)
    assert any(e['stage'] == 'reconnecting' for e in events)
    assert all(e.get('idempotency_key') == 'same-key' for e in events)
    assert 'secret' not in str(events)


def test_background_timeout_is_scoped_to_long_tools():
    assert tool_timeout('generate_video', 570) == 570
    with progress_scope(lambda _: None, background=True):
        assert tool_timeout('generate_video', 570) > 570
        assert tool_timeout('calculator', 10) == 10
    assert tool_timeout('generate_video', 570) == 570


def test_task_projection_includes_old_active_roots_and_child_progress_only_for_owner():
    store = TraceStore()
    parent = store.start_run(conversation_id='c', user_id='a', input_text='research', agent_id='super_chat', runtime='self')
    child = store.start_run(conversation_id='c', user_id='a', input_text='internal', agent_id='deep_research_v1', runtime='self')
    foreign = store.start_run(conversation_id='other', user_id='b', input_text='private', agent_id='super_chat', runtime='self')
    store.append_event(parent.run_id, type='agent.tool.delegated', status='completed', payload={'child_run_id': child.run_id})
    store.append_event(child.run_id, type='research.search.started', status='running', payload={'query_index': 1, 'prompt': 'private raw prompt'})
    store.append_event(parent.run_id, type='agent.tool.delegated', status='completed', payload={'child_run_id': foreign.run_id})
    for i in range(55):
        run = store.start_run(conversation_id='recent', user_id='a', input_text=str(i), agent_id='super_chat', runtime='self')
        store.complete_run(run.run_id, output='large result')
    tasks = store.task_runs('a')
    assert len(tasks) == 51
    projected = next(r for r in tasks if r.run_id == parent.run_id)
    assert child.run_id not in [r.run_id for r in tasks]
    assert foreign.run_id not in [r.run_id for r in tasks]
    assert any(e.type == 'research.search.started' for e in projected.events)
    assert 'private raw prompt' not in projected.model_dump_json()
    assert all(r.output == '' for r in tasks)


@pytest.mark.asyncio
async def test_background_task_completes_after_soft_deadline(tmp_path, monkeypatch):
    events, calls = [], []
    first_get = True
    async def handler(request):
        nonlocal first_get
        calls.append(request.method)
        if request.method == 'POST':
            return httpx.Response(200, json={'id': 'provider-1', 'status': 'queued'})
        if first_get:
            first_get = False
            await asyncio.sleep(.1)
        return httpx.Response(200, json={'id': 'provider-1', 'status': 'succeeded', 'artifacts': [
            {'media_type': 'image/png', 'download_url': '/v1/tasks/provider-1/artifacts/one'}]})
    client = SparkImageClient('https://spark.test', 'secret', output_dir=tmp_path,
        timeout=.025, poll_interval=.001, transport=httpx.MockTransport(handler))
    async def download(*args, **kwargs): return b'png-result'
    monkeypatch.setattr(client, '_download', download)
    with progress_scope(events.append, background=True):
        result = await client.generate(ImageGenerationRequest(prompt='cat', idempotency_key='same-key'))
    assert result.id == 'provider-1'
    assert calls.count('POST') == 1
    assert events[-1]['stage'] == 'completed'
    assert any(e['stage'] == 'saving' for e in events)
    assert any(e['stage'] == 'reconnecting' for e in events)


@pytest.mark.asyncio
async def test_progress_isolated_across_concurrent_requests():
    from agent.aigc.progress import emit_progress
    a, b = [], []
    async def work(sink, name):
        with progress_scope(sink.append, background=True):
            await asyncio.sleep(0)
            emit_progress(stage=name)
    await asyncio.gather(work(a, 'a'), work(b, 'b'))
    assert a == [{'stage': 'a'}]
    assert b == [{'stage': 'b'}]


@pytest.mark.asyncio
async def test_background_deadline_is_bounded_and_keeps_provider_identity(tmp_path, monkeypatch):
    import agent.aigc.spark_client as module
    monkeypatch.setattr(module, 'BACKGROUND_TIMEOUT', .03)
    async def handler(request):
        return httpx.Response(200, json={'id': 'provider-1', 'status': 'queued'})
    client = SparkImageClient('https://spark.test', 'secret', output_dir=tmp_path,
        timeout=.01, poll_interval=.002, transport=httpx.MockTransport(handler))
    events = []
    with progress_scope(events.append, background=True):
        with pytest.raises(module.SparkProviderError) as error:
            await client.generate(ImageGenerationRequest(prompt='cat', idempotency_key='stable'))
    assert error.value.context() == {'code': 'wait_timeout', 'task_id': 'provider-1', 'idempotency_key': 'stable'}
    assert events[-1]['stage'] == 'unknown'


@pytest.mark.asyncio
async def test_provider_queue_and_progress_changes_emit_even_without_stage_change(tmp_path):
    from agent.aigc.spark_client import SparkProviderError
    events = []
    states = iter([
        {'id': 'p', 'status': 'queued', 'queue_position': 3},
        {'id': 'p', 'status': 'queued', 'queue_position': 2},
        {'id': 'p', 'status': 'running', 'progress_percent': 20},
        {'id': 'p', 'status': 'running', 'progress_percent': 50},
        {'id': 'p', 'status': 'failed'},
    ])
    client = SparkImageClient('https://spark.test', 'secret', output_dir=tmp_path, poll_interval=0,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=next(states))))
    with progress_scope(events.append):
        with pytest.raises(SparkProviderError):
            await client.generate(ImageGenerationRequest(prompt='cat'))
    assert [e['queue_position'] for e in events if 'queue_position' in e] == [3, 2]
    assert [e['progress_percent'] for e in events if 'progress_percent' in e] == [20, 50]


def test_task_metrics_reject_invalid_provider_numbers():
    from agent.aigc.spark_client import SparkTaskClient
    assert SparkTaskClient.task_metrics({'queue_position': True, 'progress_percent': float('nan')}) == {}
    assert SparkTaskClient.task_metrics({'queue_position': 0, 'progress_percent': '42'}) == {}
    assert SparkTaskClient.task_metrics({'queue_position': 2, 'progress_percent': 0}) == {'queue_position': 2, 'progress_percent': 0}
