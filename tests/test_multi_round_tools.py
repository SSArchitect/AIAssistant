"""Regressions for tools disappearing after the first tool-result round."""
import json
from unittest.mock import patch

import httpx
import openai
import pytest
import pytest_asyncio

from agent.llm.base import LLMResponse, LLMStreamChunk, ToolCall
from agent.llm.deepseek_provider import DeepSeekProvider
from agent.llm.doubao_provider import DoubaoProvider
from agent.llm.openai_provider import OpenAIProvider
from agent.orchestrator.engine import AgentEngine
from agent.schemas.chat import ChatRequest
from agent.skills.base import SkillResult
from agent.skills.builtin.echo import EchoSkill
from agent.skills.registry import SkillRegistry


@pytest_asyncio.fixture
async def client(tmp_path, monkeypatch):
    from agent.main import app, lifespan
    monkeypatch.setenv("AGENT_MEMORY_STORAGE_PATH", str(tmp_path / "memory.json"))
    async with lifespan(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as session:
            yield session


class RetryableEcho(EchoSkill):
    async def execute(self, **kwargs):
        if kwargs.get("text") == "fail":
            return SkillResult(success=False, error="Temporary echo failure")
        return await super().execute(**kwargs)


@pytest.fixture
def tool_engine():
    registry = SkillRegistry()
    registry.register(RetryableEcho())
    return AgentEngine(registry)


class MultiRoundProvider:
    model = "multi-round-test"
    streaming_enabled = True

    def __init__(self, capability=None, first_tool_fails=False):
        if capability is not None:
            self.supports_streaming_tool_calls = capability
        self.first_tool_fails = first_tool_fails
        self.calls = []

    def next_response(self, messages, tools, mode):
        assert tools and "echo" in {tool.name for tool in tools}
        self.calls.append(mode)
        round_number = len(self.calls)
        results = [message for message in messages if message.role == "tool"]
        assert len(results) == round_number - 1
        assert [message.tool_call_id for message in results] == [f"echo_{i}" for i in range(1, round_number)]
        if results:
            assert json.loads(results[0].content)["success"] is (not self.first_tool_fails)
        if round_number <= 2:
            return LLMResponse(
                content=f"Checking round {round_number}.", model=self.model,
                tool_calls=[ToolCall(id=f"echo_{round_number}", name="echo", arguments={
                    "text": "fail" if round_number == 1 and self.first_tool_fails else f"result {round_number}",
                })],
            )
        assert round_number == 3
        return LLMResponse(content="Final answer", model=self.model)

    async def chat(self, messages, tools=None, **kwargs):
        return self.next_response(messages, tools, "chat")

    async def chat_stream_response(self, messages, tools=None, **kwargs):
        response = self.next_response(messages, tools, "stream")
        yield LLMStreamChunk(text=response.content)
        yield LLMStreamChunk(response=response)

    async def chat_stream(self, messages, tools=None, **kwargs):
        # This reproduces the production failure: a text-only stream cannot
        # deliver the next structured tool call after tools were dropped.
        yield "<tool_call>echo<arg_key>text</arg_key><arg_value>result 2</arg_value></tool_call>"


@pytest.mark.asyncio
@pytest.mark.parametrize("capability", [None, False, True])
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("first_tool_fails", [False, True])
async def test_every_tool_round_retains_tools_and_results(tool_engine, capability, streaming, first_tool_fails):
    provider = MultiRoundProvider(capability, first_tool_fails)
    tokens, provisional, intermediate = [], [], []
    with patch.object(tool_engine, "_get_provider", return_value=provider):
        result = await tool_engine.process(
            ChatRequest(conversation_id="multi-round", message="Use echo twice then answer", memory_enabled=False, stream=streaming),
            on_token=tokens.append if streaming else None,
            on_provisional_token=provisional.append,
            on_intermediate=lambda text, index: intermediate.append(text),
        )
    assert provider.calls == (["stream"] * 3 if streaming and capability is True else ["chat"] * 3)
    assert result.response == "Final answer"
    assert intermediate == ["Checking round 1.", "Checking round 2."]
    assert "Checking" not in "".join(tokens)
    assert "<tool_call>" not in result.response
    model_events = [event for event in result.events if event.type == "model.completed"]
    assert [len(event.payload["tool_calls"]) for event in model_events] == [1, 1, 0]
    assert tool_engine.trace_store.get_run(result.run_id).status == "completed"


@pytest.mark.asyncio
@pytest.mark.parametrize("provider_type,model", [
    (OpenAIProvider, "gpt-4o"),
    (DeepSeekProvider, "deepseek-chat"),
    (DoubaoProvider, "glm-5.3"),
    (DoubaoProvider, "doubao-seed-2.1-turbo"),
    (DoubaoProvider, "minimax-m3"),
])
async def test_openai_compatible_providers_stream_multiple_tool_rounds(tool_engine, provider_type, model):
    requests = []

    def handler(request):
        payload = json.loads(request.content)
        requests.append(payload)
        round_number = len(requests)
        assert payload["stream"] is True
        assert payload["tools"][0]["function"]["name"] == "echo"
        assert len([message for message in payload["messages"] if message["role"] == "tool"]) == round_number - 1
        delta = {"content": f"Checking round {round_number}." if round_number <= 2 else "Final answer"}
        chunks = [{"model": model, "choices": [{"delta": delta}]}]
        if round_number <= 2:
            chunks.append({"model": model, "choices": [{"delta": {"tool_calls": [{
                "index": 0, "id": f"echo_{round_number}", "type": "function",
                "function": {"name": "echo", "arguments": '{"text":'},
            }]}}]})
            chunks.append({"model": model, "choices": [{"delta": {"tool_calls": [{
                "index": 0, "function": {"arguments": json.dumps(f"result {round_number}") + "}"},
            }]}}]})
        body = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=body, headers={"content-type": "text/event-stream"})

    provider = provider_type(api_key="test-key", model=model)
    await provider.client.close()
    provider.client = openai.AsyncOpenAI(api_key="test-key", base_url="https://provider.test/v1", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    tokens, provisional = [], []
    try:
        with patch.object(tool_engine, "_get_provider", return_value=provider):
            result = await tool_engine.process(
                ChatRequest(conversation_id="sdk-rounds", message="Use echo twice then answer", memory_enabled=False, stream=True),
                on_token=tokens.append, on_provisional_token=provisional.append,
            )
        assert len(requests) == 3
        assert tokens == ["Final answer"]
        assert provisional == ["Checking round 1.", "Checking round 2.", "Final answer"]
        assert result.response == "Final answer"
        assert result.skills_used == ["echo"]
    finally:
        await provider.client.close()


@pytest.mark.asyncio
async def test_sse_text_only_provider_completes_two_tool_rounds(client):
    import agent.main as main
    provider = MultiRoundProvider(False)
    with patch.object(main.engine, "_get_provider", return_value=provider):
        response = await client.post("/agent/chat/stream", json={
            "conversation_id": "sse-multi-round", "message": "Use echo twice then answer", "memory_enabled": False,
        })
    assert response.status_code == 200
    events = []
    for block in response.text.split("\n\n"):
        lines = block.splitlines()
        if len(lines) == 2 and lines[0].startswith("event: ") and lines[1].startswith("data: "):
            events.append((lines[0][7:], json.loads(lines[1][6:])))
    assert provider.calls == ["chat"] * 3
    assert "".join(data["text"] for kind, data in events if kind == "token") == "Final answer"
    assert next(data for kind, data in events if kind == "response")["response"] == "Final answer"
    assert "<tool_call>" not in response.text
    assert [data["round"] for kind, data in events if kind == "intermediate"] == [1, 2]
