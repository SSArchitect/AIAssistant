import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

import agent.main as main
from agent.runs.store import ConnectRuns
from agent.schemas.chat import ChatResponse
from agent.schemas.memory import RoleProfile
from agent.llm.base import LLMMessage, LLMResponse


@pytest.mark.asyncio
async def test_connect_admission_lookup_conflict_and_engine_contract(tmp_path, monkeypatch):
    store = ConnectRuns(tmp_path / "runs.db")
    calls = []
    async def process(request):
        calls.append(request)
        return ChatResponse(conversation_id=request.conversation_id, run_id=request.run_id, response="complete")
    monkeypatch.setattr(main, "connect_runs", store)
    monkeypatch.setattr(main, "engine", SimpleNamespace(process=process))
    monkeypatch.setattr(main, "active_stream_tasks", {})
    body = {"run_id": "run", "user_id": "alice", "conversation_id": "conv", "message": "hello", "agent_id": "super_chat", "role_id": "mentor"}
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
        first = await client.post("/agent/connect/runs", json=body)
        assert first.status_code == 200
        await asyncio.gather(*list(store.tasks.values()))
        repeat = await client.post("/agent/connect/runs", json=body)
        assert repeat.json()["response"]["response"] == "complete"
        assert len(calls) == 1
        assert calls[0].role_id == "mentor"
        assert calls[0].user_id == "alice"
        assert (await client.post("/agent/connect/runs", json={**body, "role_id": "default"})).status_code == 409
        assert (await client.get("/agent/connect/runs/run?user_id=alice")).status_code == 200
        assert (await client.get("/agent/connect/runs/run?user_id=bob")).status_code == 404
        assert (await client.post("/agent/connect/runs", json={**body, "message": "changed"})).status_code == 409
        assert (await client.post("/agent/connect/runs", json={**body, "agent_id": "other"})).status_code == 400
        assert (await client.post("/agent/connect/runs", json={**body, "run_id": ""})).status_code == 400
    await store.close()


@pytest.mark.asyncio
async def test_connect_new_conversation_reuses_persona_and_long_term_memory_only(tmp_path, monkeypatch, engine):
    store = ConnectRuns(tmp_path / "persona-runs.db")
    engine.role_memory.register_role(RoleProfile(id="mentor", name="Mentor", base_persona="Patient interview coach"), user_id="alice")
    engine.role_memory.add_memory(role_id="mentor", user_id="alice", kind="long_term", content="User is preparing for developer interviews")
    engine.role_memory.register_role(RoleProfile(id="mentor", name="Other", base_persona="Bob private persona"), user_id="bob")
    engine.memory.add_many("user:alice:conversation:old", [LLMMessage(role="user", content="OLD_PRIVATE_TOPIC")])
    engine.memory.set_summary("user:alice:conversation:old", "OLD_PRIVATE_SUMMARY")
    monkeypatch.setattr(main, "connect_runs", store)
    monkeypatch.setattr(main, "engine", engine)
    monkeypatch.setattr(main, "active_stream_tasks", {})
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(content="Let's practice.", model="test-model", usage={}))
    try:
        with patch.object(engine, "_get_provider", return_value=provider):
            async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as client:
                result = await client.post("/agent/connect/runs", json={"run_id":"new-run", "user_id":"alice", "conversation_id":"new", "message":"Start developer interview practice", "agent_id":"super_chat", "role_id":"mentor"})
                assert result.status_code == 200
                await asyncio.gather(*list(store.tasks.values()))
                await engine.wait_for_postprocessing()
                completed = (await client.get("/agent/connect/runs/new-run?user_id=alice")).json()
                assert completed["status"] == "completed"
                assert completed["response"]["role_id"] == "mentor"
        messages = provider.chat.call_args_list[0].args[0]
        prompt = messages[0].content
        assert "Patient interview coach" in prompt
        assert "preparing for developer interviews" in prompt
        assert "Bob private persona" not in prompt
        assert "OLD_PRIVATE" not in str(messages)
    finally:
        await store.close()
