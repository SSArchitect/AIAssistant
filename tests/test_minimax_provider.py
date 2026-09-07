from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent.aigc.minimax_client import MiniMaxAIGCClient
from agent.llm.minimax_provider import MiniMaxProvider
from agent.llm.base import LLMMessage
from agent.orchestrator.engine import AgentEngine
from agent.schemas.chat import ChatRequest
from agent.schemas.aigc import ImageGenerationRequest, ImageGenerationResponse


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    ("configured", "enabled", "expected"),
    [
        ("disabled", None, "disabled"),
        ("adaptive", None, "adaptive"),
        ("enabled", None, "adaptive"),
        ("disabled", True, "adaptive"),
        ("adaptive", False, "disabled"),
        ("enabled", False, "disabled"),
        ("", True, "adaptive"),
        ("", False, "disabled"),
        ("", None, None),
    ],
)
@pytest.mark.asyncio
async def test_minimax_thinking_switch_overrides_config_per_request(streaming, configured, enabled, expected):
    provider = MiniMaxProvider(api_key="test-key", thinking=configured)
    message = SimpleNamespace(content="answer", reasoning_content="reasoning", tool_calls=[])
    response = SimpleNamespace(
        model=provider.model, usage=None, choices=[SimpleNamespace(message=message)],
    )

    async def chunks():
        yield SimpleNamespace(model=provider.model, usage=None, choices=[SimpleNamespace(delta=message)])

    provider.client.chat.completions.create = AsyncMock(return_value=chunks() if streaming else response)
    messages = [LLMMessage(role="user", content="hello")]
    if streaming:
        result = [chunk async for chunk in provider.chat_stream_response(messages, thinking_enabled=enabled)]
        assert result[-1].response.content == "answer"
        assert result[-1].response.reasoning == "reasoning"
    else:
        result = await provider.chat(messages, thinking_enabled=enabled)
        assert result.content == "answer"
        assert result.reasoning == "reasoning"

    kwargs = provider.client.chat.completions.create.await_args.kwargs
    assert kwargs["extra_body"] == {
        "reasoning_split": True,
        **({"thinking": {"type": expected}} if expected else {}),
    }
    if expected:
        assert kwargs["extra_body"]["thinking"]["type"] in {"adaptive", "disabled"}
    assert provider.thinking == configured


@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize(
    ("content", "details", "answer", "reasoning"),
    [
        ("answer", [{"type": "reasoning.text", "text": "plan"}], "answer", "plan"),
        ("<think>plan</think>\n\nanswer", [], "answer", "plan"),
        ("<mm:think>plan</mm:think>\n\nanswer", [], "answer", "plan"),
        ("</mm:think>answer", [], "answer", ""),
        ("</think>answer", [], "answer", ""),
        ("<mm:think>unfinished", [], "", "unfinished"),
        (" \n<think>unfinished", [], "", "unfinished"),
        ("plain answer", [], "plain answer", ""),
        ("Example: `<think>literal</think>`", [], "Example: `<think>literal</think>`", ""),
        ("<think>plan</think>answer", [{"text": "plan"}], "answer", "plan"),
    ],
)
@pytest.mark.asyncio
async def test_minimax_separates_reasoning_from_answer(streaming, content, details, answer, reasoning):
    provider = MiniMaxProvider(api_key="test-key")
    message = SimpleNamespace(content=content, reasoning_details=details, tool_calls=[])

    async def chunks():
        if details:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                content=None, reasoning_details=details,
            ))])
        # Every delimiter is split across network chunks.
        for char in content:
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=char))])

    response = SimpleNamespace(model=provider.model, usage=None, choices=[SimpleNamespace(message=message)])
    provider.client.chat.completions.create = AsyncMock(return_value=chunks() if streaming else response)
    messages = [LLMMessage(role="user", content="hello")]
    if streaming:
        result = [chunk async for chunk in provider.chat_stream_response(messages, thinking_enabled=True)]
        assert "".join(chunk.text for chunk in result) == answer
        assert "".join(chunk.reasoning for chunk in result) == reasoning
        response = result[-1].response
    else:
        response = await provider.chat(messages, thinking_enabled=True)
    assert response.content == answer
    assert response.reasoning == reasoning


