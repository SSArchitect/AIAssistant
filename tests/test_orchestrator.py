"""Unit tests for the orchestrator engine with mock LLM."""
import asyncio
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agent.aigc.share_card_renderer import ShareCardRenderResult
from agent.orchestrator.engine import AgentEngine, DEEP_RESEARCH_PLAN_MARKER
from agent.llm.base import LLMResponse, ToolCall, LLMMessage
from agent.schemas.chat import ChatAttachment, ChatRequest
from agent.schemas.memory import MemoryCandidate, MemoryContext, RoleProfile
from agent.skills.registry import SkillRegistry
from agent.skills.builtin.echo import EchoSkill
from agent.skills.builtin.calculator import CalculatorSkill
from agent.skills.builtin.datetime_skill import DateTimeSkill
from agent.skills.builtin.open_url import OpenURLSkill
from agent.skills.builtin.search import SearchSkill
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult
from agent.weight_loss import WeightLossStore


@pytest.fixture
def registry():
    reg = SkillRegistry()
    reg.register(EchoSkill())
    reg.register(CalculatorSkill())
    reg.register(DateTimeSkill())
    reg.register(SearchSkill())
    reg.register(OpenURLSkill())
    return reg


@pytest.fixture
def engine(registry):
    return AgentEngine(registry)


def agent_tool_response(
    tool_name: str,
    task: str,
    reason: str,
    *,
    context: str = "",
) -> LLMResponse:
    arguments = {
        "task": task,
        "reason": reason,
    }
    if context:
        arguments["context"] = context
    return LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id=f"call_{tool_name}",
                name=tool_name,
                arguments=arguments,
            )
        ],
        model="router-model",
        usage={"input": 12, "output": 3},
    )


def tool_message_payloads(messages: list[LLMMessage]) -> list[dict]:
    payloads: list[dict] = []
    for message in messages:
        if message.role != "tool" or not isinstance(message.content, str):
            continue
        try:
            payload = json.loads(message.content)
        except json.JSONDecodeError:
            continue
        if isinstance(payload, dict):
            payloads.append(payload)
    return payloads


def deep_research_gap_response(
    *,
    supplemental_queries=None,
    status: str = "complete",
) -> LLMResponse:
    return LLMResponse(
        content=json.dumps(
            {
                "coverage_status": status,
                "summary": "现有来源足够支撑报告。",
                "missing_data": [],
                "supplemental_queries": supplemental_queries or [],
                "stop_reason": "no gaps",
            },
            ensure_ascii=False,
        ),
        tool_calls=[],
        model="gap-model",
        usage={"input": 4, "output": 4},
    )


def agent_tool_payload(messages: list[LLMMessage], agent_id: str) -> dict:
    for payload in tool_message_payloads(messages):
        data = payload.get("data")
        if isinstance(data, dict) and data.get("agent_id") == agent_id:
            return payload
    raise AssertionError(f"No agent tool payload for {agent_id}")


@pytest.mark.asyncio
async def test_simple_response_no_tools(engine):
    """When LLM responds without tool calls, return directly."""
    mock_response = LLMResponse(
        content="Hello! How can I help you?",
        tool_calls=[],
        model="test-model",
        usage={"input": 10, "output": 5},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=mock_response)
        mock_provider.return_value = provider

        request = ChatRequest(
            conversation_id="test-conv",
            message="Hello",
        )
        result = await engine.process(request)

    assert result.response == "Hello! How can I help you?"
    assert result.skills_used == []
    assert result.conversation_id == "test-conv"
    assert result.model_used == "test-model"
    assert result.agent_id == "general_assistant"
    assert result.runtime == "self"
    assert result.run_id
    tools = provider.chat.await_args.kwargs["tools"]
    tools_by_name = {tool.name: tool for tool in tools}
    assert "search" in tools_by_name
    assert "open_url" in tools_by_name
    assert "必须先调用 search 再回答" in tools_by_name["search"].description
    assert "先调用 search" in tools_by_name["open_url"].description
    assert {"image_generation_v1", "deep_research_v1", "weight_loss_v1"}.isdisjoint(
        set(tools_by_name)
    )
    event_types = [event.type for event in result.events]
    assert event_types[0] == "run.started"
    assert "model.started" in event_types
    assert "model.completed" in event_types
    assert "workflow.started" not in event_types
    context_event = next(event for event in result.events if event.type == "context.built")
    assert context_event.payload["final_model_request"]["workflow"] == "generic_tool_loop"
    assert event_types[-1] == "run.completed"


@pytest.mark.asyncio
async def test_disabled_tools_are_filtered_per_request(engine):
    mock_response = LLMResponse(
        content="No calculator needed.",
        tool_calls=[],
        model="test-model",
        usage={"input": 8, "output": 4},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=mock_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-disabled-tools",
                message="Hello",
                disabled_tools=["calculator"],
            )
        )

    tools = provider.chat.await_args.kwargs["tools"]
    tool_names = {tool.name for tool in tools}
    assert "calculator" not in tool_names
    assert "datetime" in tool_names
    context_event = next(event for event in result.events if event.type == "context.built")
    assert "calculator" not in context_event.payload["tool_names"]


@pytest.mark.asyncio
async def test_drive_tools_are_super_chat_only_and_get_user_context(engine):
    drive_calls = []

    class FakeDriveListSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="ls_drive",
                description="Fake drive list",
                parameters=[
                    SkillParameter(name="path", type="string", description="Drive path", required=False)
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            drive_calls.append(kwargs)
            return SkillResult(
                success=True,
                data={"items": [{"id": "file-1", "name": "Notes.md"}]},
                display_text="Notes.md",
            )

    engine.skill_registry.register(FakeDriveListSkill())
    tool_response = LLMResponse(
        content="",
        tool_calls=[ToolCall(id="call_ls_drive", name="ls_drive", arguments={"path": "/"})],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="网盘根目录有 Notes.md。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-drive-tools",
                user_id="alice",
                message="列一下我的网盘根目录",
                agent_id="super_chat",
            )
        )

    assert result.response == "网盘根目录有 Notes.md。"
    assert result.skills_used == ["ls_drive"]
    assert drive_calls == [{"path": "/", "_user_id": "alice"}]
    first_tools = provider.chat.await_args_list[0].kwargs["tools"]
    ls_drive_tool = next(tool for tool in first_tools if tool.name == "ls_drive")
    assert "_user_id" not in ls_drive_tool.parameters["properties"]
    tool_started = next(event for event in result.events if event.type == "tool.started")
    assert tool_started.payload["engine_context"] == {"user_id": "alice"}


@pytest.mark.asyncio
async def test_drive_tools_are_hidden_from_general_assistant(engine):
    class FakeDriveListSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="ls_drive",
                description="Fake drive list",
                parameters=[
                    SkillParameter(name="path", type="string", description="Drive path", required=False)
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            return SkillResult(success=True, data={})

    engine.skill_registry.register(FakeDriveListSkill())
    mock_response = LLMResponse(
        content="Hello.",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=mock_response)
        mock_provider.return_value = provider

        await engine.process(ChatRequest(conversation_id="conv-general-no-drive", message="Hello"))

    tools = provider.chat.await_args.kwargs["tools"]
    assert "ls_drive" not in {tool.name for tool in tools}


@pytest.mark.asyncio
async def test_pulse_tools_are_super_chat_only_and_get_user_context(engine):
    pulse_calls = []

    class FakePulseSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="get_pulse",
                description="Read Pulse recommendations.",
                parameters=[
                    SkillParameter(name="date", type="string", description="Date", required=False)
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            pulse_calls.append(kwargs)
            return SkillResult(
                success=True,
                data={"items": [{"id": "pulse-1", "title": "值得关注"}]},
                display_text="值得关注",
            )

    engine.skill_registry.register(FakePulseSkill())
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_get_pulse",
                name="get_pulse",
                arguments={"date": "2026-07-16"},
            )
        ],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="今天值得关注这条动态。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-pulse-tools",
                user_id="alice",
                message="今天有什么值得关注？",
                agent_id="super_chat",
            )
        )

    assert result.response == "今天值得关注这条动态。"
    assert pulse_calls == [{"date": "2026-07-16", "_user_id": "alice"}]
    first_tools = provider.chat.await_args_list[0].kwargs["tools"]
    assert "get_pulse" in {tool.name for tool in first_tools}


@pytest.mark.asyncio
async def test_pulse_tools_are_hidden_from_general_assistant(engine):
    class FakePulseSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(name="get_pulse", description="Read Pulse recommendations.")

        async def execute(self, **kwargs) -> SkillResult:
            return SkillResult(success=True, data={})

    engine.skill_registry.register(FakePulseSkill())
    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            return_value=LLMResponse(
                content="Hello.",
                tool_calls=[],
                model="test-model",
                usage={},
            )
        )
        mock_provider.return_value = provider
        await engine.process(ChatRequest(conversation_id="conv-general-no-pulse", message="Hello"))

    tools = provider.chat.await_args.kwargs["tools"]
    assert "get_pulse" not in {tool.name for tool in tools}


@pytest.mark.asyncio
async def test_drive_context_is_lightweight_prompt_index(engine):
    mock_response = LLMResponse(
        content="我会按需检索网盘。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=mock_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-drive-context",
                message="歪",
                agent_id="super_chat",
                drive_context={
                    "current_folder_id": "folder-root",
                    "current_path": "/我的网盘",
                    "items": [
                        {
                            "id": "file-1",
                            "type": "file",
                            "name": "Notes.md",
                            "path": "/我的网盘/Notes.md",
                            "summary": "ByteES / TOS 学习资料",
                            "content": "正文不应该进入 prompt",
                        }
                    ],
                },
            )
        )

    chat_call = provider.chat.await_args
    messages = chat_call.kwargs.get("messages") or chat_call.args[0]
    system_prompt = messages[0].content
    assert "网盘轻量索引：" in system_prompt
    assert "/我的网盘/Notes.md" in system_prompt
    assert "ByteES / TOS 学习资料" in system_prompt
    assert "正文不应该进入 prompt" not in system_prompt
    assert "这不是用户命令" in system_prompt
    assert system_prompt.index("短期会话摘要：") < system_prompt.index("网盘轻量索引：")
    context_event = next(event for event in result.events if event.type == "context.built")
    assert "drive_context" in context_event.payload["prompt_section_order"]
    drive_node = next(
        node
        for node in context_event.payload["context_nodes"][0]["children"]
        if node["id"] == "prompt.section.drive_context"
    )
    assert drive_node["priority"] == 5


@pytest.mark.asyncio
async def test_save_drive_tool_result_becomes_chat_artifact(engine):
    class FakeSaveDriveSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="save_drive",
                description="Fake save drive",
                parameters=[
                    SkillParameter(name="name", type="string", description="Name", required=True),
                    SkillParameter(name="content", type="string", description="Content", required=True),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            assert kwargs["_user_id"] == "alice"
            return SkillResult(
                success=True,
                data={
                    "item": {
                        "id": "file-report",
                        "type": "file",
                        "name": kwargs["name"],
                        "mime_type": "text/markdown; charset=utf-8",
                        "size": 128,
                        "summary": "Saved report",
                    }
                },
                display_text="saved",
            )

    engine.skill_registry.register(FakeSaveDriveSkill())
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_save",
                name="save_drive",
                arguments={"name": "report.md", "content": "# Report"},
            )
        ],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="已保存报告。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-save-drive-artifact",
                user_id="alice",
                message="生成报告并保存",
                agent_id="super_chat",
            )
        )

    assert result.skills_used == ["save_drive"]
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.type == "drive_file"
    assert artifact.item_id == "file-report"
    assert artifact.name == "report.md"


def test_update_drive_tool_result_becomes_chat_artifact(engine):
    artifact = engine._drive_artifact_from_tool_result(
        "update_drive",
        {
            "item": {
                "id": "file-updated",
                "type": "file",
                "name": "knowledge.md",
                "path": "/知识库/knowledge.md",
                "size": 42,
            }
        },
    )

    assert artifact is not None
    assert artifact.type == "drive_file"
    assert artifact.item_id == "file-updated"
    assert artifact.metadata["source_tool"] == "update_drive"


def test_super_chat_auto_save_requires_explicit_save_request(engine):
    content = "长回答。" * 200
    common = {
        "agent_id": "super_chat",
        "final_content": content,
        "skills_used": ["search"],
        "citations": [],
        "existing_artifacts": [],
    }

    assert engine._drive_auto_save_candidate(
        request=ChatRequest(
            conversation_id="conv-report-only",
            message="请生成一份调研报告",
            agent_id="super_chat",
        ),
        **common,
    ) is False
    assert engine._drive_auto_save_candidate(
        request=ChatRequest(
            conversation_id="conv-save",
            message="请生成一份调研报告并保存到网盘",
            agent_id="super_chat",
        ),
        **common,
    ) is True
    assert engine._drive_auto_save_candidate(
        request=ChatRequest(
            conversation_id="conv-no-save",
            message="请生成一份调研报告，但不要保存",
            agent_id="super_chat",
        ),
        **common,
    ) is False


@pytest.mark.asyncio
async def test_model_error_after_read_drive_retries_then_returns_final_answer(engine):
    class FakeReadDriveSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="read_drive",
                description="Fake read drive",
                parameters=[
                    SkillParameter(name="item_id", type="string", description="Item ID"),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            return SkillResult(
                success=True,
                data={
                    "item": {
                        "id": kwargs.get("item_id"),
                        "type": "file",
                        "name": "notes.md",
                        "path": "/knowledge/notes.md",
                        "mime_type": "text/markdown",
                    },
                    "content": "# Notes\n\nReadable drive content.",
                    "truncated": False,
                },
                display_text="notes.md\n\n# Notes\n\nReadable drive content.",
            )

    engine.skill_registry.register(FakeReadDriveSkill())
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_read_drive",
                name="read_drive",
                arguments={"item_id": "file-1"},
            )
        ],
        model="test-model",
        usage={"input": 10, "output": 2},
    )
    final_response = LLMResponse(
        content="已经读完：Readable drive content.",
        tool_calls=[],
        model="test-model",
        usage={"input": 20, "output": 5},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.model = "test-model"
        provider.chat = AsyncMock(side_effect=[tool_response, RuntimeError("Connection error."), final_response])
        mock_provider.return_value = provider

        with patch("agent.orchestrator.engine.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            result = await engine.process(
                ChatRequest(
                    conversation_id="conv-read-drive-retry",
                    user_id="alice",
                    agent_id="super_chat",
                    message="把那个 md 文件完整内容读出来看看？",
                )
            )

    assert provider.chat.await_count == 3
    sleep_mock.assert_awaited_once_with(0.5)
    assert result.error_type is None
    assert result.skills_used == ["read_drive"]
    assert result.response == "已经读完：Readable drive content."

    run = engine.trace_store.get_run(result.run_id)
    assert run is not None
    assert run.status == "completed"
    event_types = [event.type for event in result.events]
    assert event_types.count("model.retrying") == 1
    assert event_types[-1] == "run.completed"


@pytest.mark.asyncio
async def test_model_error_after_read_drive_returns_tool_result_fallback_after_retries(engine):
    class FakeReadDriveSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="read_drive",
                description="Fake read drive",
                parameters=[
                    SkillParameter(name="item_id", type="string", description="Item ID"),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            return SkillResult(
                success=True,
                data={
                    "item": {
                        "id": kwargs.get("item_id"),
                        "type": "file",
                        "name": "notes.md",
                        "path": "/knowledge/notes.md",
                        "mime_type": "text/markdown",
                    },
                    "content": "# Notes\n\nReadable drive content.",
                    "truncated": False,
                },
                display_text="notes.md\n\n# Notes\n\nReadable drive content.",
            )

    engine.skill_registry.register(FakeReadDriveSkill())
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_read_drive",
                name="read_drive",
                arguments={"item_id": "file-1"},
            )
        ],
        model="test-model",
        usage={"input": 10, "output": 2},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.model = "test-model"
        provider.chat = AsyncMock(
            side_effect=[
                tool_response,
                RuntimeError("Connection error."),
                RuntimeError("Connection error."),
                RuntimeError("Connection error."),
            ]
        )
        mock_provider.return_value = provider

        with patch("agent.orchestrator.engine.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            result = await engine.process(
                ChatRequest(
                    conversation_id="conv-read-drive-fallback",
                    user_id="alice",
                    agent_id="super_chat",
                    message="把那个 md 文件完整内容读出来看看？",
                )
            )

    assert provider.chat.await_count == 4
    assert [call.args[0] for call in sleep_mock.await_args_list] == [0.5, 1.5]
    assert result.error_type is None
    assert result.skills_used == ["read_drive"]
    assert "模型在整理最终回复时连接失败" in result.response
    assert "/knowledge/notes.md" in result.response
    assert "Readable drive content." in result.response

    run = engine.trace_store.get_run(result.run_id)
    assert run is not None
    assert run.status == "partial"
    assert run.error_type == "model_error_after_tool_results"
    event_types = [event.type for event in result.events]
    assert "tool.completed" in event_types
    assert event_types.count("model.retrying") == 2
    assert "model.failed" in event_types
    assert event_types[-1] == "run.partial"


