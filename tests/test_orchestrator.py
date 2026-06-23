"""Unit tests for the orchestrator engine with mock LLM."""
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

from agent.aigc.share_card_renderer import ShareCardRenderResult
from agent.orchestrator.engine import AgentEngine, DEEP_RESEARCH_PLAN_MARKER
from agent.llm.base import LLMResponse, ToolCall, LLMMessage
from agent.schemas.chat import ChatAttachment, ChatRequest
from agent.schemas.memory import MemoryContext, RoleProfile
from agent.skills.registry import SkillRegistry
from agent.skills.builtin.echo import EchoSkill
from agent.skills.builtin.calculator import CalculatorSkill
from agent.skills.builtin.datetime_skill import DateTimeSkill
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult
from agent.weight_loss import WeightLossStore


@pytest.fixture
def registry():
    reg = SkillRegistry()
    reg.register(EchoSkill())
    reg.register(CalculatorSkill())
    reg.register(DateTimeSkill())
    return reg


@pytest.fixture
def engine(registry):
    return AgentEngine(registry)


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
    event_types = [event.type for event in result.events]
    assert event_types[0] == "run.started"
    assert "model.started" in event_types
    assert "model.completed" in event_types
    assert event_types[-1] == "run.completed"


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
    assert system_prompt.index("系统级配置：") < system_prompt.index("记忆系统：")
    assert system_prompt.index("长期记忆：") < system_prompt.index("角色记忆：")
    assert system_prompt.index("角色记忆：") < system_prompt.index("短期记忆：")
    assert system_prompt.index("短期记忆：") < system_prompt.index("上下文与记忆使用规则：")
    assert "本轮用户消息优先于历史消息" in system_prompt
    assert result.role_id == "mentor"
    assert [record.id for record in result.memory_context] == [memory.id]
    event_types = [event.type for event in result.events]
    assert "memory.loaded" in event_types
    assert "context.built" in event_types
    context_event = next(event for event in result.events if event.type == "context.built")
    assert "Patient interview coach" in context_event.payload["system_prompt"]
    assert context_event.payload["prompt_section_order"] == [
        "base_system_prompt",
        "system_config",
        "temporal_context",
        "memory_system",
        "context_priority_rules",
    ]
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
async def test_super_chat_mode_prompts_are_injected(engine):
    """Selected Super Chat modes should add hidden system instructions."""
    plan_response = LLMResponse(
        content=json.dumps(
            {
                "goal": "调研方向",
                "steps": [
                    {
                        "id": "analyze",
                        "type": "analyze",
                        "title": "分析",
                        "description": "整理已有上下文。",
                    },
                    {
                        "id": "final",
                        "type": "final",
                        "title": "汇总",
                        "description": "给出结论。",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        tool_calls=[],
        model="planner-model",
        usage={},
    )
    summary_response = LLMResponse(
        content="I will think through the task.",
        tool_calls=[],
        model="test-model",
        usage={},
    )
    memory_response = LLMResponse(content='{"memories":[]}', tool_calls=[], model="memory-model", usage={})

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[plan_response, summary_response, memory_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-mode",
                message="帮我调研这个方向",
                agent_id="super_chat",
                mode_ids=["thinking"],
                mode_prompts=[
                    "使用思考模式：先规划，再按需检索和分析。",
                ],
                )
            )

    context_event = next(event for event in result.events if event.type == "context.built")
    system_prompt = context_event.payload["system_prompt"]
    assert "Super Chat 模式指令：" in system_prompt
    assert "AI 生图 (image_generation_v1)" in system_prompt
    assert "深度研究 (deep_research_v1)" in system_prompt
    assert "使用思考模式：先规划，再按需检索和分析。" in system_prompt
    assert system_prompt.index("可用的专业 Agent：") < system_prompt.index("记忆系统：")
    assert system_prompt.index("Super Chat 模式指令：") < system_prompt.index("记忆系统：")
    assert context_event.payload["messages"][-1]["content"] == "帮我调研这个方向"
    assert context_event.payload["mode_ids"] == ["thinking"]
    assert context_event.payload["mode_prompts"] == [
        "使用思考模式：先规划，再按需检索和分析。",
    ]
    assert context_event.payload["final_model_request"]["workflow"] == "thinking"
    assert context_event.payload["prompt_section_order"] == [
        "base_system_prompt",
        "system_config",
        "temporal_context",
        "agent_context",
        "mode_context",
        "memory_system",
        "context_priority_rules",
    ]
    event_types = [event.type for event in result.events]
    assert "thinking.plan.created" in event_types
    assert "thinking.summary.completed" in event_types


@pytest.mark.asyncio
async def test_thinking_mode_executes_planned_search_before_summary(engine):
    """Thinking mode should execute search steps as workflow nodes, not just describe them."""

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
            return SkillResult(
                success=True,
                data={
                    "query": kwargs["query"],
                    "results": [
                        {
                            "title": "RayNeo company update",
                            "url": "https://example.com/rayneo-update",
                            "snippet": "RayNeo latest strategy details.",
                            "source": "web",
                        }
                    ],
                },
                display_text="RayNeo company update",
            )

    fake_search = FakeSearchSkill()
    engine.skill_registry.register(fake_search)
    plan_response = LLMResponse(
        content=json.dumps(
            {
                "goal": "了解雷鸟创新工作节奏和战略",
                "steps": [
                    {
                        "id": "search_rayneo_strategy",
                        "type": "search",
                        "title": "检索公开资料",
                        "description": "搜索公司战略和工作节奏信息。",
                        "query": "雷鸟创新 RayNeo 工作节奏 公司战略 2026",
                    },
                    {
                        "id": "analyze",
                        "type": "analyze",
                        "title": "分析",
                        "description": "交叉核对来源。",
                    },
                    {
                        "id": "final",
                        "type": "final",
                        "title": "汇总",
                        "description": "输出结果。",
                    },
                ],
            },
            ensure_ascii=False,
        ),
        tool_calls=[],
        model="planner-model",
        usage={"input": 10, "output": 20},
    )
    summary_response = LLMResponse(
        content="基于搜索结果，雷鸟创新需要关注公司战略和岗位节奏。",
        tool_calls=[],
        model="summary-model",
        usage={"input": 30, "output": 40},
    )
    memory_response = LLMResponse(content='{"memories":[]}', tool_calls=[], model="memory-model", usage={})

    with patch.object(engine, "_get_provider") as mock_provider:
        provider = AsyncMock()
        provider.chat = AsyncMock(side_effect=[plan_response, summary_response, memory_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-thinking-search",
                message="了解更多吧，比如工作节奏，未来方向，公司战略之类的",
                agent_id="super_chat",
                mode_ids=["thinking"],
                mode_prompts=["使用思考模式：先规划，再按需检索和分析。"],
            )
        )

    assert fake_search.calls
    assert fake_search.calls[0]["query"] == "雷鸟创新 RayNeo 工作节奏 公司战略 2026"
    assert fake_search.calls[0]["limit"] == 8
    assert result.skills_used == ["search"]
    assert len(result.citations) == 1
    assert result.citations[0].url == "https://example.com/rayneo-update"
    event_types = [event.type for event in result.events]
    assert "thinking.plan.created" in event_types
    assert "thinking.step.started" in event_types
    assert "tool.started" in event_types
    assert "tool.completed" in event_types
    assert "thinking.summary.completed" in event_types


@pytest.mark.asyncio
async def test_deep_research_generates_plan_before_execution(engine):
    """Deep Research should produce a confirmable plan before searching."""
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
                agent_id="deep_research_v1",
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
            )
        )

    assert result.agent_id == "deep_research_v1"
    assert "研究计划大纲" in result.response
    event_types = [event.type for event in result.events]
    assert "research.plan.completed" in event_types
    assert "model.started" not in event_types


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
        provider.chat = AsyncMock(side_effect=[query_response, summary_response, report_response])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-exec",
                message="/start",
                agent_id="deep_research_v1",
            )
        )

    assert result.response.startswith("# 研究报告")
    assert result.agent_id == "deep_research_v1"
    assert "search" in result.skills_used
    assert len(fake_search.calls) == 20
    assert len(result.citations) == 20
    assert result.plan[-1].skill == "research_report"
    event_types = [event.type for event in result.events]
    assert "research.queries.created" in event_types
    assert "research.step_summary.completed" in event_types
    assert "research.report.completed" in event_types


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
                report_response,
            ]
        )
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-summary-rejected",
                message="/start",
                agent_id="deep_research_v1",
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
        provider.chat = AsyncMock(side_effect=[query_response, summary_response, RuntimeError("report blocked")])
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-deep-report-failed",
                message="/start",
                agent_id="deep_research_v1",
            )
        )

    assert result.response.startswith("# 研究报告（降级生成）")
    assert "分块摘要：来源显示商业化在增长 [1]。" in result.response
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
    """Super Chat should call AI 生图 when the user intent is image generation."""
    review_response = LLMResponse(
        content='{"should_generate": true, "final_prompt": "cyberpunk city poster", "aspect_ratio": "9:16"}',
        tool_calls=[],
        model="review-model",
        usage={},
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
        provider.chat = AsyncMock(return_value=review_response)
        mock_provider.return_value = provider

        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-aigc-auto",
                message="帮我生成一张赛博朋克城市海报",
                agent_id="super_chat",
            )
        )

    assert result.agent_id == "image_generation_v1"
    assert result.skills_used == ["prompt_refine", "image_generation"]
    assert "![AI 生图 1](https://example.com/poster.png)" in result.response
    image_client.generate_image.assert_awaited_once()
    event_types = [event.type for event in result.events]
    assert "agent.delegated" in event_types
    delegation = next(event for event in result.events if event.type == "agent.delegated")
    assert delegation.payload["source_agent_id"] == "super_chat"
    assert delegation.payload["target_agent_id"] == "image_generation_v1"
    assert delegation.payload["reason"] == "intent"
    assert delegation.payload["forced"] is False


