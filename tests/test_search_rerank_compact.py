import json
from unittest.mock import AsyncMock

import pytest

from agent.config import RuntimeConfig, runtime_config
from agent.llm.base import LLMResponse
from agent.search import SearchResult, SearchService, StaticSearchProvider
from agent.search.service import LLMSearchReranker


def make_reranker(payload):
    provider = AsyncMock()
    provider.chat.return_value = LLMResponse(
        content=json.dumps(payload), model="fake", usage={"input": 50, "output": 8},
    )
    return LLMSearchReranker(provider, name="fake", min_score=0.5), provider


@pytest.mark.asyncio
async def test_compact_scores_preserve_order_threshold_and_candidate_evidence():
    reranker, provider = make_reranker({"scores": [0.5, 0.9, 0.2, 0.9]})
    results = [SearchResult(title=f"Dify RAG {i}", snippet="工程实践评测", url=f"https://example.com/{i}") for i in range(4)]
    selected, metadata = await reranker.rerank("Dify RAG 工程实践", results, limit=3)
    assert selected == [results[1], results[3], results[0]]
    assert metadata["judged_count"] == 4
    assert metadata["kept_count"] == 3
    assert metadata["usage"]["output"] == 8
    assert [d["index"] for d in metadata["decisions"]] == [2, 4, 1, 3]
    prompt = "\n".join(m.content for m in provider.chat.call_args.args[0])
    assert '"scores"' in prompt
    assert '"reason":"short reason"' not in prompt
    assert all(r.title in prompt and r.snippet in prompt and r.url in prompt for r in results)


@pytest.mark.asyncio
@pytest.mark.parametrize("scores", [None, {}, [], [0.9], [0.9, 0.8, 0.7], [True, 0.8], ["0.9", 0.8], [None, 0.8], [float("nan"), 0.8], [float("inf"), 0.8], [-0.1, 0.8], [1.1, 0.8]])
async def test_invalid_score_vectors_fail_instead_of_misaligning_results(scores):
    reranker, _ = make_reranker({"scores": scores})
    with pytest.raises(ValueError, match="scores"):
        await reranker.rerank("agent", [SearchResult(title="Agent A"), SearchResult(title="Agent B")], limit=2)


@pytest.mark.asyncio
async def test_compact_scores_reject_all_irrelevant_candidates():
    reranker, _ = make_reranker({"scores": [0.1, 0.49]})
    selected, metadata = await reranker.rerank("agent", [SearchResult(title="A"), SearchResult(title="B")], limit=2)
    assert selected == []
    assert metadata["judged_count"] == 2
    assert metadata["status"] == "completed"


@pytest.mark.asyncio
async def test_invalid_vector_falls_back_to_local_ranking_in_search():
    reranker, _ = make_reranker({"scores": []})
    service = SearchService(
        [StaticSearchProvider(documents=[{"title": "Agent search", "url": "https://example.com/agent"}])],
        reranker=reranker,
    )
    results = await service.search("agent search", limit=1, include_images=False)
    assert results[0].title == "Agent search"
    node = next(n for n in service.last_trace_nodes if n["node"] == "llm_rerank")
    assert node["status"] == "partial"
    assert "scores" in node["error"]


@pytest.mark.asyncio
async def test_legacy_rerank_response_still_works():
    reranker, _ = make_reranker({"results": [{"index": 1, "score": 0.8, "reason": "relevant"}]})
    result = SearchResult(title="Agent")
    selected, metadata = await reranker.rerank("agent", [result], limit=1)
    assert selected == [result]
    assert metadata["decisions"][0]["reason"] == "relevant"


def test_duckduckgo_is_disabled_by_default():
    assert RuntimeConfig().get("search.web.enabled") == "false"


@pytest.mark.parametrize("enabled", ["false", "true"])
def test_disabling_duckduckgo_preserves_other_web_sources_and_alias(monkeypatch, enabled):
    monkeypatch.setattr(runtime_config, "_data", {
        "search.web.enabled": enabled,
        "search.doubao.enabled": "true", "llm.doubao.api_key": "fake-key",
        "search.minimax.enabled": "false", "search.bing.enabled": "true",
        "search.rewrite.enabled": "false", "search.rerank.enabled": "false",
    })
    service = SearchService.from_runtime_config()
    assert ("web" in service.provider_names) == (enabled == "true")
    assert "doubao-search" in service.provider_names
    assert "bing-rss" in service.provider_names
    selected, generic_web = service._normalize_sources(["web"])
    assert generic_web
    assert "doubao-search" in selected
    assert "bing-rss" in selected