@pytest.mark.asyncio
async def test_model_error_does_not_fallback_to_historical_tool_result(engine):
    request = ChatRequest(
        conversation_id="conv-read-drive-history-fallback",
        user_id="alice",
        agent_id="super_chat",
        message="继续按刚才的文件写。",
    )
    engine.memory.add_many(
        engine._conversation_memory_id(request),
        [
            LLMMessage(
                role="assistant",
                content="",
                tool_calls=[
                    {
                        "id": "call_previous_read_drive",
                        "name": "read_drive",
                        "arguments": {"item_id": "file-previous"},
                    }
                ],
            ),
            LLMMessage(
                role="tool",
                content=json.dumps(
                    {
                        "success": True,
                        "data": {
                            "item": {
                                "id": "file-previous",
                                "type": "file",
                                "name": "previous.md",
                                "path": "/knowledge/previous.md",
                                "mime_type": "text/markdown",
                            },
                            "content": "# Previous\n\nHistorical drive content.",
                            "truncated": False,
                        },
                        "display_text": "# Previous\n\nHistorical drive content.",
                        "error": None,
                    },
                    ensure_ascii=False,
                ),
                tool_call_id="call_previous_read_drive",
            ),
        ],
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.model = "test-model"
        provider.chat = AsyncMock(
            side_effect=[
                RuntimeError("Connection error."),
                RuntimeError("Connection error."),
                RuntimeError("Connection error."),
            ]
        )
        mock_provider.return_value = provider

        with patch("agent.orchestrator.engine.asyncio.sleep", new_callable=AsyncMock) as sleep_mock:
            with pytest.raises(RuntimeError, match="Connection error"):
                await engine.process(request)

    assert provider.chat.await_count == 3
    assert [call.args[0] for call in sleep_mock.await_args_list] == [0.5, 1.5]

    runs = engine.trace_store.list_runs(
        conversation_id=request.conversation_id,
        user_id=request.user_id,
    )
    assert len(runs) == 1
    run = runs[0]
    assert run.status == "failed"
    assert run.error_type == "model_error"
    assert run.error_message == "Connection error."
    assert "Historical drive content." not in run.output
    event_types = [event.type for event in run.events]
    assert "run.partial" not in event_types
    assert "workflow.failed" in event_types
    assert event_types[-1] == "run.failed"


@pytest.mark.asyncio
async def test_tool_call_calculator(engine):
    """LLM calls calculator tool, then returns final answer."""
    # First LLM call: wants to use calculator
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_1", name="calculator", arguments={"expression": "42 * 17 + 3"})
        ],
        model="test-model",
        usage={"input": 20, "output": 10},
    )
    # Second LLM call: final answer after seeing tool result
    final_response = LLMResponse(
        content="The result of 42 * 17 + 3 is 717.",
        tool_calls=[],
        model="test-model",
        usage={"input": 30, "output": 15},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        request = ChatRequest(
            conversation_id="test-conv",
            message="What is 42 * 17 + 3?",
        )
        result = await engine.process(request)

    assert result.response == "The result of 42 * 17 + 3 is 717."
    assert "calculator" in result.skills_used
    assert len(result.plan) == 1
    assert result.plan[0].skill == "calculator"
    assert result.plan[0].status == "completed"
    event_types = [event.type for event in result.events]
    assert "tool.started" in event_types
    assert "tool.completed" in event_types


@pytest.mark.asyncio
async def test_tool_governance_blocks_unconfirmed_high_risk_call(engine):
    class ConfirmedDeleteSkill(Skill):
        def __init__(self):
            self.calls = 0

        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="confirmed_delete",
                description="Delete a test item.",
                parameters=[
                    SkillParameter(name="item_id", type="string", description="Item ID.")
                ],
                risk_level="high",
                access="destructive",
                default_policy="confirm",
                confirmation_keywords=["删除测试项"],
            )

        async def execute(self, **kwargs) -> SkillResult:
            self.calls += 1
            return SkillResult(success=True, data={"deleted": kwargs.get("item_id")})

    skill = ConfirmedDeleteSkill()
    engine.skill_registry.register(skill)
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_delete",
                name="confirmed_delete",
                arguments={"item_id": "item-1"},
            )
        ],
        model="test-model",
        usage={"input": 10, "output": 5},
    )
    final_response = LLMResponse(
        content="没有执行删除，因为缺少明确确认。",
        tool_calls=[],
        model="test-model",
        usage={"input": 10, "output": 5},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider
        result = await engine.process(
            ChatRequest(
                conversation_id="governance-confirm",
                message="查看测试项 item-1",
            )
        )

    assert skill.calls == 0
    assert result.plan[0].status == "error"
    assert any(event.type == "tool.governance.blocked" for event in result.events)


@pytest.mark.asyncio
async def test_search_tool_trace_nodes_are_appended(engine):
    class FakeSearchSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="Search test sources.",
                parameters=[
                    SkillParameter(
                        name="query",
                        type="string",
                        description="Search query.",
                        required=True,
                    )
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            query = str(kwargs.get("query") or "")
            return SkillResult(
                success=True,
                data={
                    "query": query,
                    "query_rewrite": {
                        "node": "query_rewrite",
                        "strategy": "keyword_recall",
                        "original_query": query,
                        "queries": [query],
                    },
                    "search_trace": [
                        {
                            "node": "query_rewrite",
                            "status": "completed",
                            "strategy": "keyword_recall",
                            "original_query": query,
                            "queries": [query],
                            "query_count": 1,
                        },
                        {
                            "node": "recall",
                            "status": "partial",
                            "mode": "concurrent",
                            "providers": ["web", "bing-rss"],
                            "attempt_count": 2,
                            "timed_out_count": 1,
                            "error_count": 0,
                            "result_count": 1,
                            "attempts": [
                                {
                                    "provider": "web",
                                    "query": query,
                                    "status": "timed_out",
                                    "result_count": 0,
                                    "duration_ms": 30000,
                                }
                            ],
                        },
                        {
                            "node": "ranking",
                            "status": "completed",
                            "input_count": 1,
                            "ranked_count": 1,
                            "output_count": 1,
                            "duration_ms": 2,
                            "top_results": [
                                {
                                    "rank": 1,
                                    "title": "Search Trace Result",
                                    "url": "https://example.com/search-trace",
                                }
                            ],
                        },
                        {
                            "node": "llm_rerank",
                            "status": "completed",
                            "provider": "fake-llm",
                            "input_count": 1,
                            "output_count": 1,
                            "threshold": 0.35,
                            "top_results": [
                                {
                                    "rank": 1,
                                    "title": "Search Trace Result",
                                    "url": "https://example.com/search-trace",
                                }
                            ],
                        },
                    ],
                    "results": [
                        {
                            "title": "Search Trace Result",
                            "url": "https://example.com/search-trace",
                            "snippet": "Traceable search result.",
                            "source": "test-search",
                        }
                    ],
                },
                display_text="1. Search Trace Result",
            )

    engine.skill_registry.register(FakeSearchSkill())
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_search",
                name="search",
                arguments={"query": "trace search"},
            )
        ],
        model="test-model",
        usage={"input": 20, "output": 10},
    )
    final_response = LLMResponse(
        content="Search done.",
        tool_calls=[],
        model="test-model",
        usage={"input": 30, "output": 15},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(conversation_id="conv-search-trace", message="Search trace")
        )

    event_types = [event.type for event in result.events]
    assert "search.query_rewrite.completed" in event_types
    assert "search.recall.partial" in event_types
    assert "search.ranking.completed" in event_types
    assert "search.llm_rerank.completed" in event_types
    assert event_types.index("search.ranking.completed") < event_types.index("tool.completed")
    recall_event = next(event for event in result.events if event.type == "search.recall.partial")
    assert recall_event.step_id == "call_search"
    assert recall_event.payload["timed_out_count"] == 1
    assert recall_event.payload["attempts"][0]["provider"] == "web"


@pytest.mark.asyncio
async def test_tool_call_echo(engine):
    """LLM calls echo tool."""
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_1", name="echo", arguments={"text": "test message"})
        ],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="Echo: test message",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        request = ChatRequest(conversation_id="conv1", message="Echo test")
        result = await engine.process(request)

    assert "echo" in result.skills_used


@pytest.mark.asyncio
async def test_agent_loop_mode_uses_main_function_call_workflow(engine):
    """Agent Loop mode should use the main model/tool loop with explicit workflow trace."""
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_echo", name="echo", arguments={"text": "agent loop"})
        ],
        model="loop-router",
        usage={"input": 12, "output": 4},
    )
    final_response = LLMResponse(
        content="Agent loop final answer.",
        tool_calls=[],
        model="loop-router",
        usage={"input": 20, "output": 8},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-agent-loop",
                message="用 agent loop 跑一下 echo",
                agent_id="super_chat",
                mode_ids=["agent_loop"],
                mode_prompts=["【Agent Loop】本轮使用主循环 + function calling。"],
            )
        )

    assert result.response == "Agent loop final answer."
    assert result.skills_used == ["echo"]
    context_event = next(event for event in result.events if event.type == "context.built")
    assert context_event.payload["mode_ids"] == ["agent_loop"]
    assert context_event.payload["final_model_request"]["workflow"] == "agent_loop"
    assert context_event.payload["final_model_request"]["workflow_source"] == "selected_mode"
    assert context_event.payload["final_model_request"]["legacy_workflow"] == "generic_tool_loop"
    assert context_event.payload["final_model_request"]["workflow_nodes"] == ["main_loop"]
    event_types = [event.type for event in result.events]
    assert "thinking.plan.created" not in event_types
    assert "workflow.started" in event_types
    assert "workflow.node.started" in event_types
    assert "workflow.node.completed" in event_types
    assert "workflow.completed" in event_types
    workflow_started = next(event for event in result.events if event.type == "workflow.started")
    assert workflow_started.payload["workflow_source"] == "selected_mode"
    assert workflow_started.payload["legacy_workflow"] == "generic_tool_loop"
    model_started = next(event for event in result.events if event.type == "model.started")
    assert model_started.payload["workflow"] == "agent_loop"
    assert model_started.payload["workflow_node"] == "main_loop"
    tool_started = next(event for event in result.events if event.type == "tool.started")
    assert tool_started.payload["workflow"] == "agent_loop"
    assert tool_started.payload["workflow_node"] == "main_loop"


@pytest.mark.asyncio
async def test_search_tool_results_are_returned_as_citations(engine):
    """Search result URLs should be exposed as structured citations."""

    class FakeSearchSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="Fake search",
                parameters=[
                    SkillParameter(name="query", type="string", description="Query")
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            return SkillResult(
                success=True,
                data={
                    "query": kwargs.get("query"),
                    "results": [
                        {
                            "title": "SpaceX files S-1",
                            "url": "https://example.com/spacex-s1",
                            "snippet": "Example filing details",
                            "source": "test-search",
                            "metadata": {"rank": 1},
                        }
                    ],
                    "sources": ["test-search"],
                },
                display_text="1. SpaceX files S-1 - https://example.com/spacex-s1",
            )

    engine.skill_registry.register(FakeSearchSkill())
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_1", name="search", arguments={"query": "SpaceX IPO"})
        ],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="SpaceX has relevant search-backed updates.",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(conversation_id="conv-citations", message="SpaceX latest")
        )

    assert "search" in result.skills_used
    assert len(result.citations) == 1
    assert result.citations[0].title == "SpaceX files S-1"
    assert result.citations[0].url == "https://example.com/spacex-s1"
    assert result.citations[0].source == "test-search"
    assert result.citations[0].metadata == {"rank": 1}


@pytest.mark.asyncio
async def test_super_chat_auto_searches_when_model_skips_retrieval(engine):
    """Super Chat should insert search when a direct answer skips an explicit lookup."""
    search_calls = []

    class FakeSearchSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="Fake search",
                parameters=[
                    SkillParameter(name="query", type="string", description="Query")
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            search_calls.append(kwargs)
            return SkillResult(
                success=True,
                data={
                    "query": kwargs.get("query"),
                    "results": [
                        {
                            "title": "SpaceX files S-1",
                            "url": "https://example.com/spacex-s1",
                            "snippet": "Example filing details",
                            "source": "test-search",
                        }
                    ],
                    "sources": ["test-search"],
                },
                display_text="1. SpaceX files S-1 - https://example.com/spacex-s1",
            )

    engine.skill_registry.register(FakeSearchSkill())
    direct_response = LLMResponse(
        content="SpaceX looks likely to go public soon.",
        tool_calls=[],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="基于搜索结果，SpaceX 的上市进展需要以公开文件为准。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[direct_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-auto-search",
                agent_id="super_chat",
                message="查一下 SpaceX 最新上市进展",
            )
        )

    assert provider.chat.await_count == 2
    assert search_calls
    assert search_calls[0]["limit"] == 10
    assert search_calls[0]["sources"] == "web"
    assert "SpaceX 最新上市进展" in search_calls[0]["query"]
    assert "search" in result.skills_used
    assert len(result.citations) == 1
    event_types = [event.type for event in result.events]
    assert "agent_loop.search_forced" in event_types
    forced_event = next(event for event in result.events if event.type == "agent_loop.search_forced")
    assert "SpaceX looks likely" in forced_event.payload["direct_answer_preview"]
    second_call_messages = provider.chat.await_args_list[1].args[0]
    assert any(
        message.role == "tool" and "SpaceX files S-1" in message.content
        for message in second_call_messages
    )


@pytest.mark.asyncio
async def test_super_chat_does_not_force_search_after_model_used_a_tool(engine):
    """A no-tool final answer should not trigger forced search after any tool already ran."""
    search_calls = []

    class FakeSearchSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="Fake search",
                parameters=[
                    SkillParameter(name="query", type="string", description="Query")
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            search_calls.append(kwargs)
            return SkillResult(
                success=True,
                data={
                    "query": kwargs.get("query"),
                    "results": [
                        {
                            "title": "SpaceX IPO update",
                            "url": "https://example.com/spacex-ipo",
                            "snippet": "Example update",
                            "source": "test-search",
                        }
                    ],
                    "sources": ["test-search"],
                },
                display_text="1. SpaceX IPO update - https://example.com/spacex-ipo",
            )

    engine.skill_registry.register(FakeSearchSkill())
    search_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_search",
                name="search",
                arguments={"query": "SpaceX 最新上市进展", "limit": 5},
            )
        ],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="基于搜索结果，SpaceX 暂无确定上市时间。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[search_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-model-search",
                agent_id="super_chat",
                message="查一下 SpaceX 最新上市进展",
            )
        )

    assert provider.chat.await_count == 2
    assert len(search_calls) == 1
    assert search_calls[0]["query"] == "SpaceX 最新上市进展"
    assert result.skills_used == ["search"]
    event_types = [event.type for event in result.events]
    assert "agent_loop.search_forced" not in event_types


def test_super_chat_forced_search_only_handles_explicit_retrieval(engine):
    assert engine._super_chat_auto_search_required(
        ChatRequest(
            conversation_id="conv-review-report",
            agent_id="super_chat",
            message="帮我看看我最新的研究报告有没有什么问题",
        )
    ) is False
    assert engine._super_chat_auto_search_required(
        ChatRequest(
            conversation_id="conv-lookup",
            agent_id="super_chat",
            message="查一下 SpaceX 最新上市进展",
        )
    ) is True


@pytest.mark.asyncio
async def test_super_chat_drive_file_task_filters_search_tool(engine):
    response = LLMResponse(
        content="我会继续复制这几份网盘文件。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-drive-file-task-no-web",
                agent_id="super_chat",
                message="可以，A",
                context_blocks=[
                    "上一轮方案 A：复制三份旧文件到新文件夹。"
                    "需要 read_drive 读取旧文件，再用 save_drive 保存到 /我的网盘/AI行业最新进展 文件夹。"
                ],
            )
        )

    tools = provider.chat.await_args.kwargs["tools"]
    tool_names = {tool.name for tool in tools}
    assert "search" not in tool_names
    event_types = [event.type for event in result.events]
    assert "tools.filtered" in event_types
    filtered = next(event for event in result.events if event.type == "tools.filtered")
    assert filtered.payload["reason"] == "drive_task_without_explicit_retrieval"


@pytest.mark.asyncio
async def test_super_chat_latest_info_keeps_search_available_for_model_choice(engine):
    response = LLMResponse(
        content="我先按当前理解给一个概览。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-latest-info",
                agent_id="super_chat",
                message="我想了解一下具身智能行业最新的进展",
            )
        )

    tools = provider.chat.await_args.kwargs["tools"]
    assert "search" in {tool.name for tool in tools}
    event_types = [event.type for event in result.events]
    assert "tools.filtered" not in event_types
    assert "agent_loop.search_forced" not in event_types


@pytest.mark.asyncio
async def test_max_model_rounds_runs_final_summary_without_tools(engine, monkeypatch):
    """When the loop hits its model-round budget, it should ask for a no-tool final summary."""
    monkeypatch.setattr("agent.orchestrator.engine.MAX_MODEL_ROUNDS", 2)
    monkeypatch.setattr("agent.orchestrator.engine.MAX_TOOL_ROUNDS", 2)

    first_tool_response = LLMResponse(
        content="",
        tool_calls=[ToolCall(id="call_1", name="echo", arguments={"text": "first"})],
        model="test-model",
        usage={"input": 1, "output": 1},
    )
    second_tool_response = LLMResponse(
        content="还想继续查",
        tool_calls=[ToolCall(id="call_2", name="echo", arguments={"text": "second"})],
        model="test-model",
        usage={"input": 2, "output": 1},
    )
    final_summary = LLMResponse(
        content="阶段性总结：已经完成两次工具调用，后续需要人工继续核验。",
        tool_calls=[],
        model="test-model",
        usage={"input": 3, "output": 2},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[first_tool_response, second_tool_response, final_summary]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(conversation_id="conv-max-round-summary", message="一直调用工具")
        )

    assert provider.chat.await_count == 3
    final_call = provider.chat.await_args_list[-1]
    assert final_call.kwargs["tools"] is None
    assert "禁止再调用任何工具" in final_call.args[0][-1].content
    assert result.response == "阶段性总结：已经完成两次工具调用，后续需要人工继续核验。"
    assert "I've reached the maximum number of tool calls" not in result.response

    run = engine.trace_store.get_run(result.run_id)
    assert run is not None
    assert run.status == "partial"
    assert run.error_type == "max_tool_rounds_reached"
    event_types = [event.type for event in result.events]
    assert "agent_loop.budget_exhausted" in event_types
    assert event_types[-1] == "run.partial"
    budget_event = next(event for event in result.events if event.type == "agent_loop.budget_exhausted")
    assert budget_event.payload["reason"] == "max_model_rounds_reached"


