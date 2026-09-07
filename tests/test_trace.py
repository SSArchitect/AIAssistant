"""Unit tests for run tracing and debug event storage."""
from __future__ import annotations

from agent.trace import TraceStore


def test_round_reasoning_and_tool_results_keep_order_after_reload(tmp_path, engine):
    path = tmp_path / 'thoughts.db'
    engine.trace_store = TraceStore(path)
    run = engine.trace_store.start_run(conversation_id='thoughts', input_text='test', agent_id='general_assistant', runtime='self')
    first = engine.trace_store.append_event(run.run_id, type='model.started', status='running', payload={'round': 1})
    engine._record_model_reasoning(run.run_id, 'first plan')
    engine.trace_store.append_event(run.run_id, type='tool.completed', status='completed', payload={'result_preview': 'result'})
    second = engine.trace_store.append_event(run.run_id, type='model.started', status='running', payload={'round': 2})
    engine._record_model_reasoning(run.run_id, 'second plan')
    engine.trace_store.complete_run(run.run_id, output='answer', model_used='test', tokens_used={}, skills_used=[])
    restored = TraceStore(path).get_run(run.run_id)
    assert [event.type for event in restored.events] == [
        'run.started', 'model.started', 'model.reasoning', 'tool.completed', 'model.started', 'model.reasoning', 'run.completed',
    ]
    thoughts = [event.payload for event in restored.events if event.type == 'model.reasoning']
    assert thoughts == [
        {'text': 'first plan', 'model_event_id': first.id, 'round': 1},
        {'text': 'second plan', 'model_event_id': second.id, 'round': 2},
    ]


def test_trace_store_records_completed_run_with_events():
    store = TraceStore()
    run = store.start_run(
        conversation_id="conv-1",
        input_text="hello",
        agent_id="general_assistant",
        runtime="self",
    )
    store.append_event(
        run.run_id,
        type="model.started",
        status="running",
        title="Model call",
        payload={"round": 1},
    )
    completed = store.complete_run(
        run.run_id,
        output="hi",
        model_used="test-model",
        tokens_used={"input": 1, "output": 2},
        skills_used=["calculator"],
    )

    assert completed is not None
    assert completed.status == "completed"
    assert completed.output == "hi"
    assert completed.model_used == "test-model"
    assert completed.tokens_used == {"input": 1, "output": 2}
    assert completed.skills_used == ["calculator"]
    assert completed.duration_ms is not None
    assert [event.type for event in completed.events] == [
        "run.started",
        "model.started",
        "run.completed",
    ]


def test_trace_store_filters_and_orders_runs():
    store = TraceStore()
    first = store.start_run(
        conversation_id="same-conv",
        input_text="first",
        agent_id="general_assistant",
        runtime="self",
    )
    second = store.start_run(
        conversation_id="same-conv",
        input_text="second",
        agent_id="general_assistant",
        runtime="self",
    )
    other = store.start_run(
        conversation_id="other-conv",
        input_text="other",
        agent_id="general_assistant",
        runtime="self",
    )

    same_conv_runs = store.list_runs(conversation_id="same-conv")

    assert [run.run_id for run in same_conv_runs] == [second.run_id, first.run_id]
    assert other.run_id not in {run.run_id for run in same_conv_runs}


def test_trace_store_filters_runs_by_user_id():
    store = TraceStore()
    run_a = store.start_run(
        conversation_id="shared-conv",
        user_id="a",
        input_text="a",
        agent_id="general_assistant",
        runtime="self",
    )
    run_b = store.start_run(
        conversation_id="shared-conv",
        user_id="b",
        input_text="b",
        agent_id="general_assistant",
        runtime="self",
    )

    user_a_runs = store.list_runs(conversation_id="shared-conv", user_id="a")

    assert [run.run_id for run in user_a_runs] == [run_a.run_id]
    assert run_b.run_id not in {run.run_id for run in user_a_runs}


