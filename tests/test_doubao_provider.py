import json
from unittest.mock import patch

import httpx
import openai
import pytest

from agent.config import RuntimeConfig, Settings, runtime_config
from agent.llm.base import LLMMessage, RateLimitError, ToolDefinition
from agent.llm.doubao_provider import DoubaoProvider, is_agent_plan_url
from agent.llm.factory import create_provider
from agent.main import ListModelsRequest, ValidateProviderRequest, list_models, validate_provider

PLAN_URL = "https://ark.cn-beijing.volces.com/api/plan/v3"


@pytest.fixture
def plan_config(monkeypatch):
    monkeypatch.setattr(runtime_config, "_data", {
        "llm.default_provider": "doubao",
        "llm.doubao.api_key": "test-key",
        "llm.doubao.base_url": PLAN_URL,
        "llm.doubao.model": "doubao-seed-2.1-turbo",
    })


def test_environment_url_reaches_runtime(monkeypatch):
    monkeypatch.setenv("DOUBAO_BASE_URL", PLAN_URL)
    with patch("agent.config.settings", Settings(_env_file=None)):
        assert RuntimeConfig().doubao_base_url == PLAN_URL


@pytest.mark.parametrize("url", [PLAN_URL + "/", "https://ark.cn-beijing.volces.com/api/v3"])
def test_factory_uses_configured_url_and_model_override(plan_config, url):
    runtime_config.update({"llm.doubao.base_url": url})
    provider = create_provider("doubao:glm-5.3")
    assert str(provider.client.base_url) == url.rstrip("/") + "/"
    assert provider.model == "glm-5.3"
    assert provider.provider_name == "doubao"


@pytest.mark.asyncio
async def test_plan_catalog_does_not_request_nonexistent_models_endpoint(plan_config):
    with patch("openai.AsyncOpenAI", side_effect=AssertionError("No models endpoint on Plan")):
        result = await list_models(ListModelsRequest(provider="doubao"))
    ids = [model["id"] for model in result["models"]]
    assert result["success"] is True
    assert "doubao-seed-2.1-turbo" in ids
    assert {"glm-5.3", "deepseek-v4-pro", "kimi-k3", "minimax-m3"} <= set(ids)
    assert len(ids) == len(set(ids)) == 11
    assert not any("seedream" in model or "seedance" in model for model in ids)


@pytest.mark.asyncio
async def test_catalog_does_not_claim_credentials_are_verified(plan_config):
    result = await validate_provider(ValidateProviderRequest(provider="doubao"))
    assert result["success"] is False
    assert result["status"] == "pending"
    assert result["model_count"] == 11


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["", " "])
async def test_missing_key_cannot_validate_or_list_models(plan_config, key):
    runtime_config.update({"llm.doubao.api_key": key})
    result = await list_models(ListModelsRequest(provider="doubao"))
    assert result["success"] is False
    assert result["models"] == []
    result = await validate_provider(ValidateProviderRequest(provider="doubao"))
    assert result["status"] == "missing"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 404])