@pytest.mark.asyncio
async def test_unknown_tool_call(engine):
    """LLM calls a tool that doesn't exist."""
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_1", name="nonexistent_tool", arguments={})
        ],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="Sorry, I couldn't find that tool.",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        request = ChatRequest(conversation_id="conv1", message="Do something")
        result = await engine.process(request)

    assert result.plan[0].status == "error"
    assert "nonexistent_tool" not in result.skills_used


@pytest.mark.asyncio
async def test_multiple_tool_calls(engine):
    """LLM calls multiple tools in one round."""
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_1", name="calculator", arguments={"expression": "1+1"}),
            ToolCall(id="call_2", name="echo", arguments={"text": "hello"}),
        ],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="1+1=2 and echo: hello",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        request = ChatRequest(conversation_id="conv1", message="Test")
        result = await engine.process(request)

    assert len(result.plan) == 2
    assert set(result.skills_used) == {"calculator", "echo"}


@pytest.mark.asyncio
async def test_read_only_tool_calls_run_in_parallel_and_preserve_message_order(engine):
    active = 0
    max_active = 0
    completed: list[str] = []

    class FakeReadOnlySkill(Skill):
        def __init__(self, name: str, delay: float):
            self.name = name
            self.delay = delay

        def metadata(self) -> SkillMetadata:
            parameter_name = "url" if self.name == "open_url" else "query"
            return SkillMetadata(
                name=self.name,
                description=f"Fake {self.name}",
                parameters=[
                    SkillParameter(
                        name=parameter_name,
                        type="string",
                        description=parameter_name,
                        required=True,
                    )
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            try:
                await asyncio.sleep(self.delay)
                completed.append(self.name)
                if self.name == "search":
                    return SkillResult(
                        success=True,
                        data={
                            "query": kwargs.get("query"),
                            "results": [
                                {
                                    "title": "Search result",
                                    "url": "https://example.com/search",
                                    "snippet": "Search snippet.",
                                    "source": "fake-search",
                                }
                            ],
                        },
                        display_text="search result",
                    )
                return SkillResult(
                    success=True,
                    data={
                        "page": {
                            "url": kwargs.get("url"),
                            "final_url": kwargs.get("url"),
                            "title": "Opened page",
                            "description": "Opened description.",
                            "content": "Opened content.",
                            "content_type": "text/html",
                            "status_code": 200,
                        }
                    },
                    display_text="opened page",
                )
            finally:
                active -= 1

    engine.skill_registry.register(FakeReadOnlySkill("search", 0.05))
    engine.skill_registry.register(FakeReadOnlySkill("open_url", 0.01))
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_search", name="search", arguments={"query": "parallel search"}),
            ToolCall(id="call_open", name="open_url", arguments={"url": "https://example.com/page"}),
        ],
        model="test-model",
        usage={},
    )
    final_response = LLMResponse(
        content="Parallel tools done.",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(conversation_id="conv-parallel-read-only-tools", message="查两个资料")
        )

    assert max_active == 2
    assert completed == ["open_url", "search"]
    assert result.skills_used == ["search", "open_url"]
    assert [item.skill for item in result.plan] == ["search", "open_url"]

    final_messages = provider.chat.await_args_list[1].args[0]
    tool_messages = [message for message in final_messages if message.role == "tool"]
    assert [message.tool_call_id for message in tool_messages] == ["call_search", "call_open"]


@pytest.mark.asyncio
async def test_super_chat_agent_tool_returns_json_and_continues(engine):
    """Agent tools should return JSON into the Super Chat loop like ordinary tools."""
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_echo", name="echo", arguments={"text": "should not run"}),
            ToolCall(
                id="call_image_generation",
                name="image_generation_v1",
                arguments={
                    "task": "生成一张 AI Agent 商业化趋势海报",
                    "reason": "用户需要生成图片",
                },
            ),
        ],
        model="router-model",
        usage={},
    )
    review_response = LLMResponse(
        content='{"should_generate": true, "final_prompt": "AI Agent commercialization poster", "aspect_ratio": "16:9"}',
        tool_calls=[],
        model="review-model",
        usage={},
    )
    final_response = LLMResponse(
        content="echo: should not run\n\n已生成图片：\n![AI 生图 1](https://example.com/agent-tool.png)",
        tool_calls=[],
        model="final-model",
        usage={"input": 30, "output": 8},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_agent_tool", "data": {"image_urls": ["https://example.com/agent-tool.png"]}}
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[tool_response, review_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-delegate-agent-tool",
                message="生成一张 AI Agent 商业化趋势海报，同时 echo 一下",
                agent_id="super_chat",
            )
        )

    assert result.agent_id == "super_chat"
    assert result.skills_used == ["echo", "image_generation_v1", "prompt_refine", "image_generation"]
    assert "echo: should not run" in result.response
    assert "![AI 生图 1](https://example.com/agent-tool.png)" in result.response
    image_client.generate_image.assert_awaited_once()
    tool_events = [event for event in result.events if event.type == "tool.started"]
    assert [event.payload["name"] for event in tool_events] == ["echo", "image_generation_v1"]
    delegation = next(event for event in result.events if event.type == "agent.tool.delegated")
    assert delegation.payload["protocol_version"] == "agent_tool.v1"
    assert delegation.payload["target_agent_id"] == "image_generation_v1"
    assert delegation.payload["child_run_id"]
    final_messages = provider.chat.await_args_list[-1].args[0]
    payload = agent_tool_payload(final_messages, "image_generation_v1")
    assert payload["success"] is True
    assert "![AI 生图 1](https://example.com/agent-tool.png)" in payload["data"]["response"]
    assert payload["data"]["child_run_id"] == delegation.payload["child_run_id"]


@pytest.mark.asyncio
async def test_conversation_memory(engine):
    """Memory should persist across calls for the same conversation."""
    response = LLMResponse(
        content="I remember!",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        # First message
        await engine.process(ChatRequest(conversation_id="conv1", message="Hello"))
        # Second message
        await engine.process(ChatRequest(conversation_id="conv1", message="Remember?"))

    # Second call should include history:
    # system + user1 + assistant1 (from memory) + user2 (new) = 4
    second_call_messages = provider.chat.call_args_list[1][0][0]
    assert len(second_call_messages) == 4


@pytest.mark.asyncio
async def test_separate_conversations(engine):
    """Different conversations should have separate memory."""
    response = LLMResponse(
        content="Response",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        await engine.process(ChatRequest(conversation_id="conv1", message="Hello 1"))
        await engine.process(ChatRequest(conversation_id="conv2", message="Hello 2"))

    # conv2 should only have system + its own user message
    second_call_messages = provider.chat.call_args_list[1][0][0]
    assert len(second_call_messages) == 2  # system + user


@pytest.mark.asyncio
async def test_memory_is_scoped_by_user_id(engine):
    engine.role_memory.add_memory(
        role_id="default",
        user_id="alice",
        kind="long_term",
        content="Alice likes terse memory answers",
    )
    engine.role_memory.add_memory(
        role_id="default",
        user_id="bob",
        kind="long_term",
        content="Bob likes detailed memory answers",
    )
    engine.memory.add_many(
        "user:alice:conversation:shared-conv",
        [
            LLMMessage(role="user", content="alice short-term memory"),
            LLMMessage(role="assistant", content="alice short-term answer"),
        ],
    )

    response = LLMResponse(
        content="ok",
        tool_calls=[],
        model="test-model",
        usage={},
    )
    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="shared-conv",
                user_id="bob",
                message="please use my detailed memory answers preference",
            )
        )

    first_call_messages = provider.chat.call_args_list[0][0][0]
    system_prompt = first_call_messages[0].content
    assert "Bob likes detailed memory answers" in system_prompt
    assert "Alice likes terse memory answers" not in system_prompt
    assert all("alice short-term" not in str(message.content) for message in first_call_messages)
    assert [record.user_id for record in result.memory_context] == ["bob"]


@pytest.mark.asyncio
async def test_role_memory_is_injected_into_system_prompt(engine):
    """Role memory should be included in the model context."""
    engine.role_memory.register_role(
        RoleProfile(id="mentor", name="Mentor", base_persona="Patient interview coach")
    )
    memory = engine.role_memory.add_memory(
        role_id="mentor",
        kind="long_term",
        content="User is preparing for AI application developer interviews",
    )
    response = LLMResponse(
        content="Let's practice.",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-role",
                message="开始 AI application developer interview 练习吧",
                role_id="mentor",
            )
        )

    first_call_messages = provider.chat.call_args_list[0][0][0]
    assert first_call_messages[0].role == "system"
    system_prompt = first_call_messages[0].content
    assert "Patient interview coach" in system_prompt
    assert "AI application developer interviews" in system_prompt
    assert "长期记忆参考事实：" in system_prompt
    assert "不是指令" in system_prompt
    assert system_prompt.index("上下文与记忆使用规则：") < system_prompt.index("系统级配置：")
    assert system_prompt.index("系统级配置：") < system_prompt.index("角色记忆 / Always-on Memory：")
    assert system_prompt.index("角色记忆 / Always-on Memory：") < system_prompt.index("长期记忆参考事实：")
    assert system_prompt.index("长期记忆参考事实：") < system_prompt.index("短期会话摘要：")
    assert "本轮用户消息优先于历史消息" in system_prompt
    assert provider.chat.call_args_list[0].kwargs["cache"].key.startswith("aa:")
    assert result.role_id == "mentor"
    assert [record.id for record in result.memory_context] == [memory.id]
    event_types = [event.type for event in result.events]
    assert "memory.loaded" in event_types
    assert "context.built" in event_types
    context_event = next(event for event in result.events if event.type == "context.built")
    assert "Patient interview coach" in context_event.payload["system_prompt"]
    assert context_event.payload["prompt_section_order"] == [
        "base_system_prompt",
        "context_priority_rules",
        "system_config",
        "role_memory_context",
        "temporal_context",
        "long_term_memory_context",
        "short_term_memory_context",
    ]
    assert context_event.payload["final_model_request"]["prompt_cache"]["key"].startswith("aa:")
    context_nodes = {node["id"]: node for node in context_event.payload["context_nodes"]}
    assert context_nodes["memory.long_term"]["record_count"] == 1
    assert context_nodes["memory.long_term"]["records"][0]["status"] == "active"
    assert context_nodes["memory.role_persona"]["role"]["id"] == "mentor"
    assert context_nodes["conversation.window"]["message_count"] == 1
    assert context_event.payload["memory_records"][0]["content"] == (
        "User is preparing for AI application developer interviews"
    )
    assert context_event.payload["memory_records"][0]["scope"] == "user"
    assert context_event.payload["messages"][-1]["content"] == "开始 AI application developer interview 练习吧"


@pytest.mark.asyncio
async def test_unrelated_long_term_memory_is_not_injected(engine):
    engine.role_memory.add_memory(
        role_id="default",
        kind="long_term",
        content="用户喜欢玩游戏，对游戏推荐感兴趣",
        tags=["游戏"],
    )
    response = LLMResponse(
        content="你好。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-unrelated-memory",
                message="歪",
                role_id="default",
            )
        )

    first_call_messages = provider.chat.call_args_list[0][0][0]
    assert "用户喜欢玩游戏" not in first_call_messages[0].content
    assert result.memory_context == []


@pytest.mark.asyncio
async def test_system_prompt_includes_temporal_context(engine):
    """Time-sensitive questions should give the model today's date."""
    response = LLMResponse(
        content="I will check current context.",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        await engine.process(
            ChatRequest(
                conversation_id="conv-time",
                message="What is latest SpaceX valuation?",
                role_id="default",
            )
        )

    first_call_messages = provider.chat.call_args_list[0][0][0]
    system_prompt = first_call_messages[0].content
    assert "时间上下文：" in system_prompt
    assert "当前日期/时间：" in system_prompt
    assert "当前年份：" in system_prompt
    assert "搜索工具" in system_prompt


@pytest.mark.asyncio
async def test_super_chat_agent_loop_mode_prompts_are_injected(engine):
    """Selected Super Chat modes should add hidden system instructions."""
    response = LLMResponse(
        content="Agent loop handled it.",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-mode",
                message="用 agent loop 跑一下",
                agent_id="super_chat",
                mode_ids=["agent_loop"],
                mode_prompts=[
                    "【Agent Loop】本轮使用主循环 + function calling。",
                ],
            )
        )

    context_event = next(event for event in result.events if event.type == "context.built")
    system_prompt = context_event.payload["system_prompt"]
    assert "Super Chat 模式指令：" in system_prompt
    assert "专业能力路由：" not in system_prompt
    assert "Agent-as-tool" not in system_prompt
    assert "search 是默认事实检索工具" in system_prompt
    assert "【Agent Loop】本轮使用主循环 + function calling。" in system_prompt
    assert system_prompt.index("角色记忆 / Always-on Memory：") < system_prompt.index("Super Chat 模式指令：")
    assert system_prompt.index("Super Chat 模式指令：") < system_prompt.index("长期记忆参考事实：")
    assert context_event.payload["messages"][-1]["content"] == "用 agent loop 跑一下"
    assert context_event.payload["mode_ids"] == ["agent_loop"]
    assert context_event.payload["mode_prompts"] == [
        "【Agent Loop】本轮使用主循环 + function calling。",
    ]
    assert context_event.payload["final_model_request"]["workflow"] == "agent_loop"
    assert context_event.payload["final_model_request"]["workflow_source"] == "selected_mode"
    assert context_event.payload["final_model_request"]["legacy_workflow"] == "generic_tool_loop"
    assert context_event.payload["final_model_request"]["workflow_nodes"] == ["main_loop"]
    assert context_event.payload["prompt_section_order"] == [
        "base_system_prompt",
        "context_priority_rules",
        "system_config",
        "role_memory_context",
        "mode_context",
        "temporal_context",
        "long_term_memory_context",
        "short_term_memory_context",
    ]
    assert all(node["id"] != "prompt.section.agent_context" for node in context_event.payload["context_nodes"])
    tool_names = {tool["name"] for tool in context_event.payload["final_model_request"]["tools"]}
    assert {"image_generation_v1", "weight_loss_v1"}.issubset(tool_names)
    event_types = [event.type for event in result.events]
    assert "workflow.started" in event_types
    assert "workflow.completed" in event_types
    workflow_started = next(event for event in result.events if event.type == "workflow.started")
    assert workflow_started.payload["workflow_source"] == "selected_mode"
    assert workflow_started.payload["legacy_workflow"] == "generic_tool_loop"
    assert not any(event_type.startswith("thinking.") for event_type in event_types)


@pytest.mark.asyncio
async def test_removed_thinking_mode_is_ignored_by_super_chat(engine):
    """Stale thinking mode selections should not enter a workflow or prompt context."""
    response = LLMResponse(
        content="普通 Super Chat 回答。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-removed-thinking",
                message="帮我调研这个方向",
                agent_id="super_chat",
                mode_ids=["thinking", "research", "plan"],
                mode_prompts=[
                    "【思考】先规划，再按需检索和分析。",
                    "使用思考模式：先规划，再按需检索和分析。",
                    "[Thinking] Plan first.",
                ],
            )
        )

    context_event = next(event for event in result.events if event.type == "context.built")
    system_prompt = context_event.payload["system_prompt"]
    assert "Super Chat 模式指令：" not in system_prompt
    assert "【思考】" not in system_prompt
    assert "使用思考模式" not in system_prompt
    assert context_event.payload["mode_ids"] == []
    assert context_event.payload["mode_prompts"] == []
    assert context_event.payload["final_model_request"]["workflow"] == "agent_loop"
    assert context_event.payload["final_model_request"]["workflow_source"] == "default_super_chat"
    assert context_event.payload["final_model_request"]["legacy_workflow"] == "generic_tool_loop"
    assert context_event.payload["final_model_request"]["workflow_nodes"] == ["main_loop"]
    event_types = [event.type for event in result.events]
    assert "workflow.started" in event_types
    assert "workflow.completed" in event_types
    workflow_started = next(event for event in result.events if event.type == "workflow.started")
    assert workflow_started.payload["workflow_source"] == "default_super_chat"
    assert workflow_started.payload["legacy_workflow"] == "generic_tool_loop"
    assert not any(event_type.startswith("thinking.") for event_type in event_types)


@pytest.mark.asyncio
async def test_deep_research_generates_plan_before_execution(engine):
    """Deep Research mode should produce a confirmable plan before searching."""
    response = LLMResponse(
        content="## 研究计划大纲\n\n1. 明确问题。\n2. 检索来源。\n\n确认后回复 /start。",
        tool_calls=[],
        model="research-planner",
        usage={"input": 10, "output": 20},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-plan",
                message="/plan AI Agent 商业化趋势",
                agent_id="super_chat",
                mode_ids=["deep_research"],
            )
        )

    assert "研究计划大纲" in result.response
    assert DEEP_RESEARCH_PLAN_MARKER not in result.response
    assert result.agent_id == "deep_research_v1"
    assert result.plan[0].skill == "research_plan"
    assert result.plan[0].status == "pending"
    event_types = [event.type for event in result.events]
    assert "research.plan.started" in event_types
    assert "research.plan.completed" in event_types
    assert "research.search.started" not in event_types


@pytest.mark.asyncio
async def test_deep_research_direct_agent_requires_super_chat_mode(engine):
    """Deep Research should not be directly callable as a normal agent."""
    with patch.object(engine, "_get_provider", side_effect=AssertionError("direct deep research should not call model")):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-direct-rejected",
                message="/plan AI Agent 商业化趋势",
                agent_id="deep_research_v1",
            )
        )

    assert result.error_type == "workflow_mode_required"
    assert result.agent_id == "deep_research_v1"
    assert "Super Chat" in result.response
    event_types = [event.type for event in result.events]
    assert "model.started" not in event_types
    assert "research.plan.started" not in event_types