@pytest.mark.asyncio
async def test_minimax_does_not_execute_tool_markup_inside_reasoning():
    provider = MiniMaxProvider(api_key="test-key")
    response = SimpleNamespace(model=provider.model, usage=None, choices=[SimpleNamespace(message=SimpleNamespace(
        content='<think><tool_call><invoke name="echo"><text>wrong</text></invoke></tool_call></think>answer',
        tool_calls=[],
    ))])
    provider.client.chat.completions.create = AsyncMock(return_value=response)
    result = await provider.chat([LLMMessage(role="user", content="hello")], thinking_enabled=True)
    assert result.content == "answer"
    assert result.tool_calls == []
    assert '<invoke name="echo">' in result.reasoning


@pytest.mark.asyncio
@pytest.mark.parametrize("text_tool", [False, True])
async def test_minimax_streams_reasoning_before_answer_across_tool_rounds(engine, text_tool):
    provider = MiniMaxProvider(api_key="test-key")
    reasoning, answers = [], []
    calls = []

    async def create(**kwargs):
        assert kwargs['stream'] is True
        calls.append(kwargs)
        round_number = len(calls)

        async def chunks():
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(
                content=None, reasoning_content=f'plan {round_number}',
            ))])
            assert reasoning[-1] == f'plan {round_number}', 'reasoning must reach the common callback immediately'
            assert answers == []
            if round_number == 1:
                if text_tool:
                    delta = SimpleNamespace(content='<tool_call><invoke name="echo"><text>hello</text></invoke></tool_call>')
                else:
                    delta = SimpleNamespace(content=None, tool_calls=[SimpleNamespace(
                        index=0, id='call_echo', function=SimpleNamespace(name='echo', arguments='{"text":"hello"}'),
                    )])
            else:
                assert any(message['role'] == 'tool' for message in kwargs['messages'])
                delta = SimpleNamespace(content='final answer')
            yield SimpleNamespace(choices=[SimpleNamespace(delta=delta)])
        return chunks()

    provider.client.chat.completions.create = AsyncMock(side_effect=create)
    with patch.object(engine, '_get_provider', return_value=provider):
        result = await engine.process(
            ChatRequest(conversation_id='minimax-live-reasoning', message='Use echo then answer', thinking_enabled=True, stream=True),
            on_token=answers.append, on_reasoning=reasoning.append,
        )
    assert len(calls) == 2
    assert reasoning == ['plan 1', 'plan 2']
    assert ''.join(answers) == 'final answer'
    assert result.response == 'final answer'
    assert result.reasoning == 'plan 1\n\nplan 2'
    assert 'echo' in result.skills_used
    thoughts = [event for event in result.events if event.type == 'model.reasoning']
    assert [event.payload['text'] for event in thoughts] == ['plan 1', 'plan 2']
    assert [event.payload['round'] for event in thoughts] == [1, 2]
    starts = [event for event in result.events if event.type == 'model.started']
    assert [event.payload['model_event_id'] for event in thoughts] == [event.id for event in starts]
    tool_result = next(event for event in result.events if event.type == 'tool.completed')
    assert result.events.index(thoughts[0]) < result.events.index(tool_result) < result.events.index(thoughts[1])


@pytest.mark.parametrize("enabled", [None, False, True])
@pytest.mark.parametrize("model", ["MiniMax-M2.7-highspeed", "MiniMax-M2.5-highspeed"])
def test_other_minimax_models_do_not_receive_thinking_parameter(model, enabled):
    provider = MiniMaxProvider(api_key="test-key", model=model, thinking="enabled")
    assert provider._extra_chat_kwargs(thinking_enabled=enabled) == {}


@pytest.mark.parametrize("enabled", [None, False, True])
@pytest.mark.parametrize(
    ("provider_name", "model", "supported"),
    [("minimax", "MiniMax-M3", True), ("dgx", "spark", True),
     ("minimax", "MiniMax-M2.7-highspeed", False), ("openai", "MiniMax-M3", False)],
)
def test_engine_forwards_thinking_only_to_supported_models(provider_name, model, supported, enabled):
    provider = SimpleNamespace(provider_name=provider_name, model=model)
    request = ChatRequest(conversation_id="thinking", message="hello", thinking_enabled=enabled)
    assert AgentEngine._provider_thinking_kwargs(provider, request) == (
        {"thinking_enabled": enabled} if supported and enabled is not None else {}
    )


