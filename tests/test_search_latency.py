import asyncio
import json

import httpx
import openai
import pytest

from agent.llm.base import LLMMessage, LLMResponse
from agent.llm.doubao_provider import DoubaoProvider
from agent.search import SearchResult, SearchService, StaticSearchProvider
from agent.search.service import LLMSearchQueryRewriter, LLMSearchReranker


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["rewrite", "rerank"])
async def test_search_nodes_disable_doubao_thinking_on_the_wire(stage):
    provider = DoubaoProvider(api_key="test-key", model="doubao-seed-2.1-turbo")

    def handle(request):
        body = json.loads(request.content)
        assert body["thinking"] == {"type": "disabled"}
        assert body["temperature"] == 0
        payload = {"queries": ["agent search"]} if stage == "rewrite" else {
            "results": [{"index": 1, "score": 0.9, "reason": "relevant"}],
        }
        return httpx.Response(200, json={
            "model": provider.model,
            "choices": [{"message": {"role": "assistant", "content": json.dumps(payload)}}],
        })

    await provider.client.close()
    provider.client = openai.AsyncOpenAI(
        api_key="test-key", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        if stage == "rewrite":
            result = await LLMSearchQueryRewriter(provider, name="doubao").rewrite("agent search", max_queries=2)
            assert result["status"] == "completed"
        else:
            candidates = [SearchResult(title="Agent search", url="https://example.com/search")]
            selected, _ = await LLMSearchReranker(provider, name="doubao").rerank("agent search", candidates, limit=1)
            assert selected == candidates
    finally:
        await provider.client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [None, False, True])
@pytest.mark.parametrize("streaming", [False, True])
async def test_doubao_thinking_override_is_explicit_and_supports_streaming(enabled, streaming):
    provider = DoubaoProvider(api_key="test-key")

    def handle(request):
        body = json.loads(request.content)
        if enabled is None:
            assert "thinking" not in body
        else:
            assert body["thinking"] == {"type": "enabled" if enabled else "disabled"}
        if streaming:
            return httpx.Response(200, text='data: {"choices":[{"delta":{"content":"OK"}}]}\n\ndata: [DONE]\n\n', headers={"content-type": "text/event-stream"})
        return httpx.Response(200, json={"choices": [{"message": {"role": "assistant", "content": "OK"}}], "model": "test"})

    await provider.client.close()
    provider.client = openai.AsyncOpenAI(
        api_key="test-key", max_retries=0,
        http_client=httpx.AsyncClient(transport=httpx.MockTransport(handle)),
    )
    try:
        messages = [LLMMessage(role="user", content="hello")]
        if streaming:
            assert "".join([c async for c in provider.chat_stream(messages, thinking_enabled=enabled)]) == "OK"
        else:
            assert (await provider.chat(messages, thinking_enabled=enabled)).content == "OK"
    finally:
        await provider.client.close()


@pytest.mark.asyncio
async def test_search_keeps_legacy_provider_signature_compatible():
    class LegacyProvider:
        async def chat(self, messages, temperature=0.7):
            return LLMResponse(content='{"queries":["agent search"]}')

    result = await LLMSearchQueryRewriter(LegacyProvider(), name="legacy").rewrite("agent search", max_queries=2)
    assert result["status"] == "completed"


@pytest.mark.asyncio
async def test_search_timeout_traces_have_error_and_stage_durations():
    class SlowProvider:
        async def chat(self, messages, temperature=0.7):
            await asyncio.sleep(10)

    documents = [{"title": "Agent search", "snippet": "agent search details", "url": "https://example.com/search"}]
    service = SearchService(
        [StaticSearchProvider(documents=documents)],
        query_rewriter=LLMSearchQueryRewriter(SlowProvider(), name="slow", timeout_seconds=0.1),
        reranker=LLMSearchReranker(SlowProvider(), name="slow", timeout_seconds=0.1),
    )
    assert await service.search("agent search", limit=1)
    nodes = {n["node"]: n for n in service.last_trace_nodes}
    for stage in ("query_rewrite", "llm_rerank"):
        assert nodes[stage]["status"] == "partial"
        assert "Timeout" in nodes[stage]["error"]
        assert nodes[stage]["duration_ms"] >= 50
    assert nodes["recall"]["duration_ms"] >= 0


@pytest.mark.asyncio
async def test_search_skipped_rewrite_reports_timing_without_calling_model():
    class UnexpectedRewriter:
        async def rewrite(self, *args, **kwargs):
            pytest.fail("Caller disabled rewrite")

    service = SearchService([], query_rewriter=UnexpectedRewriter())
    assert await service.search("agent search", rewrite_query=False) == []
    node = service.last_trace_nodes[0]
    assert node["status"] == "skipped"
    assert node["duration_ms"] >= 0