@pytest.mark.asyncio
@pytest.mark.parametrize("message", ["/agent deep_research_v1 /start", "/研究 /start"])
async def test_super_chat_rejects_deep_research_agent_command(engine, message):
    """Legacy agent commands should not enter the Deep Research workflow."""
    with patch.object(engine, "_get_provider", side_effect=AssertionError("deep research command should not call model")):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-command-rejected",
                message=message,
                agent_id="super_chat",
            )
        )

    assert result.error_type == "workflow_mode_required"
    assert result.agent_id == "deep_research_v1"
    assert "勾选“深度研究”模式" in result.response
    event_types = [event.type for event in result.events]
    assert "agent.command.rejected" in event_types
    assert "model.started" not in event_types
    assert "research.plan.started" not in event_types
    rejected = next(event for event in result.events if event.type == "agent.command.rejected")
    assert rejected.payload["target_agent_id"] == "deep_research_v1"
    assert rejected.payload["required_mode_id"] == "deep_research"


@pytest.mark.asyncio
async def test_super_chat_deep_research_mode_routes_to_research_agent(engine):
    """The Super Chat Deep Research mode should route into the research agent."""
    response = LLMResponse(
        content="## 研究计划大纲\n\n确认后回复 /start。",
        tool_calls=[],
        model="research-planner",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-deep-research-mode",
                message="研究 AI Agent 商业化趋势",
                agent_id="super_chat",
                mode_ids=["deep_research"],
                mode_prompts=["【深度研究】先确认研究计划，再执行。"],
                drive_context={
                    "current_folder_id": "folder-root",
                    "current_path": "/knowledge",
                    "items": [
                        {
                            "id": "file-1",
                            "type": "file",
                            "name": "market.md",
                            "path": "/knowledge/market.md",
                            "summary": "AI Agent 市场资料",
                        }
                    ],
                },
            )
        )

    assert result.agent_id == "deep_research_v1"
    assert "研究计划大纲" in result.response
    plan_messages = provider.chat.await_args.args[0]
    assert "网盘轻量索引：" in plan_messages[-1].content
    assert "/knowledge/market.md" in plan_messages[-1].content
    event_types = [event.type for event in result.events]
    assert "agent.delegated" in event_types
    assert "research.plan.completed" in event_types
    assert "model.started" not in event_types
    context_event = next(event for event in result.events if event.type == "context.built")
    assert "drive_context" in context_event.payload["prompt_section_order"]
    drive_node = next(
        node
        for node in context_event.payload["context_nodes"][0]["children"]
        if node["id"] == "prompt.section.drive_context"
    )
    assert "/knowledge/market.md" in drive_node["content"]


@pytest.mark.asyncio
async def test_deep_research_executes_approved_plan_with_search(engine):
    """After confirmation, Deep Research should search, summarize, and report."""

    class FakeSearchSkill(Skill):
        def __init__(self):
            self.calls = []

        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="fake search",
                parameters=[
                    SkillParameter(name="query", type="string", description="query"),
                    SkillParameter(name="sources", type="string", description="sources", required=False),
                    SkillParameter(name="limit", type="integer", description="limit", required=False),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            self.calls.append(kwargs)
            index = len(self.calls)
            return SkillResult(
                success=True,
                data={
                    "query": kwargs["query"],
                    "results": [
                        {
                            "title": f"Source {index}",
                            "url": f"https://example.com/source-{index}",
                            "snippet": f"Evidence snippet {index}",
                            "source": "web",
                        }
                    ],
                },
                display_text=f"Source {index}",
            )

    fake_search = FakeSearchSkill()
    engine.skill_registry.register(fake_search)
    engine.memory.add_many(
        "user:0:conversation:conv-deep-exec",
        [
            LLMMessage(role="user", content="/plan AI Agent 商业化趋势"),
            LLMMessage(
                role="assistant",
                content=(
                    f"{DEEP_RESEARCH_PLAN_MARKER}\n"
                    "## 研究计划大纲\n\n覆盖市场、技术、案例和风险。"
                ),
            ),
        ],
    )

    query_response = LLMResponse(
        content=json.dumps({"queries": ["AI Agent commercialization trend"]}),
        tool_calls=[],
        model="query-model",
        usage={"input": 5, "output": 5},
    )
    summary_response = LLMResponse(
        content="分块摘要：来源显示商业化在增长 [1]。",
        tool_calls=[],
        model="summary-model",
        usage={"input": 6, "output": 6},
    )
    report_response = LLMResponse(
        content="# 研究报告\n\nAI Agent 商业化趋势正在形成 [1]。",
        tool_calls=[],
        model="report-model",
        usage={"input": 7, "output": 7},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[query_response, summary_response, deep_research_gap_response(), report_response]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-exec",
                message="/start",
                agent_id="super_chat",
                mode_ids=["deep_research"],
            )
        )

    assert result.response.startswith("# 研究报告")
    assert result.agent_id == "deep_research_v1"
    assert "[1](https://example.com/source-1)" in result.response
    assert "search" in result.skills_used
    assert len(fake_search.calls) == 20
    assert len(result.citations) == 20
    assert result.plan[-1].skill == "research_report"
    event_types = [event.type for event in result.events]
    assert "research.queries.created" in event_types
    assert "research.step_summary.completed" in event_types
    assert "research.gap_review.completed" in event_types
    assert "research.report.completed" in event_types


@pytest.mark.asyncio
async def test_deep_research_supplements_missing_data_before_report(engine):
    """Deep Research should loop through gap review, supplemental search, and new-source summary."""

    class FakeSearchSkill(Skill):
        def __init__(self):
            self.calls = []

        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="fake search",
                parameters=[
                    SkillParameter(name="query", type="string", description="query"),
                    SkillParameter(name="sources", type="string", description="sources", required=False),
                    SkillParameter(name="limit", type="integer", description="limit", required=False),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            self.calls.append(kwargs)
            index = len(self.calls)
            return SkillResult(
                success=True,
                data={
                    "query": kwargs["query"],
                    "results": [
                        {
                            "title": f"Source {index}",
                            "url": f"https://example.com/supplement-{index}",
                            "snippet": f"Evidence snippet {index}",
                            "source": "web",
                        }
                    ],
                },
                display_text=f"Source {index}",
            )

    fake_search = FakeSearchSkill()
    engine.skill_registry.register(fake_search)
    engine.memory.add_many(
        "user:0:conversation:conv-deep-supplement",
        [
            LLMMessage(role="user", content="/plan 日常饮茶选择"),
            LLMMessage(
                role="assistant",
                content=f"{DEEP_RESEARCH_PLAN_MARKER}\n## 研究计划大纲\n\n覆盖茶类、咖啡因和价格。",
            ),
        ],
    )

    query_response = LLMResponse(
        content=json.dumps({"queries": ["daily tea selection"]}),
        tool_calls=[],
        model="query-model",
        usage={"input": 5, "output": 5},
    )
    initial_summary_response = LLMResponse(
        content="初始摘要：茶类选择信息较多，但缺少咖啡因量化和价格来源。",
        tool_calls=[],
        model="summary-model",
        usage={"input": 6, "output": 6},
    )
    supplemental_summary_response = LLMResponse(
        content="补充摘要：新增来源补齐咖啡因和价格线索 [21][22]。",
        tool_calls=[],
        model="summary-model",
        usage={"input": 6, "output": 6},
    )
    report_response = LLMResponse(
        content="# 研究报告\n\n补搜后补齐了咖啡因和价格线索 [21][22]。",
        tool_calls=[],
        model="report-model",
        usage={"input": 7, "output": 7},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[
                query_response,
                initial_summary_response,
                deep_research_gap_response(
                    supplemental_queries=[
                        "tea caffeine mg per cup authoritative source",
                        "China tea price range 2026 daily drinking",
                    ],
                    status="needs_more",
                ),
                supplemental_summary_response,
                deep_research_gap_response(),
                report_response,
            ]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-supplement",
                message="/start",
                agent_id="super_chat",
                mode_ids=["deep_research"],
            )
        )

    assert len(fake_search.calls) == 22
    assert fake_search.calls[-2]["query"] == "tea caffeine mg per cup authoritative source"
    assert fake_search.calls[-1]["query"] == "China tea price range 2026 daily drinking"
    assert len(result.citations) == 22
    assert "[21](https://example.com/supplement-21)" in result.response
    assert "[22](https://example.com/supplement-22)" in result.response
    event_types = [event.type for event in result.events]
    assert event_types.count("research.gap_review.completed") == 2
    assert "research.supplemental_search.completed" in event_types
    execution_completed = next(event for event in result.events if event.type == "research.execution.completed")
    assert execution_completed.payload["query_count"] == 22
    assert execution_completed.payload["gap_review_count"] == 2


@pytest.mark.asyncio
async def test_deep_research_archives_report_to_drive_folder(engine):
    """Completed Deep Research reports should be saved under /研究报告."""

    class FakeSearchSkill(Skill):
        def __init__(self):
            self.calls = []

        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="fake search",
                parameters=[
                    SkillParameter(name="query", type="string", description="query"),
                    SkillParameter(name="sources", type="string", description="sources", required=False),
                    SkillParameter(name="limit", type="integer", description="limit", required=False),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            self.calls.append(kwargs)
            index = len(self.calls)
            return SkillResult(
                success=True,
                data={
                    "query": kwargs["query"],
                    "results": [
                        {
                            "title": f"Source {index}",
                            "url": f"https://example.com/archive-source-{index}",
                            "snippet": f"Evidence snippet {index}",
                            "source": "web",
                        }
                    ],
                },
                display_text=f"Source {index}",
            )

    captured: dict[str, dict] = {}

    class FakeMkdirDriveSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="mkdir_drive",
                description="fake mkdir",
                parameters=[SkillParameter(name="path", type="string", description="path", required=True)],
            )

        async def execute(self, **kwargs) -> SkillResult:
            captured["mkdir"] = kwargs
            return SkillResult(
                success=True,
                data={
                    "item": {
                        "id": "folder-reports",
                        "type": "folder",
                        "name": "研究报告",
                        "parent_id": "root",
                    }
                },
                display_text="Folder already exists: 研究报告.",
            )

    class FakeSaveDriveSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="save_drive",
                description="fake save",
                parameters=[
                    SkillParameter(name="name", type="string", description="name", required=True),
                    SkillParameter(name="folder_path", type="string", description="folder", required=True),
                    SkillParameter(name="content", type="string", description="content", required=True),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            captured["save"] = kwargs
            return SkillResult(
                success=True,
                data={
                    "item": {
                        "id": "file-research-report",
                        "type": "file",
                        "name": kwargs["name"],
                        "parent_id": "folder-reports",
                        "mime_type": "text/markdown; charset=utf-8",
                        "size": len(kwargs["content"]),
                        "summary": kwargs["summary"],
                        "path": f"/研究报告/{kwargs['name']}",
                    }
                },
                display_text="Saved report.",
            )

    fake_search = FakeSearchSkill()
    engine.skill_registry.register(fake_search)
    engine.skill_registry.register(FakeMkdirDriveSkill())
    engine.skill_registry.register(FakeSaveDriveSkill())
    engine.memory.add_many(
        "user:alice:conversation:conv-deep-archive",
        [
            LLMMessage(role="user", content="/plan AI Agent 商业化趋势"),
            LLMMessage(
                role="assistant",
                content=(
                    f"{DEEP_RESEARCH_PLAN_MARKER}\n"
                    "## 研究计划大纲\n\n覆盖市场、技术、案例和风险。"
                ),
            ),
        ],
    )

    report_text = "# 研究报告\n\nAI Agent 商业化趋势正在形成 [1]。"
    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[
                LLMResponse(
                    content=json.dumps({"queries": ["AI Agent commercialization trend"]}),
                    tool_calls=[],
                    model="query-model",
                    usage={"input": 5, "output": 5},
                ),
                LLMResponse(
                    content="分块摘要：来源显示商业化在增长 [1]。",
                    tool_calls=[],
                    model="summary-model",
                    usage={"input": 6, "output": 6},
                ),
                deep_research_gap_response(),
                LLMResponse(
                    content=report_text,
                    tool_calls=[],
                    model="report-model",
                    usage={"input": 7, "output": 7},
                ),
            ]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-archive",
                user_id="alice",
                message="/start",
                agent_id="super_chat",
                mode_ids=["deep_research"],
            )
        )

    expected_report = "# 研究报告\n\nAI Agent 商业化趋势正在形成 [1](https://example.com/archive-source-1)。"
    assert result.response == expected_report
    assert {"search", "mkdir_drive", "save_drive"}.issubset(set(result.skills_used))
    assert len(result.artifacts) == 1
    artifact = result.artifacts[0]
    assert artifact.type == "drive_file"
    assert artifact.item_id == "file-research-report"
    assert artifact.metadata["path"].startswith("/研究报告/")

    assert captured["mkdir"]["_user_id"] == "alice"
    assert captured["mkdir"]["path"] == "/研究报告"
    assert captured["save"]["_user_id"] == "alice"
    assert captured["save"]["folder_path"] == "/研究报告"
    assert captured["save"]["content"] == expected_report
    assert captured["save"]["mime_type"] == "text/markdown; charset=utf-8"
    assert captured["save"]["tags"] == "deep-research,研究报告"
    assert re.match(r"^\d{8}-\d{6} AI Agent 商业化趋势\.md$", captured["save"]["name"])

    event_types = [event.type for event in result.events]
    assert "research.report_archive.started" in event_types
    assert "research.report_archive.completed" in event_types
    archive_node = next(
        event
        for event in result.events
        if event.type == "workflow.node.completed" and event.payload.get("workflow_node") == "archive_report"
    )
    assert archive_node.status == "completed"
    assert archive_node.payload["folder_path"] == "/研究报告"
    execution_completed = next(event for event in result.events if event.type == "research.execution.completed")
    assert execution_completed.payload["archive_status"] == "completed"
    assert execution_completed.payload["artifact_count"] == 1
    assert result.plan[-1].skill == "save_drive"


@pytest.mark.asyncio
async def test_deep_research_continues_when_chunk_summary_is_rejected(engine):
    """A rejected source chunk summary should use fallback text and keep executing."""

    class FakeSearchSkill(Skill):
        def __init__(self):
            self.calls = []

        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="fake search",
                parameters=[
                    SkillParameter(name="query", type="string", description="query"),
                    SkillParameter(name="sources", type="string", description="sources", required=False),
                    SkillParameter(name="limit", type="integer", description="limit", required=False),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            self.calls.append(kwargs)
            call_index = len(self.calls)
            return SkillResult(
                success=True,
                data={
                    "query": kwargs["query"],
                    "results": [
                        {
                            "title": f"Source {call_index}-{item_index}",
                            "url": f"https://example.com/source-{call_index}-{item_index}",
                            "snippet": f"Evidence snippet {call_index}-{item_index}",
                            "source": "web",
                        }
                        for item_index in range(3)
                    ],
                },
                display_text=f"Sources {call_index}",
            )

    fake_search = FakeSearchSkill()
    engine.skill_registry.register(fake_search)
    engine.memory.add_many(
        "user:0:conversation:conv-deep-summary-rejected",
        [
            LLMMessage(role="user", content="/plan SpaceX 投资可行性"),
            LLMMessage(
                role="assistant",
                content=f"{DEEP_RESEARCH_PLAN_MARKER}\n## 研究计划大纲\n\n覆盖估值、收入、风险。",
            ),
        ],
    )

    query_response = LLMResponse(
        content=json.dumps({"queries": ["SpaceX valuation"]}),
        tool_calls=[],
        model="query-model",
        usage={"input": 5, "output": 5},
    )
    first_summary_response = LLMResponse(
        content="第一批摘要 [1]。",
        tool_calls=[],
        model="summary-model",
        usage={"input": 6, "output": 6},
    )
    report_response = LLMResponse(
        content="# 研究报告\n\n继续完成报告，包含降级分块。",
        tool_calls=[],
        model="report-model",
        usage={"input": 7, "output": 7},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[
                query_response,
                first_summary_response,
                RuntimeError("input new_sensitive (1026)"),
                deep_research_gap_response(),
                report_response,
            ]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-summary-rejected",
                message="/start",
                agent_id="super_chat",
                mode_ids=["deep_research"],
            )
        )

    assert result.response.startswith("# 研究报告")
    assert len(fake_search.calls) == 20
    assert len(result.citations) == 60
    event_types = [event.type for event in result.events]
    assert "research.step_summary.failed" in event_types
    assert "research.report.completed" in event_types
    assert event_types[-1] == "run.completed"


@pytest.mark.asyncio
async def test_deep_research_returns_fallback_when_report_generation_fails(engine):
    """A failed final report call should return a conservative fallback report."""

    class FakeSearchSkill(Skill):
        def __init__(self):
            self.calls = []

        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="fake search",
                parameters=[
                    SkillParameter(name="query", type="string", description="query"),
                    SkillParameter(name="sources", type="string", description="sources", required=False),
                    SkillParameter(name="limit", type="integer", description="limit", required=False),
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            self.calls.append(kwargs)
            index = len(self.calls)
            return SkillResult(
                success=True,
                data={
                    "query": kwargs["query"],
                    "results": [
                        {
                            "title": f"Source {index}",
                            "url": f"https://example.com/source-{index}",
                            "snippet": f"Evidence snippet {index}",
                            "source": "web",
                        }
                    ],
                },
                display_text=f"Source {index}",
            )

    fake_search = FakeSearchSkill()
    engine.skill_registry.register(fake_search)
    engine.memory.add_many(
        "user:0:conversation:conv-deep-report-failed",
        [
            LLMMessage(role="user", content="/plan AI Agent 商业化趋势"),
            LLMMessage(
                role="assistant",
                content=f"{DEEP_RESEARCH_PLAN_MARKER}\n## 研究计划大纲\n\n覆盖市场、技术、案例和风险。",
            ),
        ],
    )

    query_response = LLMResponse(
        content=json.dumps({"queries": ["AI Agent commercialization trend"]}),
        tool_calls=[],
        model="query-model",
        usage={"input": 5, "output": 5},
    )
    summary_response = LLMResponse(
        content="分块摘要：来源显示商业化在增长 [1]。",
        tool_calls=[],
        model="summary-model",
        usage={"input": 6, "output": 6},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[query_response, summary_response, deep_research_gap_response(), RuntimeError("report blocked")]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-report-failed",
                message="/start",
                agent_id="super_chat",
                mode_ids=["deep_research"],
            )
        )

    assert result.response.startswith("# 研究报告（降级生成）")
    assert "分块摘要：来源显示商业化在增长 [1](https://example.com/source-1)。" in result.response
    event_types = [event.type for event in result.events]
    assert "research.report.failed" in event_types
    assert event_types[-1] == "run.completed"


