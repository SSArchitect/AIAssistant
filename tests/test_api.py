"""Integration tests for FastAPI endpoints (no LLM calls)."""
from __future__ import annotations

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from unittest.mock import AsyncMock, patch

import agent.main as main_module
from agent.llm.base import LLMResponse
from agent.main import app, skill_registry, lifespan, trace_store


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "AGENT_MEMORY_STORAGE_PATH",
        str(tmp_path / "agent_memory.json"),
    )
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            yield ac


@pytest.mark.asyncio
async def test_health(client):
    resp = await client.get("/agent/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["skills_count"] >= 3  # echo, datetime, calculator


@pytest.mark.asyncio
async def test_list_skills(client):
    resp = await client.get("/agent/skills")
    assert resp.status_code == 200
    data = resp.json()
    assert "skills" in data
    names = {s["name"] for s in data["skills"]}
    assert "echo" in names
    assert "datetime" in names
    assert "calculator" in names
    assert "search" in names


@pytest.mark.asyncio
async def test_list_skills_has_parameters(client):
    resp = await client.get("/agent/skills")
    data = resp.json()
    for skill in data["skills"]:
        assert "name" in skill
        assert "description" in skill
        assert "parameters" in skill
        assert "source" in skill
        assert "enabled" in skill


@pytest.mark.asyncio
async def test_list_agents(client):
    resp = await client.get("/agent/agents")
    assert resp.status_code == 200
    data = resp.json()
    assert "agents" in data
    agents = {agent["id"]: agent for agent in data["agents"]}
    assert "general_assistant" in agents
    assert agents["general_assistant"]["runtime"] == "self"
    assert agents["image_generation_v1"]["enabled"] is True
    assert "image_generation" in agents["image_generation_v1"]["capabilities"]
    assert "prompt_refine" in agents["image_generation_v1"]["capabilities"]
    image_quick_actions = agents["image_generation_v1"]["metadata"]["quick_actions"]
    assert {action["id"] for action in image_quick_actions} >= {"generate", "refine", "reference", "help"}
    assert next(action for action in image_quick_actions if action["id"] == "help")["auto_send"] is True
    image_command_protocol = agents["image_generation_v1"]["metadata"]["command_protocol"]
    assert image_command_protocol["version"] == "agent_command.v1"
    assert "生图" in image_command_protocol["aliases"]
    assert "/refine <提示词>" in image_command_protocol["commands"]
    assert agents["weight_loss_v1"]["enabled"] is True
    assert "food_image_calorie_estimation" in agents["weight_loss_v1"]["capabilities"]
    assert "calorie_deficit_tracking" in agents["weight_loss_v1"]["capabilities"]
    quick_actions = agents["weight_loss_v1"]["metadata"]["quick_actions"]
    action_ids = {action["id"] for action in quick_actions}
    assert action_ids >= {"today", "history", "goal", "profile", "help"}
    assert action_ids.isdisjoint({"log", "exercise", "undo"})
    assert next(action for action in quick_actions if action["id"] == "today")["auto_send"] is True
    command_protocol = agents["weight_loss_v1"]["metadata"]["command_protocol"]
    assert command_protocol["version"] == "agent_command.v1"
    assert "减肥" in command_protocol["aliases"]
    assert agents["deep_research_v1"]["enabled"] is True
    assert "deep_research" in agents["deep_research_v1"]["capabilities"]
    assert agents["deep_research_v1"]["metadata"]["execution_mode"] == "workflow_job"
    assert agents["deep_research_v1"]["metadata"]["entrypoint"] == "super_chat_mode_only"
    assert agents["deep_research_v1"]["metadata"]["super_chat_mode_id"] == "deep_research"
    assert "command_protocol" not in agents["deep_research_v1"]["metadata"]
    assert "quick_actions" not in agents["deep_research_v1"]["metadata"]
    research_policy = agents["deep_research_v1"]["metadata"]["research_policy"]
    assert research_policy["requires_plan_confirmation"] is True
    assert research_policy["target_result_count"] == 400
    assert "langgraph_research" in agents
    assert "knowledge_qa_self_v1" not in agents
    assert "knowledge_qa_langgraph_v1" not in agents


@pytest.mark.asyncio
async def test_list_roles(client):
    resp = await client.get("/agent/roles")
    assert resp.status_code == 200
    data = resp.json()
    roles = {role["id"]: role for role in data["roles"]}
    assert set(roles) == {"default", "work_partner", "learning_coach", "初一"}
    assert roles["default"]["memory_enabled"] is True
    assert roles["default"]["metadata"]["localized"]["en"]["name"] == "Everyday Assistant"
    assert roles["work_partner"]["metadata"]["localized"]["zh"]["name"] == "工作搭档"
    assert roles["work_partner"]["metadata"]["preferences"]
    assert roles["初一"]["metadata"]["built_in"] is True
    assert roles["初一"]["metadata"]["localized"]["en"]["name"] == "Chuyi"


@pytest.mark.asyncio
async def test_create_update_delete_role(client):
    create_resp = await client.post(
        "/agent/roles",
        json={
            "id": "custom_writer",
            "name": "Custom Writer",
            "base_persona": "Write with a crisp editorial voice.",
            "instructions": ["Keep examples concrete."],
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["id"] == "custom_writer"
    assert created["metadata"]["built_in"] is False

    update_resp = await client.put(
        "/agent/roles/custom_writer",
        json={
            "name": "Custom Editor",
            "instructions": ["Keep examples concrete.", "Prefer active voice."],
        },
    )
    assert update_resp.status_code == 200
    updated = update_resp.json()
    assert updated["name"] == "Custom Editor"
    assert updated["instructions"][-1] == "Prefer active voice."

    delete_resp = await client.delete("/agent/roles/custom_writer")
    assert delete_resp.status_code == 200

    list_resp = await client.get("/agent/roles")
    role_ids = {role["id"] for role in list_resp.json()["roles"]}
    assert "custom_writer" not in role_ids


@pytest.mark.asyncio
async def test_custom_roles_are_scoped_by_user_id(client):
    create_a = await client.post(
        "/agent/roles",
        json={
            "user_id": "account-a",
            "id": "private_helper",
            "name": "Account A Helper",
        },
    )
    create_b = await client.post(
        "/agent/roles",
        json={
            "user_id": "account-b",
            "id": "private_helper",
            "name": "Account B Helper",
        },
    )
    assert create_a.status_code == 200
    assert create_b.status_code == 200
    assert create_a.json()["metadata"]["owner_user_id"] == "account-a"
    assert create_b.json()["metadata"]["owner_user_id"] == "account-b"

    list_a = await client.get("/agent/roles", params={"user_id": "account-a"})
    list_b = await client.get("/agent/roles", params={"user_id": "account-b"})
    roles_a = {role["id"]: role for role in list_a.json()["roles"]}
    roles_b = {role["id"]: role for role in list_b.json()["roles"]}

    assert set(roles_a) == {"default", "work_partner", "learning_coach", "初一", "private_helper"}
    assert set(roles_b) == {"default", "work_partner", "learning_coach", "初一", "private_helper"}
    assert roles_a["private_helper"]["name"] == "Account A Helper"
    assert roles_b["private_helper"]["name"] == "Account B Helper"

    update_a = await client.put(
        "/agent/roles/private_helper",
        json={
            "user_id": "account-a",
            "name": "Account A Updated",
        },
    )
    assert update_a.status_code == 200

    list_b_after_update = await client.get("/agent/roles", params={"user_id": "account-b"})
    roles_b_after_update = {role["id"]: role for role in list_b_after_update.json()["roles"]}
    assert roles_b_after_update["private_helper"]["name"] == "Account B Helper"

    delete_a = await client.delete(
        "/agent/roles/private_helper",
        params={"user_id": "account-a"},
    )
    assert delete_a.status_code == 200

    roles_a_after_delete = {
        role["id"]
        for role in (await client.get("/agent/roles", params={"user_id": "account-a"})).json()["roles"]
    }
    roles_b_after_delete = {
        role["id"]
        for role in (await client.get("/agent/roles", params={"user_id": "account-b"})).json()["roles"]
    }
    assert "private_helper" not in roles_a_after_delete
    assert "private_helper" in roles_b_after_delete


@pytest.mark.asyncio
async def test_cannot_delete_builtin_role(client):
    resp = await client.delete("/agent/roles/default")
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_create_and_list_role_memory(client):
    create_resp = await client.post(
        "/agent/roles/default/memories",
        json={
            "kind": "long_term",
            "content": "User prefers compact summaries",
            "tags": ["api-test"],
        },
    )
    assert create_resp.status_code == 200
    created = create_resp.json()
    assert created["content"] == "User prefers compact summaries"

    list_resp = await client.get(
        "/agent/roles/default/memories",
        params={"kind": "long_term"},
    )
    assert list_resp.status_code == 200
    memories = list_resp.json()["memories"]
    assert any(memory["id"] == created["id"] for memory in memories)


@pytest.mark.asyncio
async def test_role_memory_api_is_scoped_by_user_id(client):
    create_a = await client.post(
        "/agent/roles/default/memories",
        json={
            "user_id": "account-a",
            "kind": "long_term",
            "content": "Account A private memory",
        },
    )
    create_b = await client.post(
        "/agent/roles/default/memories",
        json={
            "user_id": "account-b",
            "kind": "long_term",
            "content": "Account B private memory",
        },
    )
    assert create_a.status_code == 200
    assert create_b.status_code == 200

    list_a = await client.get(
        "/agent/roles/default/memories",
        params={"user_id": "account-a", "kind": "long_term"},
    )
    assert list_a.status_code == 200
    contents = [memory["content"] for memory in list_a.json()["memories"]]
    assert "Account A private memory" in contents
    assert "Account B private memory" not in contents


@pytest.mark.asyncio
async def test_delete_role_memory(client):
    create_resp = await client.post(
        "/agent/roles/default/memories",
        json={
            "kind": "long_term",
            "content": "Temporary debug memory",
            "source": "api-test",
        },
    )
    assert create_resp.status_code == 200
    memory_id = create_resp.json()["id"]

    delete_resp = await client.delete(
        f"/agent/roles/default/memories/{memory_id}"
    )
    assert delete_resp.status_code == 200

    list_resp = await client.get(
        "/agent/roles/default/memories",
        params={"kind": "long_term"},
    )
    assert list_resp.status_code == 200
    memories = list_resp.json()["memories"]
    assert all(memory["id"] != memory_id for memory in memories)


@pytest.mark.asyncio
async def test_get_run_trace(client):
    run = trace_store.start_run(
        conversation_id="trace-api-conv",
        input_text="hello",
        agent_id="general_assistant",
        runtime="self",
    )
    trace_store.complete_run(run.run_id, output="hi")

    resp = await client.get(f"/agent/runs/{run.run_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["run_id"] == run.run_id
    assert data["status"] == "completed"
    assert [event["type"] for event in data["events"]] == [
        "run.started",
        "run.completed",
    ]


@pytest.mark.asyncio
async def test_chat_returns_run_trace_contract(client):
    """Chat endpoint should return the debug fields the gateway and UI rely on."""
    assert main_module.engine is not None
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="service is healthy",
            tool_calls=[],
            model="contract-test-model",
            usage={"input": 3, "output": 4},
        )
    )

    with patch.object(main_module.engine, "_get_provider", return_value=provider):
        resp = await client.post(
            "/agent/chat",
            json={
                "conversation_id": "api-contract-conv",
                "message": "ping",
                "agent_id": "general_assistant",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["conversation_id"] == "api-contract-conv"
    assert data["response"] == "service is healthy"
    assert data["agent_id"] == "general_assistant"
    assert data["role_id"] == "default"
    assert data["runtime"] == "self"
    assert data["run_id"].startswith("run_")
    assert data["model_used"] == "contract-test-model"
    assert data["tokens_used"] == {"input": 3, "output": 4}
    event_types = [event["type"] for event in data["events"]]
    assert event_types[0] == "run.started"
    assert "model.started" in event_types
    assert "model.completed" in event_types
    assert event_types[-1] == "run.completed"


@pytest.mark.asyncio
async def test_chat_stream_flushes_failed_trace_before_error(client):
    """Stream failures should include the final trace events before the error SSE."""
    assert main_module.engine is not None
    provider = AsyncMock()
    provider.chat = AsyncMock(side_effect=TimeoutError("Request timed out."))

    run_id = "run_stream_failure_trace"
    with patch.object(main_module.engine, "_get_provider", return_value=provider):
        resp = await client.post(
            "/agent/chat/stream",
            json={
                "conversation_id": "api-stream-fail-conv",
                "message": "ping",
                "agent_id": "general_assistant",
                "run_id": run_id,
            },
        )

    assert resp.status_code == 200
    text = resp.text
    assert "event: error" in text
    assert '"type": "model.failed"' in text
    assert '"type": "run.failed"' in text
    assert text.index('"type": "model.failed"') < text.index("event: error")

    run = trace_store.get_run(run_id)
    assert run is not None
    assert run.status == "failed"


@pytest.mark.asyncio
async def test_list_runs_filters_by_conversation(client):
    run_a = trace_store.start_run(
        conversation_id="filter-conv-a",
        input_text="a",
        agent_id="general_assistant",
        runtime="self",
    )
    trace_store.complete_run(run_a.run_id, output="A")
    run_b = trace_store.start_run(
        conversation_id="filter-conv-b",
        input_text="b",
        agent_id="general_assistant",
        runtime="self",
    )
    trace_store.complete_run(run_b.run_id, output="B")

    resp = await client.get("/agent/runs", params={"conversation_id": "filter-conv-a"})
    assert resp.status_code == 200
    data = resp.json()
    run_ids = {run["run_id"] for run in data["runs"]}
    assert run_a.run_id in run_ids
    assert run_b.run_id not in run_ids


@pytest.mark.asyncio
async def test_chat_missing_fields(client):
    """Chat endpoint should reject missing required fields."""
    resp = await client.post("/agent/chat", json={})
    assert resp.status_code == 422  # FastAPI validation error


@pytest.mark.asyncio
async def test_chat_missing_message(client):
    """Chat endpoint should reject request without message field."""
    resp = await client.post("/agent/chat", json={
        "conversation_id": "test-conv",
    })
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_generate_followups_uses_llm_response(client):
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content='{"questions":["能直接列一张法国清单吗","路线怎么按天安排","预算大概怎么分配","多余问题"]}',
            model="followup-test-model",
        )
    )

    with patch.object(main_module, "create_provider", return_value=provider):
        resp = await client.post(
            "/agent/followups",
            json={
                "user_question": "法国第一次去怎么玩？",
                "assistant_answer": "可以先把法国最值得玩的精华浓缩成一张清单，再按天数和兴趣做路线。",
                "language": "zh",
                "model_preference": "claude",
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["questions"] == [
        "能直接列一张法国清单吗？",
        "路线怎么按天安排？",
        "预算大概怎么分配？",
    ]
    assert data["model_used"] == "followup-test-model"
    provider.chat.assert_awaited_once()
    messages = provider.chat.await_args.args[0]
    assert "下一步追问生成器" in messages[0].content
    assert "法国第一次去怎么玩" in messages[1].content


@pytest.mark.asyncio
async def test_generate_image_endpoint(client):
    minimax_client = AsyncMock()
    minimax_client.image_model = "image-01"
    minimax_client.generate_image = AsyncMock(
        return_value={
            "id": "img_123",
            "data": {
                "image_urls": [
                    "https://example.com/generated.png",
                ],
            },
        }
    )

    with patch.object(
        main_module.MiniMaxAIGCClient,
        "from_runtime_config",
        return_value=minimax_client,
    ):
        resp = await client.post(
            "/agent/aigc/image",
            json={
                "prompt": "a clean product shot of a smart desk lamp",
                "aspect_ratio": "16:9",
                "n": 1,
                "prompt_optimizer": True,
            },
        )

    assert resp.status_code == 200
    data = resp.json()
    assert data["provider"] == "minimax"
    assert data["model"] == "image-01"
    assert data["aspect_ratio"] == "16:9"
    assert data["images"][0]["url"] == "https://example.com/generated.png"
    minimax_client.generate_image.assert_awaited_once()
