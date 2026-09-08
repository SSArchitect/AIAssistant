import json

import httpx
import pytest

from agent.config import RuntimeConfig, runtime_config
from agent.search import DoubaoSearchProvider, SearchResult, SearchService
from agent.skills.builtin.search import SearchSkill


@pytest.fixture
def search_config(monkeypatch):
    monkeypatch.setattr(runtime_config, "_data", {
        "llm.doubao.api_key": "existing-volcengine-key",
        "llm.doubao.base_url": "https://ark.cn-beijing.volces.com/api/plan/v3",
        "search.minimax.enabled": "false",
        "search.bing.enabled": "false",
        "search.web.enabled": "false",
        "search.rewrite.enabled": "false",
        "search.rerank.enabled": "false",
    })
    return runtime_config


def custom_payload():
    return {
        "ResponseMetadata": {"RequestId": "request-123"},
        "Result": {"WebResults": [{
            "Title": "Agent search documentation",
            "Url": "https://example.com/search",
            "Summary": "Agent search detailed summary " * 60,
            "Snippet": "Short listing text",
            "Content": "Unopened full content",
            "SiteName": "Example",
            "PublishTime": "2026-09-08T00:00:00Z",
            "AuthInfoLevel": 1,
            "RankScore": 0.9,
            "InlineImages": [{"ImageUrl": "https://example.com/image.png"}],
        }]},
    }


@pytest.mark.asyncio
async def test_custom_request_and_summary_mapping():
    def handle(request):
        assert request.method == "POST"
        assert str(request.url) == "https://open.feedcoopapi.com/search_api/web_search"
        assert request.headers["Authorization"] == "Bearer existing-key"
        assert request.headers["Content-Type"] == "application/json"
        assert json.loads(request.content) == {
            "Query": "agent search", "SearchType": "web", "Count": 2,
            "Filter": {"NeedUrl": True},
        }
        return httpx.Response(200, json=custom_payload())

    provider = DoubaoSearchProvider(api_key="existing-key", transport=httpx.MockTransport(handle))
    results = await provider.search(" agent search ", limit=2)
    assert len(results) == 1
    item = results[0]
    assert item.source == "doubao-search"
    assert item.snippet == custom_payload()["Result"]["WebResults"][0]["Summary"][:900]
    assert item.url == "https://example.com/search"
    assert item.image_url == "https://example.com/image.png"
    assert item.metadata["published_at"] == "2026-09-08T00:00:00Z"
    assert item.metadata["site_name"] == "Example"
    assert item.metadata["request_id"] == "request-123"
    assert "page" not in item.metadata
    assert "Unopened full content" not in item.model_dump_json()


@pytest.mark.asyncio
async def test_global_request_and_snippet_mapping():
    def handle(request):
        assert str(request.url) == "https://open.feedcoopapi.com/search_api/global_search"
        assert json.loads(request.content) == {
            "Query": "agent search", "SearchType": "web", "DocCount": 3,
            "MaxSnippetLength": 500,
        }
        return httpx.Response(200, json={
            "ResponseMetadata": {"RequestId": "global-123"},
            "Result": {"ErrorCode": 0, "ErrorMsg": "", "Documents": [{
                "Title": "Agent search", "Url": "https://example.com/global",
                "Rank": 0,
                "Snippet": [
                    {"Type": "text", "Text": "First passage"},
                    {"Type": "image", "Image": {"ImageUrl": "https://example.com/global.png"}},
                    {"Type": "text", "Text": "Second passage"},
                ],
                "DocumentInfo": {"PublishTime": "2026-09-08", "Filetype": "pdf"},
                "HostInfo": {"Hostname": "Example", "AuthorityLevel": "very_high"},
            }]},
        })

    results = await DoubaoSearchProvider(
        api_key="key", edition="global", transport=httpx.MockTransport(handle),
    ).search("agent search", limit=3)
    assert results[0].snippet == "First passage\nSecond passage"
    assert results[0].image_url == "https://example.com/global.png"
    assert results[0].metadata["published_at"] == "2026-09-08"
    assert results[0].metadata["edition"] == "global"
    assert results[0].metadata["authority"] == "very_high"
    assert "page" not in results[0].metadata


@pytest.mark.asyncio
@pytest.mark.parametrize("edition,field,maximum", [("custom", "Count", 50), ("global", "DocCount", 20)])
async def test_query_and_result_limits(edition, field, maximum):
    def handle(request):
        body = json.loads(request.content)
        assert len(body["Query"]) == 100
        assert body[field] == maximum
        key = "WebResults" if edition == "custom" else "Documents"
        return httpx.Response(200, json={"Result": {key: [
            {"Title": str(i), "Url": f"https://example.com/{i}"} for i in range(60)
        ]}})

    results = await DoubaoSearchProvider(
        api_key="key", edition=edition, transport=httpx.MockTransport(handle),
    ).search("豆" * 120, limit=100)
    assert len(results) == maximum


@pytest.mark.asyncio
@pytest.mark.parametrize("edition,key", [("custom", "WebResults"), ("global", "Documents")])
async def test_empty_and_invalid_items(edition, key):
    def handle(request):
        return httpx.Response(200, json={"Result": {key: [
            None, "bad", {}, {"Title": "No URL"}, {"Url": "javascript:alert(1)"},
            {"Url": "http://127.0.0.1/private"},
            {"Url": "https://example.com/valid", "Snippet": None},
        ]}})

    results = await DoubaoSearchProvider(
        api_key="key", edition=edition, transport=httpx.MockTransport(handle),
    ).search("agent search", limit=1)
    assert len(results) == 1
    assert results[0].title == "https://example.com/valid"
    assert results[0].snippet == ""


