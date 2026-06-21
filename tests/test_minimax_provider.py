from unittest.mock import AsyncMock, patch

import httpx
import pytest

from agent.aigc.minimax_client import MiniMaxAIGCClient
from agent.llm.minimax_provider import MiniMaxProvider
from agent.schemas.aigc import ImageGenerationRequest, ImageGenerationResponse


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
