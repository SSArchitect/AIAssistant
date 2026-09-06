import asyncio

import pytest

from agent.runs.store import ConnectRuns, RunConflict
from agent.schemas.chat import ChatRequest, ChatResponse


def request(**updates):
    return ChatRequest(conversation_id="conv", user_id="alice", message="hello", run_id="run_1", agent_id="super_chat").model_copy(update=updates)


def test_admission_deduplicates_and_rejects_changed_identity(tmp_path):
    store = ConnectRuns(tmp_path / "runs.db")
    assert store.reserve(request())
    assert not store.reserve(request())
    with pytest.raises(RunConflict):
        store.reserve(request(user_id="bob"))
    with pytest.raises(RunConflict):
        store.reserve(request(message="different"))
    assert store.get("run_1", "bob") is None


def test_restart_retains_final_and_does_not_replay_unfinished(tmp_path):
    path = tmp_path / "runs.db"
    store = ConnectRuns(path)
    store.reserve(request())
    store.finish("run_1", "completed", ChatResponse(conversation_id="conv", response="result", citations=[{"title": "source", "url": "https://example.com"}]))
    store.reserve(request(run_id="run_2"))
    recovered = ConnectRuns(path)
    assert recovered.get("run_1", "alice")["response"]["citations"][0]["title"] == "source"
    assert recovered.get("run_2", "alice")["status"] == "interrupted"
    assert not recovered.reserve(request(run_id="run_2"))


def test_duplicate_submission_executes_once_and_cancel_is_terminal(tmp_path):
    async def scenario():
        store = ConnectRuns(tmp_path / "runs.db")
        calls = []
        active = {}
        async def process(req):
            calls.append(req.run_id)
            await asyncio.sleep(0)
            return ChatResponse(conversation_id="conv", response="complete")
        store.submit(request(), process, active)
        store.submit(request(), process, active)
        await asyncio.gather(*list(store.tasks.values()))
        assert calls == ["run_1"]
        assert store.get("run_1", "alice")["status"] == "completed"
        async def slow(req):
            await asyncio.sleep(100)
        store.submit(request(run_id="run_2"), slow, active)
        await asyncio.sleep(0)
        await store.close()
        assert store.get("run_2", "alice")["status"] == "cancelled"
    asyncio.run(scenario())


def test_cancel_before_first_scheduling_is_persisted(tmp_path):
    async def scenario():
        store = ConnectRuns(tmp_path / "runs.db")
        active = {}
        async def process(req):
            pytest.fail("cancelled admission executed")
        store.submit(request(), process, active)
        await store.close()
        assert store.get("run_1", "alice")["status"] == "cancelled"
        assert not active and not store.tasks
    asyncio.run(scenario())


def test_account_purge_stops_owned_runs_and_retains_other_users(tmp_path):
    async def scenario():
        store = ConnectRuns(tmp_path / "runs.db")
        async def process(req):
            await asyncio.sleep(100)
        active = {}
        store.submit(request(), process, active)
        store.reserve(request(run_id="bob-run", user_id="bob"))
        await store.purge_user("alice")
        assert store.get("run_1", "alice") is None
        assert store.get("bob-run", "bob") is not None
        assert not active and not store.tasks
    asyncio.run(scenario())
