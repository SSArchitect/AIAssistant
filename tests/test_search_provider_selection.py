import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock, call

import pytest

from agent.config import runtime_config
from agent.llm.base import LLMResponse
from agent.search import SearchResult, SearchService
from agent.search.service import (
    BingRSSSearchProvider,
    DoubaoSearchProvider,
    MiniMaxMCPSearchProvider,
)
from agent.skills.builtin.search import SearchSkill


@pytest.fixture
def selected_search_providers(monkeypatch):
    config = {
        "llm.default_provider": "bailian:qwen3.8-max",
        "llm.creation.default_model": "bailian:qwen3.8-flash",
        # Older deployments use stage-specific overrides; newer ones inherit creation.
        "search.rewrite.provider": "bailian:qwen3.8-flash",
        "search.rerank.provider": "bailian:qwen3.8-flash",
        "search.bailian.enabled": "true",
        "search.bailian.api_key": "unused-search-key",
        "search.minimax.enabled": "true",
        "search.minimax.api_key": "unused-minimax-search-key",
        "llm.minimax.api_key": "unused-minimax-model-key",
        "search.doubao.enabled": "true",
        "llm.doubao.api_key": "test-doubao-key",
        "search.bing.enabled": "true",
        "search.web.enabled": "false",
        "search.rewrite.enabled": "true",
        "search.rerank.enabled": "true",
        "search.retry.attempts": "1",
        "search.retry.delay_seconds": "0",
    }
    # Replace and restore the in-memory map; never persist or sync test settings.
    monkeypatch.setattr(runtime_config, "_data", config)
    overrides_path = (Path(__file__).resolve().parents[1]
                      / "ops/config/search-sources-20261030.json")
    overrides = json.loads(overrides_path.read_text(encoding="utf-8"))
    assert overrides == {
        "search.minimax.enabled": "false",
        "search.bailian.enabled": "false",
    }
    runtime_config.update(overrides)
    rewriter = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(
        content='{"queries":["agent search","智能体 搜索"]}',
    )))
    reranker = SimpleNamespace(chat=AsyncMock(return_value=LLMResponse(
        content='{"scores":[0.9,0.8]}',
    )))
    factory = Mock(side_effect=[rewriter, reranker])
    monkeypatch.setattr("agent.llm.factory.create_provider", factory)

    calls = []

    async def search(provider, query, *, limit=5):
        calls.append((provider.name, query))
        return [SearchResult(
            title=f"Agent search {provider.name}",
            snippet="Agent search retrieval and ranking.",
            url=f"https://example.com/{provider.name}",
            source=provider.name,
        )]

    monkeypatch.setattr(DoubaoSearchProvider, "search", search)
    monkeypatch.setattr(BingRSSSearchProvider, "search", search)
    disabled_providers = [MiniMaxMCPSearchProvider]
    # The production adapter is not present in older repository snapshots.
    if importlib.util.find_spec("agent.search.bailian") is not None:
        from agent.search.bailian import BailianSearchProvider

        disabled_providers.append(BailianSearchProvider)
    disabled_searches = []
    for provider in disabled_providers:
        disabled = AsyncMock(side_effect=AssertionError("Disabled search source was called"))
        monkeypatch.setattr(provider, "search", disabled)
        disabled_searches.append(disabled)

    yield SimpleNamespace(
        config=config, factory=factory, rewriter=rewriter,
        reranker=reranker, calls=calls,
    )
    for disabled in disabled_searches:
        disabled.assert_not_called()


def test_disabled_search_sources_keep_auxiliary_model_calls(selected_search_providers):
    service = SearchService.from_runtime_config()

    assert service.provider_names == ["doubao-search", "bing-rss"]
    assert selected_search_providers.factory.call_args_list == [
        call("bailian:qwen3.8-flash"), call("bailian:qwen3.8-flash"),
    ]
    assert service._query_rewriter.name == "llm:bailian:qwen3.8-flash"
    assert service._reranker.name == "llm:bailian:qwen3.8-flash"


@pytest.mark.asyncio
@pytest.mark.parametrize("sources", [
    None,
    ["web"],
    ["web", "minimax-mcp", "bailian-search"],
])
async def test_default_and_web_search_use_only_enabled_sources(
    selected_search_providers, sources,
):
    result = await SearchSkill().execute(
        query="agent search", sources=sources, limit=2, include_images=False,
    )

    assert result.success
    assert {item["source"] for item in result.data["results"]} == {
        "doubao-search", "bing-rss",
    }
    assert {source for source, _ in selected_search_providers.calls} == {
        "doubao-search", "bing-rss",
    }
    nodes = {node["node"]: node for node in result.data["search_trace"]}
    assert nodes["recall"]["providers"] == ["doubao-search", "bing-rss"]
    for stage in ("query_rewrite", "llm_rerank"):
        assert nodes[stage]["status"] == "completed"
        assert nodes[stage]["provider"] == "llm:bailian:qwen3.8-flash"
    selected_search_providers.rewriter.chat.assert_awaited_once()
    selected_search_providers.reranker.chat.assert_awaited_once()
    assert runtime_config.get("llm.default_provider") == "bailian:qwen3.8-max"
    assert runtime_config.get("llm.creation.default_model") == "bailian:qwen3.8-flash"


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["minimax-mcp", "bailian-search"])
async def test_explicit_disabled_source_returns_empty_without_other_source_fallback(
    selected_search_providers, source,
):
    result = await SearchSkill().execute(
        query="agent search", sources=[source], include_images=False,
    )

    # Existing explicit-source semantics: no matching provider means empty results.
    assert result.success
    assert result.data["results"] == []
    assert selected_search_providers.calls == []
    recall = next(node for node in result.data["search_trace"] if node["node"] == "recall")
    assert recall["providers"] == []
    assert recall["attempts"] == []
    selected_search_providers.reranker.chat.assert_not_awaited()


@pytest.mark.asyncio
async def test_missing_remaining_provider_key_keeps_bing_available(selected_search_providers):
    selected_search_providers.config["llm.doubao.api_key"] = ""
    selected_search_providers.reranker.chat.return_value = LLMResponse(content='{"scores":[0.9]}')

    result = await SearchSkill().execute(
        query="agent search", sources=["web"], limit=1, include_images=False,
    )

    assert result.success
    assert result.data["sources"] == ["bing-rss"]
    assert [item["source"] for item in result.data["results"]] == ["bing-rss"]
    assert {source for source, _ in selected_search_providers.calls} == {"bing-rss"}


@pytest.mark.asyncio
@pytest.mark.parametrize("sources", [None, ["web"]])
async def test_disabling_all_sources_reports_unavailable_without_search_or_model_calls(
    selected_search_providers, sources,
):
    selected_search_providers.config.update({
        "search.doubao.enabled": "false",
        "search.bing.enabled": "false",
    })

    result = await SearchSkill().execute(
        query="agent search", sources=sources, include_images=False,
    )

    assert not result.success
    assert "No search providers configured" in result.error
    assert selected_search_providers.calls == []
    selected_search_providers.rewriter.chat.assert_not_awaited()
    selected_search_providers.reranker.chat.assert_not_awaited()