@pytest.mark.asyncio
async def test_context_blocks_are_injected_as_turn_context(engine):
    """Uploaded attachment text should enter the system context, not the user message."""
    response = LLMResponse(
        content="I used the attachment context.",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-context-blocks",
                message="请基于附件总结",
                agent_id="super_chat",
                context_blocks=[
                    "附件上下文\n### 1. notes.md\n内容：\nFirst line\nSecond line",
                ],
            )
        )

    first_call_messages = provider.chat.call_args_list[0][0][0]
    system_prompt = first_call_messages[0].content
    assert "用户本轮提供的上下文：" in system_prompt
    assert "### 1. notes.md" in system_prompt
    assert "First line\nSecond line" in system_prompt
    assert first_call_messages[-1].content == "请基于附件总结"
    context_event = next(event for event in result.events if event.type == "context.built")
    assert context_event.payload["context_block_count"] == 1
    assert context_event.payload["context_block_chars"] > 0


def test_aigc_prompt_mentions_persisted_history_when_memory_is_empty(engine):
    request = ChatRequest(
        conversation_id="conv-persisted-history",
        message="好，帮我生成一个图片吧，总结给我",
        agent_id="image_generation_v1",
        context_blocks=[
            "持久化会话历史（当前会话最近消息，按时间从旧到新）：\n"
            "用户：帮我看看minimax有什么进展\n"
            "助手：MiniMax 最近发布了图像和语音相关能力。"
        ],
    )
    role_context = MemoryContext(
        role=RoleProfile(id="default", name="默认助手"),
        rendered="当前角色上下文：\n- 角色 ID：default",
    )

    messages = engine._build_aigc_review_messages(
        request=request,
        role_context=role_context,
        history=[],
        professional=False,
    )

    user_message = messages[1].content
    assert "没有历史会话。" not in user_message
    assert "持久化会话历史已包含在下方本轮额外上下文中" in user_message
    assert "用户：帮我看看minimax有什么进展" in user_message


def test_agent_input_packet_filters_noise_and_renders_protocol(engine):
    engine.memory.add_many(
        "conv-aigc-handoff",
        [
            LLMMessage(role="user", content="上一版要科技蓝背景，主体是桌面台灯。"),
            LLMMessage(
                role="assistant",
                content="品牌主色是 cobalt blue，主体是 brass desk lamp，风格偏高级产品海报。",
            ),
            LLMMessage(
                role="assistant",
                content="**图片结果**\n![AI 生图 1](https://example.com/old.png)",
            ),
        ],
    )
    request = ChatRequest(
        conversation_id="conv-aigc-handoff",
        message="按上一版方向再出一张横版",
        agent_id="super_chat",
        context_blocks=[
            "持久化会话历史（当前会话最近消息，按时间从旧到新）：\n"
            "助手：I cannot generate images in this chat.\n"
            "用户：保留蓝色科技感和桌面台灯"
        ],
        attachments=[
            ChatAttachment(
                name="lamp-ref.png",
                type="image/png",
                size=128,
                kind="image",
                data_url="data:image/png;base64,ZmFrZQ==",
            )
        ],
    )
    history = engine.memory.get("conv-aigc-handoff")

    packet = engine._build_agent_handoff_packet(
        request=request,
        source_agent_id="super_chat",
        target_agent_id="image_generation_v1",
        history=history,
        context_brief="目标：生成一张高级感横版产品海报。",
        delegation_trace={"reason": "intent", "forced": False},
    )
    rendered = engine._render_agent_handoff_packet(packet)

    assert packet.protocol_version == "agent_input.v1"
    assert packet.source_agent_id == "super_chat"
    assert packet.target_agent_id == "image_generation_v1"
    assert packet.reason == "intent"
    assert packet.attachments[0].has_data_url is True
    assert "结构化 Agent 输入（agent_input.v1）" in rendered
    assert "品牌主色是 cobalt blue" in rendered
    assert "保留蓝色科技感" in rendered
    assert "I cannot generate images" not in rendered
    assert "**图片结果**" not in rendered
    assert packet.metadata["protocol_version"] == "agent_input.v1"


@pytest.mark.asyncio
async def test_image_generation_agent_refines_prompt_and_returns_image(engine):
    """AI 生图 should review the prompt, call MiniMax, and return renderable image Markdown."""
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, "final_prompt": "cinematic product photo of a brass desk lamp", '
            '"aspect_ratio": "1:1", "style_notes": "softbox lighting", '
            '"negative_prompt": "blurry, distorted", "review_notes": ["明确主体和光线"]}'
        ),
        tool_calls=[],
        model="review-model",
        usage={"input": 12, "output": 8},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={
            "id": "img_1",
            "data": {"image_urls": ["https://example.com/generated.png"]},
        }
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=review_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-aigc",
                message="生成一个复古台灯",
                agent_id="image_generation_v1",
                mode_ids=["image_prompt_refine"],
                attachments=[
                    ChatAttachment(
                        name="lamp-ref.png",
                        type="image/png",
                        size=128,
                        kind="image",
                        data_url="data:image/png;base64,ZmFrZQ==",
                    )
                ],
            )
        )

    assert result.agent_id == "image_generation_v1"
    assert result.skills_used == ["prompt_refine", "image_generation"]
    assert "专业修饰后的提示词" in result.response
    assert "cinematic product photo of a brass desk lamp" in result.response
    assert "![AI 生图 1](https://example.com/generated.png)" in result.response
    image_client.generate_image.assert_awaited_once()
    image_kwargs = image_client.generate_image.await_args.kwargs
    assert image_kwargs["aspect_ratio"] == "1:1"
    subject_reference = image_kwargs["extra"]["subject_reference"][0]
    assert subject_reference["type"] == "character"
    assert subject_reference["image_file"] == "data:image/png;base64,ZmFrZQ=="
    review_user_message = provider.chat.await_args.args[0][1].content
    assert "lamp-ref.png" in review_user_message
    event_types = [event.type for event in result.events]
    assert "aigc.prompt_review.completed" in event_types
    assert "aigc.image.completed" in event_types


@pytest.mark.asyncio
async def test_image_generation_text_only_omits_subject_reference(engine):
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, '
            '"final_prompt": "cute chibi political avatar, square icon, clean line art", '
            '"aspect_ratio": "1:1"}'
        ),
        tool_calls=[],
        model="review-model",
        usage={},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_text", "data": {"image_urls": ["https://example.com/avatar.png"]}}
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=review_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-aigc-text-only",
                message="帮我做一个q版的trump头像图片",
                agent_id="image_generation_v1",
            )
        )

    assert "![AI 生图 1](https://example.com/avatar.png)" in result.response
    image_client.generate_image.assert_awaited_once()
    image_kwargs = image_client.generate_image.await_args.kwargs
    assert "subject_reference" not in image_kwargs["extra"]


@pytest.mark.asyncio
async def test_image_generation_sensitive_error_returns_helpful_summary(engine):
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, '
            '"final_prompt": "cute chibi avatar of a famous political figure", '
            '"aspect_ratio": "1:1"}'
        ),
        tool_calls=[],
        model="review-model",
        usage={},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(side_effect=ValueError("input new_sensitive"))

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=review_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-aigc-sensitive-error",
                message="帮我做一个q版的trump头像图片",
                agent_id="image_generation_v1",
            )
        )

    assert result.error_type == ""
    assert "这次图片没有生成成功" in result.response
    assert "内容安全审核" in result.response
    assert "真实政治公众人物" in result.response
    assert "金发、深蓝西装、红色领带" in result.response
    failed_event = next(event for event in result.events if event.type == "aigc.image.failed")
    assert failed_event.payload["raw_error_message"] == "input new_sensitive"
    run_failed_event = next(event for event in result.events if event.type == "run.failed")
    assert run_failed_event.payload["error_type"] == "aigc_error"


@pytest.mark.asyncio
async def test_image_generation_financial_sensitive_error_is_contextual(engine):
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, '
            '"final_prompt": "MiniMax infographic with HK00100 stock tag, IPO timeline, '
            'valuation 461-504 billion HKD, investment disclaimer", '
            '"aspect_ratio": "9:16"}'
        ),
        tool_calls=[],
        model="review-model",
        usage={},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(side_effect=ValueError("input new_sensitive"))

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=review_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-aigc-financial-sensitive-error",
                message="帮我看看minimax有什么进展，并生成一个图片给我",
                agent_id="image_generation_v1",
            )
        )

    assert "金融/投资类可视化内容会更严格" in result.response
    assert "模型发布、产品矩阵、用户规模、技术能力" in result.response
    assert "真实政治公众人物" not in result.response
    failed_event = next(event for event in result.events if event.type == "aigc.image.failed")
    assert failed_event.payload["raw_error_message"] == "input new_sensitive"


@pytest.mark.asyncio
async def test_super_chat_auto_delegates_image_intent_to_image_agent(engine):
    """Super Chat should call AI 生图 through the image_generation_v1 agent tool."""
    delegate_response = agent_tool_response(
        "image_generation_v1",
        "帮我生成一张赛博朋克城市海报",
        "用户明确要求生成图片",
    )
    review_response = LLMResponse(
        content='{"should_generate": true, "final_prompt": "cyberpunk city poster", "aspect_ratio": "9:16"}',
        tool_calls=[],
        model="review-model",
        usage={},
    )
    final_response = LLMResponse(
        content="已生成赛博朋克城市海报：\n![AI 生图 1](https://example.com/poster.png)",
        tool_calls=[],
        model="final-model",
        usage={"input": 24, "output": 8},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_2", "data": {"image_urls": ["https://example.com/poster.png"]}}
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[delegate_response, review_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-aigc-auto",
                message="帮我生成一张赛博朋克城市海报",
                agent_id="super_chat",
            )
        )

    assert result.agent_id == "super_chat"
    assert result.skills_used == ["image_generation_v1", "prompt_refine", "image_generation"]
    assert "![AI 生图 1](https://example.com/poster.png)" in result.response
    image_client.generate_image.assert_awaited_once()
    event_types = [event.type for event in result.events]
    assert "tool.started" in event_types
    assert "tool.completed" in event_types
    assert "agent.tool.delegated" in event_types
    delegation = next(event for event in result.events if event.type == "agent.tool.delegated")
    assert delegation.payload["target_agent_id"] == "image_generation_v1"
    assert delegation.payload["reason"] == "用户明确要求生成图片"
    assert delegation.payload["protocol_version"] == "agent_tool.v1"
    final_messages = provider.chat.await_args_list[-1].args[0]
    payload = agent_tool_payload(final_messages, "image_generation_v1")
    assert payload["success"] is True
    assert "![AI 生图 1](https://example.com/poster.png)" in payload["data"]["response"]


@pytest.mark.asyncio
async def test_super_chat_delegates_chinese_comparison_chart_to_image_agent(engine):
    """Chinese visual deliverables such as 对比图 should delegate through the tool layer."""
    delegate_response = agent_tool_response(
        "image_generation_v1",
        "我想学习一下skill，mcp，tool，subagent等知识，帮我收集一下，然后整理一个对比图和一份学习资料给我吧",
        "用户需要整理对比图和学习资料，包含视觉产出",
    )
    planner_response = LLMResponse(
        content=(
            '{"information_strategy": "retrieve", "brief_format": "markdown", '
            '"steps": ["task_decomposition", "retrieval", "image_generation", "final_summary"], '
            '"reason": "The user asks to collect knowledge before making a comparison chart.", '
            '"brief_format_reason": "Markdown brief fits learning-material summary before generation."}'
        ),
        tool_calls=[],
        model="planner-model",
        usage={"input": 8, "output": 4},
    )
    research_response = LLMResponse(
        content=(
            "Research Brief: compare Skill, MCP, Tool, and Sub-Agent.\n"
            "Key Facts: Tool is an atomic callable capability; MCP standardizes tool/context access; "
            "Skill packages instructions and resources for a repeatable workflow; Sub-Agent is an "
            "independent agent loop for delegated tasks.\n"
            "Visual Brief: create a Chinese comparison infographic with one column per concept and "
            "a learning path section.\n"
            "Learning Materials: OpenAI function calling, MCP docs, agent workflow articles."
        ),
        tool_calls=[],
        model="research-model",
        usage={"input": 20, "output": 10},
    )
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, '
            '"final_prompt": "Chinese infographic comparison chart for Skill, MCP, Tool, and Sub-Agent", '
            '"aspect_ratio": "9:16", '
            '"review_notes": ["保留对比图和学习路径两个区域"]}'
        ),
        tool_calls=[],
        model="review-model",
        usage={"input": 10, "output": 5},
    )
    final_response = LLMResponse(
        content=(
            "已生成对比图，并整理好学习资料摘要。\n"
            "![AI 生图 1](https://example.com/compare.png)"
        ),
        tool_calls=[],
        model="final-model",
        usage={"input": 40, "output": 12},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_compare", "data": {"image_urls": ["https://example.com/compare.png"]}}
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[delegate_response, planner_response, research_response, review_response, final_response]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-comparison-chart",
                message="我想学习一下skill，mcp，tool，subagent等知识，帮我收集一下，然后整理一个对比图和一份学习资料给我吧",
                agent_id="super_chat",
                mode_ids=["plan", "research"],
                mode_prompts=[
                    "【计划模式】本轮必须让用户看见计划。",
                    "【研究】本轮必须先拆解研究问题，再收集/对比可靠信息。",
                ],
            )
        )

    assert result.agent_id == "super_chat"
    assert "image_generation_v1" in result.skills_used
    assert "image_generation" in result.skills_used
    assert "![AI 生图 1](https://example.com/compare.png)" in result.response
    image_client.generate_image.assert_awaited_once()
    event_types = [event.type for event in result.events]
    assert "agent.tool.delegated" in event_types
    assert "aigc.plan.created" not in event_types
    assert "aigc.research.completed" not in event_types
    delegation = next(event for event in result.events if event.type == "agent.tool.delegated")
    assert delegation.payload["reason"] == "用户需要整理对比图和学习资料，包含视觉产出"
    assert delegation.payload["protocol_version"] == "agent_tool.v1"
    payload = agent_tool_payload(provider.chat.await_args_list[-1].args[0], "image_generation_v1")
    assert "Learning Materials" in payload["data"]["response"]


@pytest.mark.asyncio
async def test_text_heavy_chinese_share_card_uses_text_rendering_guard(engine):
    """Dense Chinese share cards should render exact copy via local SVG instead of MiniMax text."""
    planner_response = LLMResponse(
        content=(
            '{"information_strategy": "retrieve", "brief_format": "markdown", '
            '"steps": ["task_decomposition", "retrieval", "image_generation", "final_summary"], '
            '"reason": "Need to prepare a visual brief before image generation.", '
            '"brief_format_reason": "Markdown is enough for a fresh research brief."}'
        ),
        tool_calls=[],
        model="planner-model",
        usage={"input": 6, "output": 3},
    )
    research_response = LLMResponse(
        content=(
            "关键事实：\n"
            "1. 巽寮湾 ⭐⭐⭐⭐⭐｜1.5h｜全高速+沿海大道｜全家、情侣\n"
            "2. 西湖市区 ⭐⭐⭐⭐｜1h｜高速+市区｜老人、不想开车\n"
            "3. 双月湾 ⭐⭐⭐⭐｜2h｜高速+县道｜喜欢小众\n"
            "4. 罗浮山 ⭐⭐⭐｜1.5h｜高速+山路｜登山爱好者\n"
            "5. 南昆山 ⭐⭐⭐｜2.5h｜高速+盘山路｜自驾老手\n"
            "视觉简报：做一张中文分享图，必须呈现评分、时长、道路类型、推荐人群，保留免责语。"
        ),
        tool_calls=[],
        model="research-model",
        usage={"input": 30, "output": 20},
    )
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, '
            '"final_prompt": "A Chinese infographic with exact labels for all five Huizhou driving options, '
            'star ratings, route types, travel times, audience labels, and a small disclaimer.", '
            '"aspect_ratio": "3:4", '
            '"review_notes": ["保留五个方案和评分"]}'
        ),
        tool_calls=[],
        model="review-model",
        usage={"input": 10, "output": 6},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_share", "data": {"image_urls": ["https://example.com/share.png"]}}
    )
    svg_result = ShareCardRenderResult(
        url="/static/generated/aigc/share.svg",
        path=Path("/tmp/share.svg"),
        title="深圳自驾惠州舒适度对比",
        conclusion="首推 巽寮湾",
        row_count=5,
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ), patch("agent.orchestrator.engine.render_share_card_svg", return_value=svg_result) as mock_svg:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[planner_response, research_response, review_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-text-heavy-share-card",
                message="帮我把这几个方案生成一个图片吧，方便分享",
                agent_id="image_generation_v1",
                mode_ids=["research"],
                mode_prompts=["【研究】先整理资料，再生成图片。"],
            )
        )

    review_messages = provider.chat.await_args_list[2].args[0]
    assert "文字密集型视觉策略" in review_messages[0].content

    mock_svg.assert_called_once()
    image_client.generate_image.assert_not_awaited()
    assert "![AI 生图 1](/static/generated/aigc/share.svg)" in result.response
    assert "结构化 SVG 渲染器" in result.response

    prompt_event = next(event for event in result.events if event.type == "aigc.prompt_review.completed")
    assert prompt_event.payload["text_heavy_visual"] is True
    assert "文字渲染保护" in prompt_event.payload["final_prompt_preview"]
    image_event = next(event for event in result.events if event.type == "aigc.image.started")
    assert image_event.payload["provider"] == "local_svg"
    assert image_event.payload["row_count"] == 5


