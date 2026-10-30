import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from agent.main import SearchRequest, search as search_endpoint
from agent.search import SearchResult, SearchService, WebPageContent
from agent.skills.builtin.search import SearchSkill


PAGE_URL = "https://example.com/agent-search"
IMAGE_URL = "https://example.com/preview.jpg"


@pytest.fixture
def image_search(monkeypatch):
    reader = SimpleNamespace(
        open=AsyncMock(return_value=WebPageContent(
            url=PAGE_URL,
            final_url=PAGE_URL,
            title="Agent search page",
            description=f"Useful description. {IMAGE_URL}",
            content=f"Useful page body. {IMAGE_URL}",
            content_type="text/html",
            status_code=200,
            metadata={"image_url": IMAGE_URL},
        )),
        open_media=AsyncMock(return_value={"image_url": IMAGE_URL}),
        validate_image=AsyncMock(side_effect=lambda url: url),
    )
    provider = SimpleNamespace(
        name="test",
        recall_query_limit=1,
        search=AsyncMock(return_value=[SearchResult(
            title="Agent search result",
            snippet=f"Useful search summary. {IMAGE_URL}",
            url=PAGE_URL,
            source="test",
            image_url=IMAGE_URL,
        )]),
    )
    service = SearchService(providers=[provider], page_reader=reader)
    monkeypatch.setattr(SearchService, "from_runtime_config", classmethod(lambda cls: service))
    monkeypatch.setattr("agent.search.service.WebPageReader", lambda: reader)
    return SimpleNamespace(service=service, provider=provider, reader=reader)


def assert_image_choice(image_search, result, trace_nodes, *, requested):
    image_nodes = [node for node in trace_nodes if node["node"] == "image_enrichment"]
    if requested:
        assert result["image_url"] == IMAGE_URL
        image_search.reader.validate_image.assert_awaited_once_with(IMAGE_URL)
        assert len(image_nodes) == 1
        assert image_nodes[0]["validated_count"] == 1
    else:
        assert result["image_url"] == ""
        assert IMAGE_URL not in json.dumps(result)
        image_search.reader.validate_image.assert_not_awaited()
        image_search.reader.open_media.assert_not_awaited()
        assert image_nodes == []


def test_search_tool_images_require_explicit_user_request():
    parameter = next(item for item in SearchSkill().metadata().parameters if item.name == "include_images")
    assert parameter.default is False
    assert "仅在用户明确要求" in parameter.description


@pytest.mark.asyncio
@pytest.mark.parametrize("options,requested", [
    ({}, False),
    ({"include_images": False}, False),
    ({"include_images": True}, True),
    ({"open_results": True}, False),
    ({"open_results": True, "include_images": False}, False),
    ({"open_results": True, "include_images": True}, True),
])
async def test_page_content_does_not_implicitly_enable_image_requests(image_search, options, requested):
    results = await image_search.service.search("agent search", limit=1, **options)

    assert len(results) == 1
    result = results[0].model_dump(mode="json")
    assert "Useful search summary." in result["snippet"]
    assert_image_choice(image_search, result, image_search.service.last_trace_nodes, requested=requested)
    if options.get("open_results"):
        image_search.reader.open.assert_awaited_once()
        assert "Useful page body." in result["metadata"]["page"]["content"]
    else:
        image_search.reader.open.assert_not_awaited()


@pytest.mark.asyncio
@pytest.mark.parametrize("direct_url", [False, True])
@pytest.mark.parametrize("options,requested", [({}, False), ({"include_images": False}, False), ({"include_images": True}, True)])
async def test_search_skill_requires_image_opt_in_for_query_and_url(image_search, direct_url, options, requested):
    result = await SearchSkill().execute(query=PAGE_URL if direct_url else "agent search", **options)

    assert result.success
    assert result.data["image_count"] == int(requested)
    assert_image_choice(image_search, result.data["results"][0], result.data["search_trace"], requested=requested)
    if direct_url:
        image_search.provider.search.assert_not_awaited()
        assert "Useful page body." in result.data["results"][0]["metadata"]["page"]["content"]
    else:
        image_search.provider.search.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("direct_url", [False, True])
@pytest.mark.parametrize("options,requested", [({}, False), ({"include_images": False}, False), ({"include_images": True}, True)])
async def test_search_api_requires_image_opt_in_for_query_and_url(image_search, direct_url, options, requested):
    request = SearchRequest(query=PAGE_URL if direct_url else "agent search", **options)
    response = await search_endpoint(request)

    assert len(response.results) == 1
    assert_image_choice(image_search, response.results[0].model_dump(mode="json"), response.trace_nodes, requested=requested)
    if direct_url:
        image_search.provider.search.assert_not_awaited()
        assert "Useful page body." in response.results[0].metadata["page"]["content"]
    else:
        image_search.provider.search.assert_awaited_once()


@pytest.mark.asyncio
async def test_explicit_image_request_still_discovers_missing_preview(image_search):
    image_search.provider.search.return_value = [SearchResult(
        title="Agent search result", url=PAGE_URL, source="test",
    )]

    results = await image_search.service.search("agent search", limit=1, include_images=True)

    assert_image_choice(image_search, results[0].model_dump(mode="json"), image_search.service.last_trace_nodes, requested=True)
    image_search.reader.open_media.assert_awaited_once_with(PAGE_URL)
