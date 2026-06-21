"""Unit tests for run tracing and debug event storage."""
from __future__ import annotations

from agent.trace import TraceStore


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