@pytest.mark.asyncio
async def test_image_generation_reuses_existing_context_brief_without_research(engine):
    """Image-only follow-ups should reuse existing conversation facts instead of re-researching."""
    delegate_response = agent_tool_response(
        "image_generation_v1",
        "帮我给这些方案生成一个图片吧",
        "用户要求基于已有方案生成可分享图片",
    )
    structured_brief = (
        "目标：为已有惠州自驾舒适度对比生成分享卡骨架。\n"
        "必须包含：五个方案、舒适度排序、首推方案，以及精确文字使用覆盖层的注意事项。\n"
        "数据行：\n"
        "- 巽寮湾 | 1.5h | 全高速+沿海大道 | 容易 | 全家、情侣 | top recommendation\n"
        "- 西湖市区 | 1h | 高速+市区 | 较易 | 老人、不想开车\n"
        "- 双月湾 | 2h | 高速+县道 | 中等 | 喜欢小众\n"
        "- 罗浮山 | 1.5h | 高速+山路 | 较易 | 登山爱好者\n"
        "- 南昆山 | 2.5h | 高速+盘山路 | 较难 | 自驾老手\n"
        "版式：竖版 3:4，五张堆叠卡片，高亮第一张。\n"
        "视觉风格：干净旅行 App 质感，海蓝色和暖色点缀。\n"
        "注意事项：图片模型不要排版精确中文。"
    )
    planner_response = LLMResponse(
        content=(
            '{"information_strategy": "reuse_context", "brief_format": "structured", '
            '"selected_context_brief": '
            + repr(structured_brief).replace("'", '"')
            + ', "steps": ["task_decomposition", "context_reuse", "image_generation", "final_summary"], '
            '"reason": "The prior assistant answer already contains the needed comparison facts.", '
            '"brief_format_reason": "Structured rows are best for a multi-option comparison share card."}'
        ),
        tool_calls=[],
        model="planner-model",
        usage={"input": 20, "output": 10},
    )
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, '
            '"final_prompt": "A clean share-card skeleton for five Huizhou self-driving options", '
            '"aspect_ratio": "3:4", '
            '"review_notes": ["复用已有自驾舒适度对比"]}'
        ),
        tool_calls=[],
        model="review-model",
        usage={"input": 10, "output": 5},
    )
    final_response = LLMResponse(
        content=(
            "已复用已有上下文生成分享卡：\n"
            "![AI 生图 1](/static/generated/aigc/reuse.svg)\n\n"
            "核心结论：首推 巽寮湾。"
        ),
        tool_calls=[],
        model="final-model",
        usage={"input": 36, "output": 8},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_reuse", "data": {"image_urls": ["https://example.com/reuse.png"]}}
    )
    svg_result = ShareCardRenderResult(
        url="/static/generated/aigc/reuse.svg",
        path=Path("/tmp/reuse.svg"),
        title="深圳自驾惠州舒适度对比",
        conclusion="首推 巽寮湾",
        row_count=5,
    )

    context_block = (
        "持久化会话历史（当前会话最近消息，按时间从旧到新）：\n"
        "用户：如果自驾呢，哪个或者哪种方案更舒服，可以给我一个图片一目了然吗\n"
        "助手：# 深圳自驾惠州·方案舒适度深度对比\n\n"
        "## 一句话结论\n"
        "自驾最舒服 -> 巽寮湾\n\n"
        "## 五维舒适度对比表\n"
        "| 方案 | 单程时长 | 道路类型 | 停车难度 | 推荐人群 |\n"
        "|---|---|---|---|---|\n"
        "| 巽寮湾 | 1.5h | 全高速+沿海大道 | 容易 | 全家、情侣 |\n"
        "| 西湖市区 | 1h | 高速+市区 | 较易 | 老人、不想开车 |\n"
        "| 双月湾 | 2h | 高速+县道 | 中等 | 喜欢小众 |\n"
        "| 罗浮山 | 1.5h | 高速+山路 | 较易 | 登山爱好者 |\n"
        "| 南昆山 | 2.5h | 高速+盘山路 | 较难 | 自驾老手 |\n"
        "用户：帮我把这几个方案生成一个图片吧，方便分享\n"
        "助手：**图片结果**\n![AI 生图 1](https://example.com/old.png)\n"
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ), patch("agent.orchestrator.engine.render_share_card_svg", return_value=svg_result):
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[delegate_response, planner_response, review_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-context-reuse-image",
                message="帮我给这些方案生成一个图片吧",
                agent_id="super_chat",
                mode_ids=["plan", "research"],
                mode_prompts=[
                    "【计划模式】本轮必须让用户看见计划。",
                    "【研究】先拆解问题，再收集/对比可靠信息。",
                ],
                context_blocks=[context_block],
            )
        )

    assert provider.chat.await_count == 4
    assert result.skills_used[0] == "image_generation_v1"
    planning_messages = provider.chat.await_args_list[1].args[0]
    assert "比较信息交接格式" in planning_messages[0].content
    review_messages = provider.chat.await_args_list[2].args[0]
    review_user_message = review_messages[1].content
    assert "数据行：" in review_user_message
    assert "巽寮湾 | 1.5h" in review_user_message
    assert "本轮额外上下文" not in review_user_message

    event_types = [event.type for event in result.events]
    assert "agent.tool.delegated" in event_types
    assert "aigc.planning.completed" not in event_types
    assert "aigc.context_reuse.completed" not in event_types
    payload = agent_tool_payload(provider.chat.await_args_list[-1].args[0], "image_generation_v1")
    assert "![AI 生图 1](/static/generated/aigc/reuse.svg)" in payload["data"]["response"]
    child_plan = payload["data"]["plan"]
    assert any(step["skill"] == "context_reuse" for step in child_plan)
    assert [step["skill"] for step in child_plan] == [
        "task_decomposition",
        "context_reuse",
        "image_generation",
        "final_summary",
    ]
    image_client.generate_image.assert_not_awaited()
    assert "![AI 生图 1](/static/generated/aigc/reuse.svg)" in result.response
    assert "上下文复用简报" not in result.response
    assert "当前生图请求" not in result.response
    assert "核心结论：首推 巽寮湾" in result.response


def test_aigc_planning_invalid_json_marks_fallback_and_structures_context(engine):
    context_brief = (
        "Context Reuse Brief: reuse the already researched conversation facts below.\n\n"
        "Current image request:\n重新生成一下图片\n\n"
        "Reusable facts and layout source:\n"
        "# 深圳自驾惠州·方案舒适度深度对比\n"
        "自驾最舒服 -> 巽寮湾\n"
        "| 方案 | 单程时长 | 道路类型 | 停车难度 | 疲劳度 | 推荐人群 |\n"
        "|---|---|---|---|---|---|\n"
        "| 巽寮湾 | 1.5h | 全高速+沿海大道 | 容易 | 最低 | 全家、情侣 |\n"
        "| 南昆山 | 2.5h | 高速+盘山路 | 较难 | 最高 | 自驾老手 |\n"
    )
    request = ChatRequest(
        conversation_id="conv-planning-fallback",
        message="重新生成一下图片",
        agent_id="image_generation_v1",
        mode_ids=["plan", "research"],
    )
    fallback = engine._default_aigc_planning_decision(request, context_brief)

    decision = engine._parse_aigc_planning_response(
        "不是 JSON",
        fallback=fallback,
        context_brief=context_brief,
        model="planner-model",
        usage={"input": 1, "output": 1},
    )

    assert decision["fallback"] is True
    assert decision["information_strategy"] == "reuse_context"
    assert decision["brief_format"] == "structured"
    assert decision["selected_context_brief"].startswith("目标：")
    assert "数据行：" in decision["selected_context_brief"]
    assert "上下文复用简报" not in decision["selected_context_brief"]


@pytest.mark.asyncio
async def test_super_chat_image_mode_forces_delegation(engine):
    """The Super Chat AI 生图 mode should be expressed as an image_generation_v1 tool call."""
    delegate_response = agent_tool_response(
        "image_generation_v1",
        "按这个方向来一版",
        "用户选择 AI 生图模式，需要交给图像生成 Agent",
    )
    review_response = LLMResponse(
        content='{"should_generate": true, "final_prompt": "minimalist product concept render", "aspect_ratio": "1:1"}',
        tool_calls=[],
        model="review-model",
        usage={},
    )
    final_response = LLMResponse(
        content="已按这个方向生成概念图：\n![AI 生图 1](https://example.com/concept.png)",
        tool_calls=[],
        model="final-model",
        usage={"input": 22, "output": 8},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_3", "data": {"image_urls": ["https://example.com/concept.png"]}}
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[delegate_response, review_response, final_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-aigc-force",
                message="按这个方向来一版",
                agent_id="super_chat",
                mode_ids=["image_generation"],
                mode_prompts=["【AI 生图】本轮强制交给 AI 生图 Agent 处理。"],
            )
        )

    assert result.agent_id == "super_chat"
    assert "image_generation_v1" in result.skills_used
    assert "image_generation" in result.skills_used
    assert "![AI 生图 1](https://example.com/concept.png)" in result.response
    delegation = next(event for event in result.events if event.type == "agent.tool.delegated")
    assert delegation.payload["reason"] == "用户选择 AI 生图模式，需要交给图像生成 Agent"
    assert delegation.payload["protocol_version"] == "agent_tool.v1"
    payload = agent_tool_payload(provider.chat.await_args_list[-1].args[0], "image_generation_v1")
    assert payload["data"]["child_run_id"] == delegation.payload["child_run_id"]


@pytest.mark.asyncio
async def test_super_chat_research_image_intent_prepares_brief_before_generation(engine):
    """Research + image requests should collect a brief before prompt review and generation."""
    search_calls = []
    delegate_response = agent_tool_response(
        "image_generation_v1",
        "关于 SpaceX 是否值得投资，先收集一下信息，然后生成一个图给我",
        "用户需要先检索资料再生成投资主题图像",
        context="已有会话中曾回复无法生成图片，本轮需要进入图像生成 Agent。",
    )

    class FakeSearchSkill(Skill):
        def metadata(self) -> SkillMetadata:
            return SkillMetadata(
                name="search",
                description="Search test sources.",
                parameters=[
                    SkillParameter(
                        name="query",
                        type="string",
                        description="Search query.",
                        required=True,
                    )
                ],
            )

        async def execute(self, **kwargs) -> SkillResult:
            search_calls.append(kwargs)
            return SkillResult(
                success=True,
                data={
                    "query": kwargs.get("query"),
                    "results": [
                        {
                            "title": "SpaceX valuation and revenue estimates",
                            "url": "https://example.com/spacex-investment",
                            "snippet": "SpaceX remains private; valuation and revenue are estimates.",
                            "source": "test-search",
                            "metadata": {
                                "rank": 1,
                                "thumbnail_url": "https://example.com/spacex.jpg",
                            },
                        }
                    ],
                },
                display_text="1. SpaceX valuation and revenue estimates",
            )

    engine.skill_registry.register(FakeSearchSkill())
    planner_response = LLMResponse(
        content=(
            '{"information_strategy": "retrieve", "brief_format": "markdown", '
            '"steps": ["task_decomposition", "retrieval", "image_generation", "final_summary"], '
            '"reason": "Investment-related image needs fresh source-backed facts.", '
            '"brief_format_reason": "Markdown research brief is suitable for source notes and caveats."}'
        ),
        tool_calls=[],
        model="planner-model",
        usage={"input": 8, "output": 4},
    )
    research_tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(
                id="call_search",
                name="search",
                arguments={"query": "SpaceX private company valuation revenue risks"},
            )
        ],
        model="research-model",
        usage={"input": 10, "output": 2},
    )
    research_final_response = LLMResponse(
        content=(
            "Research Plan: check SpaceX ownership, valuation, revenue, and risks.\n"
            "Key Facts: SpaceX is private; investment access is limited to secondary markets. "
            "Use estimated valuation/revenue only with caveats.\n"
            "Visual Brief: show company snapshot, growth drivers, risks, and access caveat.\n"
            "Source Notes / Gaps: https://example.com/spacex-investment"
        ),
        tool_calls=[],
        model="research-model",
        usage={"input": 20, "output": 8},
    )
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, "final_prompt": "SpaceX investment infographic based on '
            'researched facts and caveats", "aspect_ratio": "3:4"}'
        ),
        tool_calls=[],
        model="review-model",
        usage={"input": 12, "output": 6},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_4", "data": {"image_urls": ["https://example.com/spacex.png"]}}
    )
    final_response = LLMResponse(
        content=(
            "**图片结果**\n"
            "![AI 生图 1](https://example.com/spacex.png)\n\n"
            "**简要总结**\nSpaceX is private; estimates need caveats."
        ),
        tool_calls=[],
        model="final-model",
        usage={"input": 60, "output": 16},
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[
                delegate_response,
                planner_response,
                research_tool_response,
                research_final_response,
                review_response,
                final_response,
            ]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-aigc-research",
                message="关于 SpaceX 是否值得投资，先收集一下信息，然后生成一个图给我",
                agent_id="super_chat",
                mode_ids=["research"],
                mode_prompts=["【研究】先拆解问题，再收集/对比可靠信息。"],
                context_blocks=[
                    "持久化会话历史：\n助手：I cannot generate images in this chat."
                ],
            )
        )

    assert result.agent_id == "super_chat"
    assert result.skills_used == ["image_generation_v1", "search", "prompt_refine", "image_generation"]
    assert result.citations and result.citations[0].url == "https://example.com/spacex-investment"
    assert result.citations[0].metadata["image_url"] == "https://example.com/spacex.jpg"
    assert search_calls and search_calls[0]["limit"] == 12
    assert result.plan
    assert result.plan[0].skill == "image_generation_v1"
    assert len(result.plan) == 1
    assert result.response.startswith("**图片结果**")
    assert "![AI 生图 1](https://example.com/spacex.png)" in result.response
    assert "**简要总结**" in result.response
    assert "**生图提示词**" not in result.response
    assert "SpaceX investment infographic based on researched facts and caveats" not in result.response
    image_client.generate_image.assert_awaited_once()

    final_messages = provider.chat.call_args_list[-1][0][0]
    payload = agent_tool_payload(final_messages, "image_generation_v1")
    child_plan = payload["data"]["plan"]
    assert [step["skill"] for step in child_plan] == [
        "task_decomposition",
        "retrieval",
        "image_generation",
        "final_summary",
    ]
    assert [step["status"] for step in child_plan] == ["completed", "completed", "completed", "completed"]
    assert "SpaceX is private" in child_plan[1]["result_summary"]
    assert payload["data"]["citations"][0]["url"] == "https://example.com/spacex-investment"

    review_user_message = provider.chat.call_args_list[4][0][0][1].content
    assert "结构化 Agent 输入（agent_input.v1）" in review_user_message
    assert "来源：super_chat -> image_generation_v1" in review_user_message
    assert "原因：用户需要先检索资料再生成投资主题图像" in review_user_message
    assert "生图简报：" in review_user_message
    assert "SpaceX is private" in review_user_message
    assert "近期会话：" not in review_user_message
    assert "本轮额外上下文：" not in review_user_message
    assert "I cannot generate images in this chat" not in review_user_message

    event_types = [event.type for event in result.events]
    assert "agent.input_context.built" not in event_types
    assert "agent.handoff_context.built" not in event_types
    assert event_types.index("agent.tool.delegated") < event_types.index("tool.completed")
    assert "tool.completed" in event_types
    assert "citations.collected" not in event_types
    context_events = [event for event in result.events if event.type == "context.built"]
    assert context_events[0].payload["context_block_count"] == 1


@pytest.mark.asyncio
async def test_image_generation_agent_can_ask_for_clarification(engine):
    """Prompt review may keep the flow conversational instead of generating immediately."""
    review_response = LLMResponse(
        content=(
            '{"should_generate": false, '
            '"clarifying_question": "你想生成什么主体和风格？", '
            '"final_prompt": "", "aspect_ratio": "1:1", "review_notes": []}'
        ),
        tool_calls=[],
        model="review-model",
        usage={"input": 4, "output": 3},
    )
    image_client = MagicMock()
    image_client.generate_image = AsyncMock()

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ) as image_factory:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=review_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-aigc-clarify",
                message="帮我生图",
                agent_id="image_generation_v1",
            )
        )

    assert result.response == "你想生成什么主体和风格？"
    assert result.skills_used == ["prompt_refine"]
    assert "image_generation" not in result.skills_used
    image_factory.assert_not_called()
    event_types = [event.type for event in result.events]
    assert "aigc.prompt_review.completed" in event_types
    assert "aigc.image.started" not in event_types


@pytest.mark.asyncio
async def test_streams_final_answer_after_tool_call(engine):
    """Streaming requests should emit final-answer tokens after tools resolve."""
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_1", name="echo", arguments={"text": "search result"})
        ],
        model="test-model",
        usage={"input": 10, "output": 2},
    )

    async def stream_answer(*args, **kwargs):
        yield "streamed "
        yield "answer"

    tokens = []

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.model = "stream-model"
        provider.chat = AsyncMock(return_value=tool_response)
        provider.chat_stream = stream_answer
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-stream-tools",
                message="Use a tool then answer",
                role_id="default",
                stream=True,
            ),
            on_token=tokens.append,
        )

    assert tokens == ["streamed ", "answer"]
    assert result.response == "streamed answer"
    assert result.model_used == "stream-model"
    assert "echo" in result.skills_used
    assert provider.chat.call_count == 1
    assert [event.type for event in result.events].count("model.started") == 2
    streaming_events = [
        event
        for event in result.events
        if event.type == "model.started" and event.payload.get("streaming")
    ]
    assert len(streaming_events) == 1


