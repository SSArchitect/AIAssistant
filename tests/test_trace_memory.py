"""Persistent traces keep large historical payloads on disk, with full API fidelity."""
import gc
import weakref

import pytest

from agent.trace import TraceStore
from agent.schemas.trace import RunEvent


def start(store, user='a', agent='super_chat'):
    return store.start_run(conversation_id='c', user_id=user, input_text='test',
                           agent_id=agent, runtime='self')


@pytest.mark.parametrize('finish', ['complete_run', 'fail_run', 'partial_run', 'cancel_run'])
def test_finished_payload_is_released_but_remains_readable(tmp_path, finish):
    store = TraceStore(tmp_path / 'trace.db')
    run = start(store)
    event = store.append_event(run.run_id, type='context.built', status='completed',
                               payload={'image': 'data:image/png;base64,' + 'x' * 100000})
    reference = weakref.ref(event)
    kwargs = {'error_message': 'test'} if finish == 'fail_run' else {'output': 'done'}
    completed = getattr(store, finish)(run.run_id, **kwargs)
    assert event in completed.events
    run_id = run.run_id
    del completed, run, event
    gc.collect()
    assert reference() is None, 'store must not retain completed image/context payloads'
    restored = store.get_run(run_id)
    assert restored.events[1].payload['image'].endswith('x' * 100000)
    assert store.list_runs_page(user_id='a').runs[0] == restored


def test_restart_does_not_deserialize_full_context_and_task_polling_stays_compact(tmp_path, monkeypatch):
    path = tmp_path / 'trace.db'
    store = TraceStore(path)
    parent, child, foreign = start(store), start(store), start(store, user='b')
    store.append_event(parent.run_id, type='agent.tool.delegated', status='completed',
                       payload={'child_run_id': child.run_id})
    store.append_event(parent.run_id, type='agent.tool.delegated', status='completed',
                       payload={'child_run_id': foreign.run_id})
    for run in (parent, child, foreign):
        store.append_event(run.run_id, type='context.built', status='completed',
                           payload={'private': 'large context'})
    store.append_event(child.run_id, type='media.task.progress', status='running',
                       payload={'kind': 'video', 'task_id': 'provider-id', 'stage': 'running', 'private': 'omit'})
    store.complete_run(child.run_id, output='child')
    store.complete_run(parent.run_id, output='parent')
    parse = RunEvent.model_validate_json

    def reject_context(value, *args, **kwargs):
        result = parse(value, *args, **kwargs)
        assert result.type != 'context.built', 'startup/task poll must not load large context events'
        return result

    with monkeypatch.context() as patch:
        patch.setattr(RunEvent, 'model_validate_json', reject_context)
        restored = TraceStore(path)
        tasks = restored.task_runs('a')
        assert len(tasks) == 1
        assert tasks[0].run_id == parent.run_id
        assert any(e.payload.get('task_id') == 'provider-id' for e in tasks[0].events)
        assert not any(e.run_id == foreign.run_id for e in tasks[0].events)
        assert 'private' not in tasks[0].model_dump_json()
    assert restored.get_run(foreign.run_id).status == 'interrupted'
    assert [e.type for e in restored.get_run(foreign.run_id).events] == [
        'run.started', 'context.built', 'run.interrupted']


def test_late_events_and_skill_updates_preserve_historical_payloads(tmp_path):
    path = tmp_path / 'trace.db'
    store = TraceStore(path)
    run = start(store)
    store.append_event(run.run_id, type='context.built', status='completed', payload={'original': True})
    store.complete_run(run.run_id, output='awaiting approval')
    store = TraceStore(path)
    store.append_event(run.run_id, type='approval.resolved', status='completed',
                       payload={'approval_id': 'approval-1', 'decision': 'allow_once'})
    store.record_skill_use(run.run_id, 'delete_todo')
    restored = TraceStore(path).get_run(run.run_id)
    assert restored.events[1].payload == {'original': True}
    assert restored.events[-1].payload['approval_id'] == 'approval-1'
    assert restored.skills_used == ['delete_todo']
    assert store.purge_user('a') == 1
    assert TraceStore(path).get_run(run.run_id) is None