@pytest.mark.asyncio
async def test_super_chat_delegates_chinese_comparison_chart_to_image_agent(engine):
    """Chinese visual deliverables such as 对比图 should route through AI 生图."""
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
        provider.chat = AsyncMock(side_effect=[planner_response, research_response, review_response])
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

    assert result.agent_id == "image_generation_v1"
    assert "image_generation" in result.skills_used
    assert "![AI 生图 1](https://example.com/compare.png)" in result.response
    image_client.generate_image.assert_awaited_once()
    event_types = [event.type for event in result.events]
    assert "agent.delegated" in event_types
    assert "aigc.plan.created" in event_types
    assert "aigc.research.completed" in event_types
    delegation = next(event for event in result.events if event.type == "agent.delegated")
    assert delegation.payload["reason"] == "intent"
    assert delegation.payload["forced"] is False


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
        provider.chat = AsyncMock(side_effect=[planner_response, review_response])
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

    assert provider.chat.await_count == 2
    planning_messages = provider.chat.await_args_list[0].args[0]
    assert "比较信息交接格式" in planning_messages[0].content
    review_messages = provider.chat.await_args_list[1].args[0]
    review_user_message = review_messages[1].content
    assert "数据行：" in review_user_message
    assert "巽寮湾 | 1.5h" in review_user_message
    assert "本轮额外上下文" not in review_user_message

    event_types = [event.type for event in result.events]
    assert "aigc.planning.completed" in event_types
    assert "aigc.context_reuse.completed" in event_types
    assert "aigc.research.started" not in event_types
    plan_event = next(event for event in result.events if event.type == "aigc.plan.created")
    assert plan_event.payload["information_strategy"] == "reuse_context"
    assert plan_event.payload["brief_format"] == "structured"
    assert plan_event.payload["reuse_context_brief"] is True
    assert [step["id"] for step in plan_event.payload["steps"]] == [
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
    """The Super Chat AI 生图 mode should force delegation even for vague wording."""
    review_response = LLMResponse(
        content='{"should_generate": true, "final_prompt": "minimalist product concept render", "aspect_ratio": "1:1"}',
        tool_calls=[],
        model="review-model",
        usage={},
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
        provider.chat = AsyncMock(return_value=review_response)
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

    assert result.agent_id == "image_generation_v1"
    assert "image_generation" in result.skills_used
    assert "![AI 生图 1](https://example.com/concept.png)" in result.response
    delegation = next(event for event in result.events if event.type == "agent.delegated")
    assert delegation.payload["reason"] == "mode"
    assert delegation.payload["forced"] is True


@pytest.mark.asyncio
async def test_super_chat_research_image_intent_prepares_brief_before_generation(engine):
    """Research + image requests should collect a brief before prompt review and generation."""
    search_calls = []

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

    with patch.object(engine, "_get_provider") as mock_provider, patch(
        "agent.orchestrator.engine.MiniMaxAIGCClient.from_runtime_config",
        return_value=image_client,
    ):
        provider = AsyncMock()
        provider.chat = AsyncMock(
            side_effect=[planner_response, research_tool_response, research_final_response, review_response]
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

    assert result.agent_id == "image_generation_v1"
    assert result.skills_used == ["search", "prompt_refine", "image_generation"]
    assert result.citations and result.citations[0].url == "https://example.com/spacex-investment"
    assert result.citations[0].metadata["image_url"] == "https://example.com/spacex.jpg"
    assert search_calls and search_calls[0]["limit"] == 12
    assert result.plan
    assert [step.skill for step in result.plan] == [
        "task_decomposition",
        "retrieval",
        "image_generation",
        "final_summary",
    ]
    assert [step.status for step in result.plan] == ["completed", "completed", "completed", "completed"]
    assert "SpaceX is private" in result.plan[1].result_summary
    assert result.response.startswith("**图片结果**")
    assert "![AI 生图 1](https://example.com/spacex.png)" in result.response
    assert "**简要总结**" in result.response
    assert "**执行计划**" in result.response
    assert "**生图提示词**" not in result.response
    assert "SpaceX investment infographic based on researched facts and caveats" not in result.response
    image_client.generate_image.assert_awaited_once()

    review_user_message = provider.chat.call_args_list[3][0][0][1].content
    assert "结构化 Agent 输入（agent_input.v1）" in review_user_message
    assert "source_agent.routing" in review_user_message
    assert "target_agent.execution_planning" in review_user_message
    assert "target_agent.research_brief" in review_user_message
    assert "生图简报：" in review_user_message
    assert "SpaceX is private" in review_user_message
    assert "近期会话：" not in review_user_message
    assert "本轮额外上下文：" not in review_user_message
    assert "I cannot generate images in this chat" not in review_user_message

    event_types = [event.type for event in result.events]
    assert "agent.input_context.built" in event_types
    assert "agent.handoff_context.built" in event_types
    input_context_event = next(event for event in result.events if event.type == "agent.input_context.built")
    assert input_context_event.payload["protocol_version"] == "agent_input.v1"
    assert input_context_event.payload["stage_context_count"] == 1
    updated_input_events = [event for event in result.events if event.type == "agent.input_context.updated"]
    assert updated_input_events[-1].payload["stage_context_count"] >= 3
    assert event_types.index("aigc.planning.completed") < event_types.index("aigc.plan.created")
    assert event_types.index("aigc.plan.created") < event_types.index("memory.loaded")
    assert event_types.index("aigc.plan.created") < event_types.index("agent.delegated")
    assert event_types.index("agent.delegated") < event_types.index("aigc.research.started")
    assert event_types.index("aigc.plan.created") < event_types.index("aigc.research.started")
    assert event_types.index("aigc.research.started") < event_types.index("aigc.prompt_review.started")
    assert event_types.index("aigc.prompt_review.completed") < event_types.index("aigc.image.started")
    assert event_types.index("aigc.image.completed") < event_types.index("aigc.summary.completed")
    assert event_types.index("aigc.summary.completed") < event_types.index("aigc.plan.completed")
    assert "tool.completed" in event_types
    assert "citations.collected" in event_types
    context_event = next(event for event in result.events if event.type == "context.built")
    assert context_event.payload["context_block_count"] == 0


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

    memories = engine.role_memory.list_memories(role_id="default", kind="long_term")
    assert len(result.memory_updates) == 1
    assert result.memory_updates[0].content == "我的名字是安安"
    assert memories[0].content == "我的名字是安安"
    assert "memory.extracted" in [event.type for event in result.events]


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

    assert len(result.memory_updates) == 1
    assert result.memory_updates[0].content == "用户正在重构 agent memory 系统"
    assert result.memory_updates[0].metadata["reviewer"] == "ai"
    event_types = [event.type for event in result.events]
    assert "memory.review.completed" in event_types


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

    memory_id = "user:0:conversation:conv-compact"
    assert engine.memory.get_summary(memory_id) == "用户正在分层设计 memory 系统。"
    assert [message.content for message in engine.memory.get(memory_id)] == ["第二轮", "第二轮"]
    assert "memory.compaction.completed" in [event.type for event in result.events]


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
    provider = AsyncMock()
    provider.chat = AsyncMock(return_value=LLMResponse(content="{}", model="profile-test-model", usage={}))

    with patch.object(engine, "_get_provider", return_value=provider):
        result = await engine.process(
            ChatRequest(
                conversation_id="conv-super-profile",
                agent_id="super_chat",
                message="那帮我设置一下身高168cm，体重116kg，性别男，年龄26吧",
            )
        )

    profile = store.get_profile("conv-weight-loss-profile")
    assert result.agent_id == "weight_loss_v1"
    assert profile["height_cm"] == 168
    assert profile["current_weight_kg"] == 116
    assert profile["sex"] == "男"
    assert profile["age_years"] == 26

    profile_result = await engine.process(
        ChatRequest(
            conversation_id="conv-weight-loss-profile",
            agent_id="weight_loss_v1",
            message="/profile",
        )
    )

    assert "身高 168" in profile_result.response
    assert "当前体重 116" in profile_result.response
    assert "性别 男" in profile_result.response
    assert "年龄 26" in profile_result.response
    event_types = [event.type for event in result.events]
    assert "agent.delegated" in event_types
    assert "weight_loss.profile.updated" in event_types


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