@pytest.mark.asyncio
async def test_provider_can_disable_streaming_after_tool_call(engine):
    """Providers with text-style tool markers should keep using chat after tools."""
    tool_response = LLMResponse(
        content="",
        tool_calls=[
            ToolCall(id="call_1", name="echo", arguments={"text": "search result"})
        ],
        model="test-model",
        usage={"input": 10, "output": 2},
    )
    final_response = LLMResponse(
        content="final answer",
        tool_calls=[],
        model="test-model",
        usage={"input": 20, "output": 4},
    )
    tokens = []

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.disable_stream_after_tools = True
        provider.chat = AsyncMock(side_effect=[tool_response, final_response])
        provider.chat_stream = AsyncMock()
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-no-stream-tools",
                message="Use a tool then answer",
                role_id="default",
                stream=True,
            ),
            on_token=tokens.append,
        )

    assert tokens == []
    assert result.response == "final answer"
    assert "echo" in result.skills_used
    assert provider.chat.call_count == 2
    provider.chat_stream.assert_not_called()


@pytest.mark.asyncio
async def test_memory_hook_writes_after_turn(engine):
    """Explicit memory requests should create role-scoped long-term memory."""
    response = LLMResponse(
        content="我会记住。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-memory-hook",
                message="请记住：我的名字是安安",
                role_id="default",
            )
        )
        await engine.wait_for_postprocessing()

    memories = engine.role_memory.list_memories(role_id="default", kind="long_term")
    assert result.memory_updates == []
    assert memories[0].content == "我的名字是安安"
    run = engine.trace_store.get_run(result.run_id)
    assert run is not None
    assert "memory.extracted" in [event.type for event in run.events]


@pytest.mark.asyncio
async def test_memory_postprocess_does_not_block_response(engine):
    """Long-term memory review should run after the answer is ready."""
    started = asyncio.Event()
    release = asyncio.Event()

    class SlowMemoryHook:
        async def review_turn(self, **kwargs):
            started.set()
            await release.wait()
            return [
                MemoryCandidate(
                    kind="long_term",
                    content="用户希望长期记忆检测后台执行",
                    confidence=0.9,
                    reason="explicit_test",
                    tags=["test"],
                )
            ]

    engine.memory_hook = SlowMemoryHook()
    response = LLMResponse(
        content="已经拆开。",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-memory-postprocess",
                message="请记住：长期记忆检测后台执行",
                role_id="default",
            )
        )

    assert result.response == "已经拆开。"
    assert result.memory_updates == []
    assert [event.type for event in result.events][-1] == "run.completed"
    assert engine.role_memory.list_memories(role_id="default", kind="long_term") == []

    await asyncio.wait_for(started.wait(), timeout=1)
    assert engine.role_memory.list_memories(role_id="default", kind="long_term") == []

    release.set()
    await engine.wait_for_postprocessing()
    memories = engine.role_memory.list_memories(role_id="default", kind="long_term")
    assert memories[0].content == "用户希望长期记忆检测后台执行"


@pytest.mark.asyncio
async def test_ai_memory_review_writes_long_term_memory(registry):
    engine = AgentEngine(registry, ai_memory_review_enabled=True)
    assistant_response = LLMResponse(
        content="我会记住。",
        tool_calls=[],
        model="chat-model",
        usage={},
    )
    review_response = LLMResponse(
        content=json.dumps(
            {
                "memories": [
                    {
                        "kind": "long_term",
                        "content": "用户正在重构 agent memory 系统",
                        "confidence": 0.86,
                        "reason": "持续项目状态",
                        "tags": ["project"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        tool_calls=[],
        model="review-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[assistant_response, review_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-ai-memory",
                message="我们现在在重构 agent memory 系统",
            )
        )
        await engine.wait_for_postprocessing()

    memories = engine.role_memory.list_memories(role_id="default", kind="long_term")
    assert result.memory_updates == []
    assert memories[0].content == "用户正在重构 agent memory 系统"
    assert memories[0].metadata["reviewer"] == "ai"
    run = engine.trace_store.get_run(result.run_id)
    assert run is not None
    event_types = [event.type for event in run.events]
    assert "memory.review.completed" in event_types


@pytest.mark.asyncio
async def test_ai_memory_review_failure_skips_memory_write(registry):
    engine = AgentEngine(registry, ai_memory_review_enabled=True)
    assistant_response = LLMResponse(
        content="我先回答当前问题。",
        tool_calls=[],
        model="chat-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[assistant_response, RuntimeError("review blocked")]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-ai-memory-failure",
                message="帮我计划一下澳洲旅行",
            )
        )
        await engine.wait_for_postprocessing()

    assert engine.role_memory.list_memories(role_id="default", kind="long_term") == []
    run = engine.trace_store.get_run(result.run_id)
    assert run is not None
    event_types = [event.type for event in run.events]
    assert "memory.review.failed" in event_types
    assert "memory.candidates.created" not in event_types
    assert "memory.extracted" not in event_types


@pytest.mark.asyncio
async def test_ai_memory_review_filters_one_off_request_memory(registry):
    engine = AgentEngine(registry, ai_memory_review_enabled=True)
    assistant_response = LLMResponse(
        content="我可以帮你做一份行程草案。",
        tool_calls=[],
        model="chat-model",
        usage={},
    )
    review_response = LLMResponse(
        content=json.dumps(
            {
                "memories": [
                    {
                        "kind": "long_term",
                        "content": "用户想了解如何计划澳洲旅行",
                        "confidence": 0.95,
                        "reason": "用户提出旅行规划需求",
                        "tags": ["travel"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        tool_calls=[],
        model="review-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[assistant_response, review_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-ai-memory-filter-low-signal",
                message="帮我计划一下澳洲旅行",
            )
        )
        await engine.wait_for_postprocessing()

    assert engine.role_memory.list_memories(role_id="default", kind="long_term") == []
    run = engine.trace_store.get_run(result.run_id)
    assert run is not None
    event_types = [event.type for event in run.events]
    assert "memory.candidates.created" in event_types
    assert "memory.candidates.filtered" in event_types
    assert "memory.extracted" in event_types
    extracted = next(event for event in run.events if event.type == "memory.extracted")
    assert extracted.payload["stored_count"] == 0


@pytest.mark.asyncio
async def test_ai_memory_review_updates_existing_memory(registry):
    engine = AgentEngine(registry, ai_memory_review_enabled=True)
    existing = engine.role_memory.add_memory(
        role_id="default",
        kind="long_term",
        content="用户正在重构 agent memory 系统",
        tags=["project"],
    )
    assistant_response = LLMResponse(
        content="我会更新这条记忆。",
        tool_calls=[],
        model="chat-model",
        usage={},
    )
    review_response = LLMResponse(
        content=json.dumps(
            {
                "memories": [
                    {
                        "action": "update",
                        "target_id": existing.id,
                        "kind": "long_term",
                        "content": "用户正在重构 agent memory 系统，并优化日期收纳和合并策略",
                        "confidence": 0.92,
                        "reason": "同一长期项目的新增进展",
                        "tags": ["project", "memory"],
                    }
                ]
            },
            ensure_ascii=False,
        ),
        tool_calls=[],
        model="review-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[assistant_response, review_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-ai-memory-update",
                message="memory 系统还要优化日期收纳和合并策略",
            )
        )
        await engine.wait_for_postprocessing()

    memories = engine.role_memory.list_memories(role_id="default", kind="long_term")
    assert len(memories) == 1
    assert result.memory_updates == []
    assert memories[0].id == existing.id
    assert memories[0].version == 2
    assert "日期收纳" in memories[0].content


def test_memory_retrieval_query_uses_context_for_continuation(engine):
    porcelain = engine.role_memory.add_memory(
        role_id="default",
        kind="long_term",
        content="用户对瓷器烧制失败率、直播开窑和汝瓷建盏工艺感兴趣",
        tags=["瓷器"],
    )
    engine.role_memory.add_memory(
        role_id="default",
        kind="long_term",
        content="用户喜欢玩游戏，对游戏推荐感兴趣",
        tags=["游戏"],
    )

    query = engine._memory_retrieval_query(
        ChatRequest(
            conversation_id="conv-memory-continuation",
            message="可以的，继续说吧",
            context_blocks=["制作瓷器的失败率很高吗？我看直播开窑的失败率似乎好高"],
        )
    )
    context = engine.role_memory.get_context(role_id="default", query=query)

    assert context is not None
    assert [record.id for record in context.long_term_memories] == [porcelain.id]


@pytest.mark.asyncio
async def test_conversation_memory_compacts_with_summary(registry):
    engine = AgentEngine(
        registry,
        conversation_compaction_threshold=2,
        conversation_compaction_keep_messages=2,
    )
    first_response = LLMResponse(content="第一轮", model="chat-model", usage={})
    second_response = LLMResponse(content="第二轮", model="chat-model", usage={})
    compact_response = LLMResponse(
        content=json.dumps(
            {
                "should_compact": True,
                "summary": "用户正在分层设计 memory 系统。",
                "keep_message_indices": [2, 3],
            },
            ensure_ascii=False,
        ),
        model="compact-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[first_response, second_response, compact_response]
        )
        mock_provider.return_value = provider

        await engine.process(ChatRequest(conversation_id="conv-compact", message="第一轮"))
        result = await engine.process(ChatRequest(conversation_id="conv-compact", message="第二轮"))
        await engine.wait_for_postprocessing()

    memory_id = "user:0:conversation:conv-compact"
    blocks = engine.memory.get_summary_blocks(memory_id)
    assert len(blocks) == 1
    assert blocks[0].content == "用户正在分层设计 memory 系统。"
    assert engine.memory.get_summary(memory_id) == (
        f"{blocks[0].date}:\n- 用户正在分层设计 memory 系统。"
    )
    assert [message.content for message in engine.memory.get(memory_id)] == ["第二轮", "第二轮"]
    run = engine.trace_store.get_run(result.run_id)
    assert run is not None
    assert "memory.compaction.completed" in [event.type for event in run.events]


@pytest.mark.asyncio
async def test_memory_disabled_hides_stored_memory(engine):
    engine.role_memory.add_memory(
        role_id="default",
        kind="long_term",
        content="User likes hidden durable memory",
    )
    engine.memory.add_many(
        "user:0:conversation:conv-memory-disabled",
        [
            LLMMessage(role="user", content="hidden short-term message"),
            LLMMessage(role="assistant", content="hidden short-term answer"),
        ],
    )
    response = LLMResponse(
        content="ok",
        tool_calls=[],
        model="test-model",
        usage={},
    )

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-memory-disabled",
                message="hello",
                memory_enabled=False,
            )
        )

    first_call_messages = provider.chat.call_args_list[0][0][0]
    assert "User likes hidden durable memory" not in first_call_messages[0].content
    assert all("hidden short-term" not in message.content for message in first_call_messages)
    assert result.memory_context == []


@pytest.mark.asyncio
async def test_unknown_role_returns_traced_error(engine):
    """Unknown roles should fail before a model call."""
    with patch.object(engine, "_get_provider") as mock_provider:
        result = await engine.process(
            ChatRequest(
                conversation_id="conv1",
                message="Hello",
                role_id="missing_role",
            )
        )

    mock_provider.assert_not_called()
    assert result.error_type == "unknown_role"
    assert result.role_id == "missing_role"
    assert [event.type for event in result.events] == ["run.started", "run.failed"]


@pytest.mark.asyncio
async def test_unknown_agent_returns_traced_error(engine):
    """Unknown agents should fail with a trace instead of calling a provider."""
    with patch.object(engine, "_get_provider") as mock_provider:
        result = await engine.process(
            ChatRequest(
                conversation_id="conv1",
                message="Hello",
                agent_id="missing_agent",
            )
        )

    mock_provider.assert_not_called()
    assert result.error_type == "unknown_agent"
    assert result.run_id
    event_types = [event.type for event in result.events]
    assert event_types == ["run.started", "run.failed"]


@pytest.mark.asyncio
async def test_weight_loss_agent_estimates_image_logs_and_summarizes_deficit(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss.db")
    engine = AgentEngine(registry, weight_loss_store=store)
    analysis_payload = {
        "intent": "mixed",
        "profile_updates": {
            "daily_calorie_goal": 1600,
            "maintenance_calories": 2200,
        },
        "meal": {
            "should_log": True,
            "meal_name": "鸡胸饭",
            "meal_type": "lunch",
            "items": [
                {
                    "name": "米饭",
                    "portion": "一小碗",
                    "calories": 220,
                    "carbs_g": 48,
                    "confidence": 0.7,
                },
                {
                    "name": "鸡胸肉",
                    "portion": "约120g",
                    "calories": 190,
                    "protein_g": 35,
                    "confidence": 0.75,
                },
                {
                    "name": "蔬菜和酱汁",
                    "portion": "一份",
                    "calories": 150,
                    "confidence": 0.55,
                },
            ],
            "total_calories": 560,
            "calorie_min": 480,
            "calorie_max": 650,
            "protein_g": 38,
            "carbs_g": 52,
            "fat_g": 14,
            "confidence": 0.68,
            "assumptions": ["按普通外卖饭盒份量估算", "酱汁另计少量油脂"],
            "notes": "图片估算。",
        },
        "exercise": {"should_log": False, "activity": "", "calories_burned": 0},
        "clarifying_question": "",
        "assistant_notes": ["建议称量主食会更准。"],
    }
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(analysis_payload, ensure_ascii=False),
            model="vision-test-model",
            usage={"input": 100, "output": 80},
        )
    )

    with patch.object(engine, "_get_provider", return_value=provider):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-weight-loss",
                agent_id="weight_loss_v1",
                message="我的每日目标1600大卡，维持热量2200大卡。帮我估算这餐热量并记录。",
                attachments=[
                    ChatAttachment(
                        name="meal.png",
                        type="image/png",
                        kind="image",
                        size=4,
                        content="food photo",
                        data_url="data:image/png;base64,ZmFrZQ==",
                    )
                ],
            )
        )

    summary = store.summary("conv-weight-loss", days=1)
    assert result.agent_id == "weight_loss_v1"
    assert result.model_used == "vision-test-model"
    assert "food_calorie_estimation" in result.skills_used
    assert "calorie_deficit_stats" in result.skills_used
    assert "560 kcal" in result.response
    assert "1640 kcal" in result.response
    assert "模型：" not in result.response
    assert "vision-test-model" not in result.response
    assert summary["profile"]["daily_calorie_goal"] == 1600
    assert summary["profile"]["maintenance_calories"] == 2200
    assert summary["totals"]["intake"] == 560
    assert summary["totals"]["deficit"] == 1640
    event_types = [event.type for event in result.events]
    assert "weight_loss.analysis.completed" in event_types
    assert "weight_loss.meal.logged" in event_types
    assert "weight_loss.summary.completed" in event_types


@pytest.mark.asyncio
async def test_weight_loss_image_analysis_retries_transient_provider_failures(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_retries.db")
    engine = AgentEngine(registry, weight_loss_store=store)
    analysis_payload = {
        "intent": "log_food",
        "profile_updates": {"daily_calorie_goal": 1600},
        "meal": {
            "should_log": True,
            "meal_name": "寿司拼盘",
            "meal_type": "lunch",
            "items": [{"name": "寿司", "portion": "一份", "calories": 465, "confidence": 0.7}],
            "total_calories": 465,
            "calorie_min": 400,
            "calorie_max": 550,
            "protein_g": 28,
            "carbs_g": 51,
            "fat_g": 15.5,
            "confidence": 0.7,
            "assumptions": ["按常规寿司拼盘估算"],
            "notes": "图片估算。",
        },
        "exercise": {"should_log": False, "activity": "", "calories_burned": 0},
        "clarifying_question": "",
        "assistant_notes": [],
    }
    provider = AsyncMock()
    provider.chat = AsyncMock(
        side_effect=[
            ConnectionError("connection dropped"),
            ConnectionError("connection dropped again"),
            LLMResponse(
                content=json.dumps(analysis_payload, ensure_ascii=False),
                model="vision-retry-model",
                usage={"input": 120, "output": 70},
            ),
        ]
    )

    with patch.object(engine, "_get_provider", return_value=provider), patch(
        "agent.orchestrator.engine.asyncio.sleep", new_callable=AsyncMock
    ) as sleep_mock:
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-weight-loss-retry",
                agent_id="weight_loss_v1",
                message="我今天午饭吃了这些，你知道多少热量吗",
                attachments=[
                    ChatAttachment(
                        name="meal.png",
                        type="image/png",
                        kind="image",
                        size=4,
                        content="food photo",
                        data_url="data:image/png;base64,ZmFrZQ==",
                    )
                ],
            )
        )

    assert provider.chat.await_count == 3
    assert [call.args[0] for call in sleep_mock.await_args_list] == [2.0, 5.0]
    assert result.model_used == "vision-retry-model"
    assert "465 kcal" in result.response
    summary = store.summary("conv-weight-loss-retry", days=1)
    assert summary["totals"]["intake"] == 465
    event_types = [event.type for event in result.events]
    assert event_types.count("weight_loss.analysis.retrying") == 2
    assert "weight_loss.analysis.completed" in event_types
    assert "weight_loss.analysis.failed" not in event_types