async def test_standard_endpoint_keeps_remote_discovery_and_errors(plan_config, status):
    runtime_config.update({"llm.doubao.base_url": "https://ark.cn-beijing.volces.com/api/v3"})

    def handler(request):
        assert str(request.url) == "https://ark.cn-beijing.volces.com/api/v3/models"
        return httpx.Response(status, json={"data": [{"id": "remote-model"}]})

    sdk = openai.AsyncOpenAI(api_key="test-key", base_url=runtime_config.doubao_base_url,
                             max_retries=0, http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    with patch("openai.AsyncOpenAI", return_value=sdk):
        result = await list_models(ListModelsRequest(provider="doubao"))
    await sdk.close()
    assert result["success"] is (status == 200)
    assert result["models"] == ([{"id": "remote-model", "name": "remote-model"}] if status == 200 else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [200, 401, 429])
async def test_chat_uses_plan_auth_model_and_tools(plan_config, status):
    provider = create_provider("doubao")

    def handler(request):
        assert str(request.url) == PLAN_URL + "/chat/completions"
        assert request.headers["authorization"] == "Bearer test-key"
        payload = json.loads(request.content)
        assert payload["model"] == "doubao-seed-2.1-turbo"
        assert payload["tools"][0]["function"]["name"] == "echo"
        return httpx.Response(status, json={
            "model": payload["model"], "choices": [{"message": {
                "role": "assistant", "content": "OK", "tool_calls": [{
                    "id": "call-1", "type": "function",
                    "function": {"name": "echo", "arguments": '{"text":"hello"}'},
                }],
            }}], "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
        })

    await provider.client.close()
    provider.client = openai.AsyncOpenAI(api_key="test-key", base_url=PLAN_URL, max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        args = ([LLMMessage(role="user", content="hello")],)
        kwargs = {"tools": [ToolDefinition(name="echo", description="Echo", parameters={"type": "object"})]}
        if status == 200:
            response = await provider.chat(*args, **kwargs)
            assert response.content == "OK"
            assert response.tool_calls[0].arguments == {"text": "hello"}
        else:
            with pytest.raises(openai.AuthenticationError if status == 401 else RateLimitError):
                await provider.chat(*args, **kwargs)
    finally:
        await provider.client.close()


def test_provider_rejects_blank_key():
    with pytest.raises(ValueError, match="API key not configured"):
        DoubaoProvider(api_key=" ")


@pytest.mark.asyncio
@pytest.mark.parametrize("streaming", [False, True])
@pytest.mark.parametrize("status", [200, 400])
async def test_plan_reference_images_and_tools_preserved_on_wire(plan_config, streaming, status):
    provider = create_provider()
    parts = [
        {"type": "text", "text": "Compare both reference images, then call report_visual."},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,aW1hZ2Ux"}},
        {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,aW1hZ2Uy"}},
    ]
    tool = ToolDefinition(name="report_visual", description="Report the comparison.",
                          parameters={"type": "object", "properties": {}})
    calls = []

    def handler(request):
        payload = json.loads(request.content)
        calls.append(payload)
        assert payload["model"] == "doubao-seed-2.1-turbo"
        assert payload["messages"] == [{"role": "user", "content": parts}]
        assert payload["tools"][0]["function"]["name"] == "report_visual"
        if status == 400:
            return httpx.Response(400, json={"error": {
                "code": "InvalidParameter", "message": "Model only support text input",
                "type": "BadRequest",
            }})
        tool_call = {"id": "visual-1", "type": "function", "function": {
            "name": "report_visual", "arguments": "{}",
        }}
        if streaming:
            chunk = {"model": provider.model, "choices": [{"delta": {
                "tool_calls": [{"index": 0, **tool_call}],
            }}]}
            return httpx.Response(200, text="data: " + json.dumps(chunk) + "\n\ndata: [DONE]\n\n",
                                  headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"model": provider.model, "choices": [{"message": {
            "role": "assistant", "content": "", "tool_calls": [tool_call],
        }}]})

    await provider.client.close()
    provider.client = openai.AsyncOpenAI(
        api_key="test-key", base_url=PLAN_URL, max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    async def invoke():
        messages = [LLMMessage(role="user", content=parts)]
        if streaming:
            chunks = [chunk async for chunk in provider.chat_stream_response(messages, tools=[tool])]
            return chunks[-1].response
        return await provider.chat(messages, tools=[tool])

    try:
        if status == 400:
            with pytest.raises(openai.BadRequestError, match="Model only support text input"):
                await invoke()
        else:
            response = await invoke()
            assert response.tool_calls[0].name == "report_visual"
            assert response.tool_calls[0].arguments == {}
        # A rejected image request must not silently retry after discarding the images.
        assert len(calls) == 1
    finally:
        await provider.client.close()


@pytest.mark.parametrize("url,expected", [
    (PLAN_URL, True), (PLAN_URL + "/", True),
    ("https://example.com/api/plan/v3", False),
    (PLAN_URL + "/models", False), (PLAN_URL + "?proxy=1", False),
])
def test_catalog_only_applies_to_official_plan_endpoint(url, expected):
    assert is_agent_plan_url(url) is expected


@pytest.mark.asyncio
async def test_plan_stream_preserves_reasoning_and_answer(plan_config):
    provider = create_provider("doubao")

    def handler(request):
        assert str(request.url) == PLAN_URL + "/chat/completions"
        assert json.loads(request.content)["stream"] is True
        chunks = [
            {"choices": [{"delta": {"reasoning_content": "plan"}}]},
            {"choices": [{"delta": {"content": "OK"}}]},
        ]
        content = "".join("data: " + json.dumps(chunk) + "\n\n" for chunk in chunks) + "data: [DONE]\n\n"
        return httpx.Response(200, text=content, headers={"content-type": "text/event-stream"})

    await provider.client.close()
    provider.client = openai.AsyncOpenAI(api_key="test-key", base_url=PLAN_URL,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        chunks = [chunk async for chunk in provider.chat_stream_response([LLMMessage(role="user", content="hello")])]
        assert "".join(chunk.text for chunk in chunks) == "OK"
        assert chunks[-1].response.reasoning == "plan"
        assert chunks[-1].response.content == "OK"
    finally:
        await provider.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
@pytest.mark.parametrize('finish_reason', ['stop', 'length', 'content_filter'])
async def test_plan_response_preserves_finish_reason(plan_config, streaming, finish_reason):
    """A capped JSON plan must not look like a completed model response."""
    provider = create_provider()
    def handler(request):
        if streaming:
            chunks = [dict(choices=[dict(delta=dict(content='{\"plan\":'), finish_reason=None)]),
                      dict(choices=[dict(delta={}, finish_reason=finish_reason)])]
            return httpx.Response(200, text=''.join('data: '+json.dumps(c)+'\n\n' for c in chunks)+'data: [DONE]\n\n',
                                  headers={'content-type':'text/event-stream'})
        return httpx.Response(200, json=dict(model=provider.model, choices=[dict(
            message=dict(role='assistant', content='{\"plan\":'), finish_reason=finish_reason)]))
    await provider.client.close()
    provider.client = openai.AsyncOpenAI(api_key='test-key', base_url=PLAN_URL,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    try:
        messages = [LLMMessage(role='user',content='六个镜头的完整方案')]
        if streaming:
            chunks = [c async for c in provider.chat_stream_response(messages)]
            response = chunks[-1].response
        else:
            response = await provider.chat(messages)
        assert response.finish_reason == finish_reason
        assert response.content == '{\"plan\":'
    finally:
        await provider.client.close()