def test_trace_store_purges_only_target_user_runs():
    store = TraceStore()
    run_a = store.start_run(
        conversation_id="shared-conv",
        user_id="a",
        input_text="a",
        agent_id="general_assistant",
        runtime="self",
    )
    run_b = store.start_run(
        conversation_id="shared-conv",
        user_id="b",
        input_text="b",
        agent_id="general_assistant",
        runtime="self",
    )

    assert store.purge_user("a") == 1
    assert store.get_run(run_a.run_id) is None
    assert store.get_run(run_b.run_id) is not None


def test_trace_store_marks_failed_run():
    store = TraceStore()
    run = store.start_run(
        conversation_id="conv-1",
        input_text="hello",
        agent_id="general_assistant",
        runtime="self",
    )
    failed = store.fail_run(
        run.run_id,
        error_message="provider unavailable",
        error_type="provider_error",
        output="provider unavailable",
    )

    assert failed is not None
    assert failed.status == "failed"
    assert failed.error_type == "provider_error"
    assert failed.error_message == "provider unavailable"
    assert failed.output == "provider unavailable"
    assert [event.type for event in failed.events] == ["run.started", "run.failed"]


def test_trace_store_marks_partial_run():
    store = TraceStore()
    run = store.start_run(
        conversation_id="conv-partial",
        input_text="hello",
        agent_id="general_assistant",
        runtime="self",
    )
    partial = store.partial_run(
        run.run_id,
        output="partial answer",
        error_type="max_tool_rounds_reached",
        error_message="max_model_rounds_reached",
        model_used="test-model",
        tokens_used={"input": 3, "output": 4},
        skills_used=["search"],
    )

    assert partial is not None
    assert partial.status == "partial"
    assert partial.output == "partial answer"
    assert partial.error_type == "max_tool_rounds_reached"
    assert partial.error_message == "max_model_rounds_reached"
    assert partial.tokens_used == {"input": 3, "output": 4}
    assert [event.type for event in partial.events] == ["run.started", "run.partial"]
    assert partial.events[-1].payload["response_status"] == "partial_summary"


def test_trace_store_records_approval_resolution_after_completed_run():
    store = TraceStore()
    run = store.start_run(
        conversation_id="conv-approval",
        user_id="user-1",
        input_text="delete the selected items",
        agent_id="general_assistant",
        runtime="self",
    )
    store.append_event(
        run.run_id,
        type="approval.required",
        status="pending",
        title="Approval required",
        payload={
            "approval_id": "approval-1",
            "tool_name": "delete_todo",
            "operations": [{"arguments": {"todo_id": "todo-1"}}],
        },
    )
    store.complete_run(run.run_id, output="Waiting for approval")

    store.append_event(
        run.run_id,
        type="approval.resolved",
        status="completed",
        title="Approval resolved",
        payload={
            "approval_id": "approval-1",
            "decision": "allow_once",
            "completed_count": 1,
        },
    )
    store.record_skill_use(run.run_id, "delete_todo")

    completed = store.get_run(run.run_id)
    assert completed is not None
    assert completed.status == "completed"
    assert completed.skills_used == ["delete_todo"]
    assert [event.type for event in completed.events] == [
        "run.started",
        "approval.required",
        "run.completed",
        "approval.resolved",
    ]


def test_task_summary_keeps_optional_metrics_and_research_counts():
    store = TraceStore()
    run = store.start_run(conversation_id='c', user_id='a', input_text='video', agent_id='super_chat', runtime='self')
    store.append_event(run.run_id, type='media.task.progress', status='running',
        payload={'kind': 'video', 'stage': 'queued', 'queue_position': 2, 'progress_percent': 0, 'private': 'omit'})
    store.append_event(run.run_id, type='research.step_summary.started', status='running',
        payload={'chunk': 2, 'chunk_count': 3, 'prompt': 'omit'})
    events = store.task_runs('a')[0].events
    assert events[-2].payload == {'kind': 'video', 'stage': 'queued', 'queue_position': 2, 'progress_percent': 0}
    assert events[-1].payload == {'chunk': 2, 'chunk_count': 3}