@pytest.mark.asyncio
async def test_weight_loss_advice_uses_natural_chat_format(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_advice.db")
    store.upsert_profile("conv-weight-loss-advice", {"daily_calorie_goal": 1600})
    store.add_meal(
        "conv-weight-loss-advice",
        {
            "meal_name": "日料午餐",
            "meal_type": "lunch",
            "total_calories": 1570,
            "calorie_min": 1320,
            "calorie_max": 1820,
            "source": "image",
            "raw_json": {
                "items": [
                    {"name": "天妇罗拼盘", "calories": 420},
                    {"name": "豚骨叉烧拉面", "calories": 650},
                ]
            },
        },
    )
    engine = AgentEngine(registry, weight_loss_store=store)
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(
                {
                    "intent": "advice",
                    "profile_updates": {},
                    "meal": {"should_log": False, "total_calories": 0, "items": []},
                    "exercise": {"should_log": False, "activity": "", "calories_burned": 0},
                    "clarifying_question": "",
                    "assistant_response": "是的，主要高在天妇罗的吸油和拉面的浓汤、面条、叉烧。天妇罗约 420 kcal，拉面约 650 kcal，所以这两个加起来就接近 1000 kcal。",
                    "assistant_notes": ["用户对天妇罗和拉面的热量感到惊讶，属于对上轮估算的反馈和咨询"],
                },
                ensure_ascii=False,
            ),
            model="vision-advice-model",
            usage={"input": 90, "output": 70},
        )
    )

    with patch.object(engine, "_get_provider", return_value=provider):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-weight-loss-advice",
                agent_id="weight_loss_v1",
                message="这个天妇罗和拉面的热量这么吓人的吗",
            )
        )

    assert result.response.startswith("是的，主要高在天妇罗")
    assert "**热量统计**" not in result.response
    assert "**备注**" not in result.response
    assert "用户对天妇罗" not in result.response
    assert "今天已记录" in result.response
    assert result.model_used == "vision-advice-model"
    assert "模型：" not in result.response
    assert "vision-advice-model" not in result.response
    assert "weight_loss.meal.logged" not in [event.type for event in result.events]


@pytest.mark.asyncio
async def test_super_chat_does_not_route_day_recap_meal_words_to_weight_loss(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_false_positive.db")
    engine = AgentEngine(registry, weight_loss_store=store)
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content="老板，今天不是一无所获，至少你投了简历。先把明天最小的一件事写下来就好。",
            model="chat-model",
            usage={"input": 40, "output": 20},
        )
    )

    with patch.object(engine, "_get_provider", return_value=provider):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-day-recap-not-weight-loss",
                agent_id="super_chat",
                message=(
                    "我回忆一下今天，11点起床，十二点点外卖吃饭看视频，"
                    "睡醒四点，刷视频到六点，做完吃完饭八点，"
                    "我一天什么都没干，只投了几份简历。"
                ),
            )
        )

    assert result.agent_id == "super_chat"
    assert "今天已记录" not in result.response
    tools = provider.chat.await_args.kwargs["tools"]
    weight_loss_tool = next(tool for tool in tools if tool.name == "weight_loss_v1")
    assert "do not call it merely because the user mentions meals" in weight_loss_tool.description
    event_types = [event.type for event in result.events]
    assert "agent.delegated" not in event_types
    assert "weight_loss.analysis.started" not in event_types
    assert "model.started" in event_types


@pytest.mark.asyncio
async def test_weight_loss_conversation_response_preserves_markdown_newlines(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_markdown_response.db")
    engine = AgentEngine(registry, weight_loss_store=store)
    provider = AsyncMock()
    provider.chat = AsyncMock(
        return_value=LLMResponse(
            content=json.dumps(
                {
                    "intent": "advice",
                    "profile_updates": {},
                    "meal": {"should_log": False, "total_calories": 0, "items": []},
                    "exercise": {"should_log": False, "activity": "", "calories_burned": 0},
                    "assistant_response": "可以这样看：\n\n### 今天不算空白\n- 你投了简历\n- 你吃了饭",
                    "assistant_notes": ["用户在复盘时间线", "建议把明天最小任务写下来"],
                },
                ensure_ascii=False,
            ),
            model="vision-advice-model",
            usage={"input": 80, "output": 40},
        )
    )

    with patch.object(engine, "_get_provider", return_value=provider):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-weight-loss-markdown-response",
                agent_id="weight_loss_v1",
                message="今天吃得有点乱，帮我看看怎么调整",
            )
        )

    assert "可以这样看：\n\n### 今天不算空白\n- 你投了简历" in result.response
    assert "用户在复盘时间线" not in result.response
    assert "- 建议把明天最小任务写下来" in result.response


@pytest.mark.asyncio
async def test_image_generation_agent_help_command_uses_protocol_without_model(engine):
    with patch.object(engine, "_get_provider", side_effect=AssertionError("help command should not call a model")):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-aigc-command-help",
                agent_id="image_generation_v1",
                message="/help",
            )
        )

    assert result.agent_id == "image_generation_v1"
    assert result.skills_used == ["image_generation_commands"]
    assert "/generate <提示词>" in result.response
    assert "/refine <提示词>" in result.response
    event_types = [event.type for event in result.events]
    assert "aigc.command.received" in event_types
    assert "aigc.prompt_review.started" not in event_types
    assert "aigc.image.started" not in event_types


@pytest.mark.asyncio
async def test_weight_loss_agent_slash_commands_use_database_without_model(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_commands.db")
    engine = AgentEngine(registry, weight_loss_store=store)

    async def send(message: str):
        return await engine.process(
            ChatRequest(
                conversation_id="conv-weight-loss-commands",
                agent_id="weight_loss_v1",
                message=message,
            )
        )

    with patch.object(engine, "_get_provider", side_effect=AssertionError("slash commands should not call a model")):
        goal_result = await send("/goal 每日目标1600 维持热量2200")
        meal_result = await send("/log 午餐 鸡胸饭 560kcal")
        exercise_result = await send("/exercise 跑步 260kcal 35分钟")
        today_result = await send("/today")
        history_result = await send("/history 7d")
        undo_result = await send("/undo")

    profile = store.get_profile("conv-weight-loss-commands")
    summary = store.summary("conv-weight-loss-commands", days=1)
    meals = store.list_meals("conv-weight-loss-commands", days=7)
    exercises = store.list_exercises("conv-weight-loss-commands", days=7)

    assert profile["daily_calorie_goal"] == 1600
    assert profile["maintenance_calories"] == 2200
    assert "目标档案已更新" in goal_result.response
    assert "560 kcal" in meal_result.response
    assert "260 kcal" in exercise_result.response
    assert "今日统计" in today_result.response
    assert "鸡胸饭" in history_result.response
    assert "跑步" in history_result.response
    assert "已撤销最近一条运动" in undo_result.response
    assert summary["totals"]["intake"] == 560
    assert summary["totals"]["exercise"] == 0
    assert len(meals) == 1
    assert exercises == []

    event_types = [event.type for event in history_result.events]
    assert "weight_loss.command.received" in event_types
    assert "weight_loss.summary.completed" in event_types


@pytest.mark.asyncio
async def test_super_chat_routes_agent_command_protocol_to_weight_loss_agent(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_agent_commands.db")
    engine = AgentEngine(registry, weight_loss_store=store)
    conversation_id = "conv-super-agent-command"
    store.upsert_profile(conversation_id, {"daily_calorie_goal": 1600, "maintenance_calories": 2200})
    store.add_meal(
        conversation_id,
        {
            "meal_name": "鸡胸饭",
            "meal_type": "lunch",
            "total_calories": 560,
            "source": "test",
        },
    )

    with patch.object(engine, "_get_provider", side_effect=AssertionError("agent commands should not call a model")):
        history_result = await engine.process(
            ChatRequest(
                conversation_id=conversation_id,
                agent_id="super_chat",
                message="/agent weight_loss_v1 /history 7d",
            )
        )
        today_result = await engine.process(
            ChatRequest(
                conversation_id=conversation_id,
                agent_id="super_chat",
                message="/weight_loss/today",
            )
        )

    assert history_result.agent_id == "weight_loss_v1"
    assert history_result.model_used == ""
    assert "最近 7 天健康记录" in history_result.response
    assert "鸡胸饭" in history_result.response
    assert "今日统计" in today_result.response
    assert "1640 kcal" in today_result.response

    event_types = [event.type for event in history_result.events]
    assert "agent.command.routed" in event_types
    assert "agent.delegated" in event_types
    assert "weight_loss.command.received" in event_types
    route = next(event for event in history_result.events if event.type == "agent.command.routed")
    assert route.payload["protocol_version"] == "agent_command.v1"
    assert route.payload["target_agent_id"] == "weight_loss_v1"
    assert route.payload["command_text"] == "/history 7d"
    delegation = next(event for event in history_result.events if event.type == "agent.delegated")
    assert delegation.payload["reason"] == "command_protocol"
    assert delegation.payload["forced"] is True


@pytest.mark.asyncio
async def test_super_chat_routes_agent_command_protocol_to_image_generation_agent(engine):
    review_response = LLMResponse(
        content=(
            '{"should_generate": true, "final_prompt": "cinematic vintage desk lamp poster", '
            '"aspect_ratio": "1:1", "review_notes": ["已按专业海报方向修饰"]}'
        ),
        tool_calls=[],
        model="review-model",
        usage={"input": 18, "output": 9},
    )
    image_client = MagicMock()
    image_client.image_model = "image-01"
    image_client.generate_image = AsyncMock(
        return_value={"id": "img_command", "data": {"image_urls": ["https://example.com/command.png"]}}
    )

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(return_value=review_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-aigc-command",
                agent_id="super_chat",
                message="/生图 /refine 复古台灯海报",
            )
        )

    assert result.agent_id == "image_generation_v1"
    assert result.skills_used == ["prompt_refine", "image_generation"]
    assert "![AI 生图 1](https://example.com/command.png)" in result.response
    image_client.generate_image.assert_awaited_once()

    review_user_message = provider.chat.await_args.args[0][1].content
    assert "当前用户请求：\n复古台灯海报" in review_user_message
    assert "target_agent.command" in review_user_message

    event_types = [event.type for event in result.events]
    assert "agent.command.routed" in event_types
    assert "aigc.command.received" in event_types
    assert "agent.input_context.built" in event_types
    route = next(event for event in result.events if event.type == "agent.command.routed")
    assert route.payload["target_agent_id"] == "image_generation_v1"
    assert route.payload["command_text"] == "/refine 复古台灯海报"
    command_event = next(event for event in result.events if event.type == "aigc.command.received")
    assert command_event.payload["command"] == "refine"
    input_event = next(event for event in result.events if event.type == "agent.input_context.built")
    assert input_event.payload["packet"]["current_request"] == "复古台灯海报"
    assert any(
        stage["stage_id"] == "target_agent.command"
        for stage in input_event.payload["packet"]["stage_contexts"]
    )


@pytest.mark.asyncio
async def test_super_chat_profile_update_is_shared_with_weight_loss_agent(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_shared_profile.db")
    engine = AgentEngine(registry, weight_loss_store=store)
    delegate_response = agent_tool_response(
        "weight_loss_v1",
        "那帮我设置一下身高168cm，体重116kg，性别男，年龄26吧",
        "用户明确要求设置身高体重性别年龄等减脂档案",
    )
    provider = AsyncMock()
    provider.chat = AsyncMock(
        side_effect=[
            delegate_response,
            LLMResponse(content="{}", model="profile-test-model", usage={}),
            LLMResponse(
                content="已把减脂档案设置好了：身高 168 cm，当前体重 116 kg，性别 男，年龄 26。",
                model="final-model",
                usage={"input": 24, "output": 8},
            ),
        ]
    )

    with patch.object(engine, "_get_provider", return_value=provider):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-profile",
                agent_id="super_chat",
                message="那帮我设置一下身高168cm，体重116kg，性别男，年龄26吧",
            )
        )

    profile = store.get_profile("conv-super-profile")
    assert result.agent_id == "super_chat"
    assert result.skills_used[0] == "weight_loss_v1"
    assert profile["height_cm"] == 168
    assert profile["current_weight_kg"] == 116
    assert profile["sex"] == "男"
    assert profile["age_years"] == 26

    profile_result = await engine.process(
        ChatRequest(
            conversation_id="conv-super-profile",
            agent_id="weight_loss_v1",
            message="/profile",
        )
    )

    assert "身高 168" in profile_result.response
    assert "当前体重 116" in profile_result.response
    assert "性别 男" in profile_result.response
    assert "年龄 26" in profile_result.response
    event_types = [event.type for event in result.events]
    assert "tool.completed" in event_types
    assert "agent.tool.delegated" in event_types
    assert "weight_loss.profile.updated" not in event_types
    payload = agent_tool_payload(provider.chat.await_args_list[-1].args[0], "weight_loss_v1")
    assert payload["data"]["agent_id"] == "weight_loss_v1"
    assert "身高 168" in payload["data"]["response"]


@pytest.mark.asyncio
async def test_weight_loss_records_are_scoped_by_user_id(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_user_scopes.db")
    engine = AgentEngine(registry, weight_loss_store=store)

    async def send(user_id: str, conversation_id: str, message: str):
        return await engine.process(
            ChatRequest(
                conversation_id=conversation_id,
                user_id=user_id,
                agent_id="weight_loss_v1",
                message=message,
            )
        )

    with patch.object(engine, "_get_provider", side_effect=AssertionError("slash commands should not call a model")):
        await send("0", "conv-user-0-a", "/goal 身高168cm 体重116kg 性别男 年龄26")
        await send("0", "conv-user-0-a", "/log 午餐 鸡胸饭 560kcal")
        await send("1", "conv-user-1-a", "/goal 身高180cm 体重80kg 性别女 年龄31")
        await send("1", "conv-user-1-a", "/log 早餐 酸奶 210kcal")
        profile0_result = await send("0", "conv-user-0-b", "/profile")
        profile1_result = await send("1", "conv-user-1-b", "/profile")
        history0_result = await send("0", "conv-user-0-c", "/history 7d")
        history1_result = await send("1", "conv-user-1-c", "/history 7d")

    summary0 = store.summary("another-conv-for-user-0", days=1, user_id="0")
    summary1 = store.summary("another-conv-for-user-1", days=1, user_id="1")

    assert summary0["scope_id"] == "user:0"
    assert summary1["scope_id"] == "user:1"
    assert summary0["profile"]["height_cm"] == 168
    assert summary0["profile"]["current_weight_kg"] == 116
    assert summary0["totals"]["intake"] == 560
    assert summary1["profile"]["height_cm"] == 180
    assert summary1["profile"]["current_weight_kg"] == 80
    assert summary1["totals"]["intake"] == 210
    assert "身高 168" in profile0_result.response
    assert "当前体重 116" in profile0_result.response
    assert "身高 180" in profile1_result.response
    assert "当前体重 80" in profile1_result.response
    assert "鸡胸饭" in history0_result.response
    assert "酸奶" not in history0_result.response
    assert "酸奶" in history1_result.response
    assert "鸡胸饭" not in history1_result.response


def test_weight_loss_store_migrates_legacy_conversation_scope(tmp_path):
    db_path = tmp_path / "legacy_weight_loss.db"
    now = datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE weight_loss_profiles (
                conversation_id TEXT PRIMARY KEY,
                daily_calorie_goal INTEGER,
                maintenance_calories INTEGER,
                target_deficit INTEGER,
                current_weight_kg REAL,
                target_weight_kg REAL,
                height_cm REAL,
                sex TEXT,
                activity_level TEXT,
                notes TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE weight_loss_meals (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                logged_at TEXT NOT NULL,
                meal_name TEXT,
                meal_type TEXT,
                total_calories INTEGER NOT NULL,
                calorie_min INTEGER,
                calorie_max INTEGER,
                protein_g REAL,
                carbs_g REAL,
                fat_g REAL,
                confidence REAL,
                source TEXT,
                notes TEXT,
                image_count INTEGER NOT NULL DEFAULT 0,
                raw_json TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE weight_loss_exercises (
                id TEXT PRIMARY KEY,
                conversation_id TEXT NOT NULL,
                logged_at TEXT NOT NULL,
                activity TEXT,
                calories_burned INTEGER NOT NULL,
                duration_min REAL,
                notes TEXT,
                raw_json TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            INSERT INTO weight_loss_profiles (
                conversation_id, daily_calorie_goal, maintenance_calories, current_weight_kg,
                height_cm, sex, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            ("legacy-conv", 1600, 2200, 116, 168, "男", now, now),
        )
        conn.execute(
            """
            INSERT INTO weight_loss_meals (
                id, conversation_id, logged_at, meal_name, meal_type, total_calories, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            ("meal_legacy", "__default_user__", now, "旧记录餐食", "lunch", 465, now),
        )

    store = WeightLossStore(db_path)
    profile = store.get_profile("any-conversation")
    summary = store.summary("another-conversation", days=1)

    assert profile["conversation_id"] == "user:0"
    assert profile["user_id"] == "0"
    assert profile["daily_calorie_goal"] == 1600
    assert profile["maintenance_calories"] == 2200
    assert profile["current_weight_kg"] == 116
    assert profile["height_cm"] == 168
    assert summary["scope_id"] == "user:0"
    assert summary["totals"]["intake"] == 465

    with sqlite3.connect(db_path) as conn:
        conn.row_factory = sqlite3.Row
        meal = conn.execute("SELECT conversation_id, user_id FROM weight_loss_meals WHERE id = ?", ("meal_legacy",)).fetchone()
        columns = {row["name"] for row in conn.execute("PRAGMA table_info(weight_loss_profiles)").fetchall()}

    assert "user_id" in columns
    assert "age_years" in columns
    assert dict(meal) == {"conversation_id": "user:0", "user_id": "0"}


@pytest.mark.asyncio
async def test_weight_loss_goal_command_body_metrics_do_not_become_calorie_goals(registry, tmp_path):
    store = WeightLossStore(tmp_path / "weight_loss_body_metrics_command.db")
    engine = AgentEngine(registry, weight_loss_store=store)

    result = await engine.process(
        ChatRequest(
            conversation_id="conv-body-metrics-command",
            agent_id="weight_loss_v1",
            message="/goal 身高168cm 体重116kg 性别男 年龄26",
        )
    )

    profile = store.get_profile("another-weight-loss-conv")
    assert result.model_used == ""
    assert profile["height_cm"] == 168
    assert profile["current_weight_kg"] == 116
    assert profile["sex"] == "男"
    assert profile["age_years"] == 26
    assert profile["daily_calorie_goal"] is None
    assert profile["maintenance_calories"] is None
