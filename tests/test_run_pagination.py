from datetime import datetime, timezone

import pytest

from agent.trace import TraceStore


def add_run(store, index, user="alice", conversation="chat"):
    run = store.start_run(conversation_id=conversation, user_id=user,
                          input_text=str(index), agent_id="super_chat", runtime="self",
                          run_id=f"run_{index:03d}")
    run.started_at = datetime(2026, 9, 16, tzinfo=timezone.utc)
    return run


def test_run_pages_use_tie_breaker_and_survive_inserts_and_deleted_boundary():
    store = TraceStore()
    for index in range(23):
        add_run(store, index)
    add_run(store, 100, user="bob")
    add_run(store, 101, conversation="other")
    first = store.list_runs_page(user_id="alice", conversation_id="chat")
    assert [r.run_id for r in first.runs] == [f"run_{i:03d}" for i in range(22, 12, -1)]
    assert first.has_more and first.next_cursor
    add_run(store, 102)
    del store._runs[first.runs[-1].run_id]
    second = store.list_runs_page(user_id="alice", conversation_id="chat", cursor=first.next_cursor)
    assert [r.run_id for r in second.runs] == [f"run_{i:03d}" for i in range(12, 2, -1)]
    last = store.list_runs_page(user_id="alice", conversation_id="chat", cursor=second.next_cursor)
    assert [r.run_id for r in last.runs] == ["run_002", "run_001", "run_000"]
    assert not last.has_more and last.next_cursor == ""


def test_empty_and_exact_page_have_no_next_cursor():
    store = TraceStore()
    assert store.list_runs_page(user_id="alice").runs == []
    for index in range(10):
        add_run(store, index)
    page = store.list_runs_page(user_id="alice")
    assert len(page.runs) == 10
    assert not page.has_more and page.next_cursor == ""


@pytest.mark.parametrize("cursor", ["garbage!", "e30=", "W10=", "x" * 2048])
def test_invalid_cursor_is_rejected(cursor):
    with pytest.raises(ValueError, match="cursor"):
        TraceStore().list_runs_page(cursor=cursor)