def test_extract_minimax_text_tool_calls():
    provider = MiniMaxProvider(api_key="test-key")

    content, tool_calls = provider._extract_text_tool_calls(
        '我再查几条。]<]minimax[>[<tool_call>\n'
        ']<]minimax[>[<invoke name="search">]<]minimax[>[<query>字节 AI 新闻</query>'
        ']<]minimax[>[<sources>web</sources>]<]minimax[>[<limit>6</limit>'
        ']<]minimax[>[</invoke>\n'
        ']<]minimax[>[</tool_call>'
    )

    assert content == "我再查几条。"
    assert len(tool_calls) == 1
    assert tool_calls[0].name == "search"
    assert tool_calls[0].arguments == {
        "query": "字节 AI 新闻",
        "sources": "web",
        "limit": 6,
    }


def test_minimax_image_response_normalizes_url_and_base64():
    request = ImageGenerationRequest(
        prompt="a small studio product shot",
        aspect_ratio="1:1",
        response_format="url",
    )

    response = ImageGenerationResponse.from_minimax(
        {
            "id": "img_123",
            "data": {
                "image_urls": ["https://example.com/image.png"],
                "image_base64": ["data:image/png;base64,aGVsbG8="],
            },
        },
        request,
        model="image-01",
    )

    assert response.id == "img_123"
    assert response.provider == "minimax"
    assert response.images[0].url == "https://example.com/image.png"
    assert response.images[1].base64 == "aGVsbG8="


@pytest.mark.asyncio
async def test_minimax_image_request_normalizes_subject_reference():
    client = MiniMaxAIGCClient(api_key="test-key")

    with patch.object(
        client,
        "_post_json",
        new=AsyncMock(return_value={"base_resp": {"status_code": 0}}),
    ) as mock_post:
        await client.generate_image(
            "turn this person into a chibi avatar",
            extra={
                "subject_reference": [
                    {
                        "type": "image",
                        "image": "data:image/png;base64,ZmFrZQ==",
                        "name": "legacy-ref.png",
                    }
                ]
            },
        )

    payload = mock_post.await_args.args[1]
    assert payload["subject_reference"] == [
        {
            "type": "character",
            "image_file": "data:image/png;base64,ZmFrZQ==",
        }
    ]


@pytest.mark.asyncio
async def test_minimax_post_json_retries_remote_disconnect():
    class FakeAsyncClient:
        def __init__(self):
            self.post = AsyncMock(
                side_effect=[
                    httpx.RemoteProtocolError("Server disconnected without sending a response."),
                    httpx.Response(
                        200,
                        request=httpx.Request(
                            "POST",
                            "https://api.minimaxi.com/v1/image_generation",
                        ),
                        json={
                            "id": "img_retry",
                            "data": {"image_urls": ["https://example.com/retry.png"]},
                            "base_resp": {"status_code": 0, "status_msg": "success"},
                        },
                    ),
                ]
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    fake_client = FakeAsyncClient()
    client = MiniMaxAIGCClient(api_key="test-key")

    with patch("agent.aigc.minimax_client.httpx.AsyncClient", return_value=fake_client), patch(
        "agent.aigc.minimax_client.asyncio.sleep",
        new=AsyncMock(),
    ):
        data = await client._post_json("/v1/image_generation", {"model": "image-01"})

    assert data["id"] == "img_retry"
    assert fake_client.post.await_count == 2


@pytest.mark.asyncio
async def test_minimax_post_json_retries_remote_disconnect_five_times():
    class FakeAsyncClient:
        def __init__(self):
            self.post = AsyncMock(
                side_effect=[
                    httpx.RemoteProtocolError("Server disconnected without sending a response.")
                    for _ in range(5)
                ]
            )

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return False

    fake_client = FakeAsyncClient()
    client = MiniMaxAIGCClient(api_key="test-key")

    with patch("agent.aigc.minimax_client.httpx.AsyncClient", return_value=fake_client), patch(
        "agent.aigc.minimax_client.asyncio.sleep",
        new=AsyncMock(),
    ), pytest.raises(httpx.RemoteProtocolError):
        await client._post_json("/v1/image_generation", {"model": "image-01"})

    assert fake_client.post.await_count == 5
