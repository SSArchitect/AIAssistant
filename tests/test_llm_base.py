"""Unit tests for LLM base classes and factory."""
import pytest
from agent.llm.base import LLMMessage, LLMResponse, ToolCall, ToolDefinition
from agent.llm.factory import create_provider
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.openai_provider import OpenAIProvider
from agent.config import runtime_config
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class TestLLMMessage:
    def test_basic_message(self):
        msg = LLMMessage(role="user", content="hello")
        assert msg.role == "user"
        assert msg.content == "hello"
        assert msg.tool_call_id is None
        assert msg.tool_calls is None

    def test_tool_message(self):
        msg = LLMMessage(role="tool", content='{"result": 42}', tool_call_id="call_123")
        assert msg.tool_call_id == "call_123"

    def test_assistant_with_tool_calls(self):
        msg = LLMMessage(
            role="assistant",
            content="",
            tool_calls=[{"id": "call_1", "name": "calc", "arguments": {"expr": "1+1"}}],
        )
        assert len(msg.tool_calls) == 1


def test_openai_provider_preserves_multimodal_user_content():
    provider = OpenAIProvider(api_key="test-key", model="test-model")
    converted = provider._convert_messages(
        [
            LLMMessage(
                role="user",
                content=[
                    {"type": "text", "text": "请估算这餐热量"},
                    {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZmFrZQ=="}},
                ],
            )
        ]
    )

    assert converted[0]["content"][0] == {"type": "text", "text": "请估算这餐热量"}
    assert converted[0]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")


def test_openai_compatible_provider_accepts_explicit_timeout():
    provider = OpenAIProvider(
        api_key="test-key",
        model="test-model",
        timeout_seconds=60,
    )

    assert provider.client.timeout.connect == 60
    assert provider.client.timeout.read == 60


def test_minimax_provider_defaults_to_sixty_second_timeout():
    provider = MiniMaxProvider(api_key="test-key")

    assert provider.client.timeout.connect == 60
    assert provider.client.timeout.read == 60


def test_minimax_provider_uses_runtime_timeout():
    keys = [
        "llm.default_provider",
        "llm.minimax.api_key",
        "llm.minimax.model",
        "llm.minimax.base_url",
        "llm.minimax.thinking",
        "llm.minimax.timeout",
    ]
    previous = {key: runtime_config.get(key) for key in keys}
    try:
        runtime_config.update(
            {
                "llm.default_provider": "minimax",
                "llm.minimax.api_key": "test-key",
                "llm.minimax.model": "MiniMax-M3",
                "llm.minimax.base_url": "https://api.minimaxi.com/v1",
                "llm.minimax.thinking": "disabled",
                "llm.minimax.timeout": "75",
            }
        )

        provider = create_provider()

        assert isinstance(provider, MiniMaxProvider)
        assert provider.client.timeout.connect == 75
        assert provider.client.timeout.read == 75
    finally:
        runtime_config.update(previous)


class TestLLMResponse:
    def test_basic_response(self):
        resp = LLMResponse(content="hello", model="test-model")
        assert resp.content == "hello"
        assert resp.tool_calls == []
        assert resp.usage == {}

    def test_response_with_tool_calls(self):
        resp = LLMResponse(
            content="",
            tool_calls=[ToolCall(id="1", name="calc", arguments={"x": 1})],
            model="test",
        )
        assert len(resp.tool_calls) == 1
        assert resp.tool_calls[0].name == "calc"


class TestToolDefinition:
    def test_definition(self):
        td = ToolDefinition(
            name="calculator",
            description="Calculate",
            parameters={"type": "object", "properties": {}},
        )
        assert td.name == "calculator"


class TestSkillToToolDefinition:
    def test_conversion(self):
        class TestSkill(Skill):
            def metadata(self):
                return SkillMetadata(
                    name="test",
                    description="Test skill",
                    parameters=[
                        SkillParameter(name="input", type="string", description="Input text", required=True),
                        SkillParameter(name="count", type="integer", description="Count", required=False),
                    ],
                )

            async def execute(self, **kwargs):
                return SkillResult(success=True)

        skill = TestSkill()
        td = skill.to_tool_definition()

        assert td["name"] == "test"
        assert td["parameters"]["type"] == "object"
        assert "input" in td["parameters"]["properties"]
        assert "count" in td["parameters"]["properties"]
        assert "input" in td["parameters"]["required"]
        assert "count" not in td["parameters"]["required"]
        assert td["parameters"]["properties"]["input"]["type"] == "string"
        assert td["parameters"]["properties"]["count"]["type"] == "integer"