@pytest.mark.asyncio
@pytest.mark.parametrize("payload", [
    {"ResponseMetadata": {"Error": {"Code": "InvalidApiKey", "Message": "secret-key"}}},
    {"Result": {"ErrorCode": 100013, "ErrorMsg": "secret-key"}},
    [], {}, {"Result": None}, {"Result": {"WebResults": "broken"}},
])
async def test_api_and_malformed_response_errors_do_not_leak_key(payload):
    provider = DoubaoSearchProvider(
        api_key="secret-key",
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    with pytest.raises(ValueError) as error:
        await provider.search("agent search")
    assert "secret-key" not in str(error.value)


@pytest.mark.asyncio
@pytest.mark.parametrize("edition,key", [("custom", "WebResults"), ("global", "Documents")])
@pytest.mark.parametrize("items", [None, []])
async def test_no_matches_is_success(edition, key, items):
    provider = DoubaoSearchProvider(
        api_key="key", edition=edition,
        transport=httpx.MockTransport(lambda _: httpx.Response(200, json={"Result": {key: items}})),
    )
    assert await provider.search("agent search") == []


@pytest.mark.asyncio
async def test_custom_falls_back_to_listing_snippet():
    payload = custom_payload()
    payload["Result"]["WebResults"][0].pop("Summary")
    provider = DoubaoSearchProvider(
        api_key="key", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)),
    )
    assert (await provider.search("agent search"))[0].snippet == "Short listing text"


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_errors(status):
    provider = DoubaoSearchProvider(
        api_key="key", transport=httpx.MockTransport(lambda _: httpx.Response(status)),
    )
    with pytest.raises(httpx.HTTPStatusError):
        await provider.search("agent search")


@pytest.mark.asyncio
async def test_timeout_propagates():
    def handle(request):
        raise httpx.ReadTimeout("search timed out", request=request)
    with pytest.raises(httpx.ReadTimeout):
        await DoubaoSearchProvider(api_key="key", transport=httpx.MockTransport(handle)).search("agent search")


@pytest.mark.asyncio
async def test_empty_query_and_nonpositive_limit_do_not_request():
    def handle(request):
        pytest.fail("Empty search must not issue a request")
    provider = DoubaoSearchProvider(api_key="key", transport=httpx.MockTransport(handle))
    assert await provider.search(" ") == []
    assert await provider.search("agent", limit=0) == []
    assert await provider.search("agent", limit=-1) == []
    with pytest.raises(ValueError, match="API key"):
        await DoubaoSearchProvider(api_key="").search("agent")
    with pytest.raises(ValueError, match="edition"):
        DoubaoSearchProvider(api_key="key", edition="unknown")


def test_registration_reuses_existing_key_and_separate_search_endpoint(search_config):
    service = SearchService.from_runtime_config()
    assert service.provider_names == ["doubao-search"]
    provider = service._providers[0]
    assert provider._api_key == "existing-volcengine-key"
    assert provider._base_url == "https://open.feedcoopapi.com/search_api/web_search"
    assert provider.recall_query_limit == 1


def test_registration_override_and_disable(search_config):
    search_config.update({
        "search.doubao.api_key": "dedicated-key", "search.doubao.edition": "global",
        "search.doubao.timeout": "4.5",
    })
    provider = SearchService.from_runtime_config()._providers[0]
    assert provider._api_key == "dedicated-key"
    assert provider._base_url.endswith("/global_search")
    assert provider._timeout == 4.5
    search_config.update({"search.doubao.enabled": "false"})
    assert SearchService.from_runtime_config().provider_names == []
    search_config.update({"search.doubao.enabled": "true", "search.doubao.api_key": "", "llm.doubao.api_key": ""})
    assert SearchService.from_runtime_config().provider_names == []


def test_yaml_defaults():
    config = RuntimeConfig()
    assert config.get("search.doubao.enabled") == "true"
    assert config.get("search.doubao.edition") == "custom"
    assert float(config.get("search.doubao.timeout")) > 0


@pytest.mark.asyncio
@pytest.mark.parametrize("sources", [None, ["web"], ["doubao-search"]])
async def test_search_service_and_skill_include_doubao(search_config, monkeypatch, sources):
    service = SearchService.from_runtime_config()
    service._providers[0]._transport = httpx.MockTransport(lambda _: httpx.Response(200, json=custom_payload()))
    monkeypatch.setattr(SearchService, "from_runtime_config", classmethod(lambda cls: service))
    result = await SearchSkill().execute(query="agent search", sources=sources, include_images=False)
    assert result.success
    assert result.data["results"][0]["source"] == "doubao-search"
    assert result.data["opened_results"] == 0
    assert result.data["provider_errors"] == []
    assert any(node["node"] == "recall" for node in result.data["search_trace"])


@pytest.mark.asyncio
async def test_failure_keeps_other_web_sources_available():
    class Fallback:
        name = "web"
        async def search(self, query, *, limit=5):
            return [SearchResult(title="Agent search", snippet="Agent search documentation", url="https://example.com/search", source=self.name)]

    failed = DoubaoSearchProvider(api_key="key", transport=httpx.MockTransport(lambda _: httpx.Response(401)))
    service = SearchService([failed, Fallback()], retry_attempts=1)
    results = await service.search("agent search", sources=["web"], include_images=False, rewrite_query=False)
    assert results[0].source == "web"
    assert any("doubao-search" in error for error in service.last_provider_errors)
