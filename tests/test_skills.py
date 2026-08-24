"""Unit tests for builtin skills."""
import asyncio
import json

import httpx
import pytest
from agent.skills.builtin.echo import EchoSkill
from agent.skills.builtin.datetime_skill import DateTimeSkill
from agent.skills.builtin.calculator import CalculatorSkill
from agent.skills.builtin.agent_tool import AgentToolSkill
from agent.skills.builtin.drive import (
    ArchiveURLToDriveSkill,
    DriveDeleteSkill,
    DriveGatewayClient,
    DriveListSkill,
    DriveReadSkill,
    DriveSaveSkill,
    DriveSearchSkill,
    DriveShareSkill,
    DriveUpdateSkill,
)
from agent.skills.builtin.todo import (
    TodoCreateSkill,
    TodoDeleteSkill,
    TodoGatewayClient,
    TodoGetSkill,
    TodoListSkill,
    TodoUpdateSkill,
)
from agent.skills.builtin.open_url import OpenURLSkill
from agent.skills.builtin.pulse import (
    PulseDeleteTopicSkill,
    PulseGatewayClient,
    PulseGetSkill,
    PulseListTopicsSkill,
    PulseOptimizeTopicsSkill,
    PulseRefreshSkill,
    PulseUpsertTopicSkill,
)
from agent.skills.builtin.search import SearchSkill
from agent.skills.base import Skill
from agent.runtime.registry import get_agent
from agent.search import (
    BingRSSSearchProvider,
    DuckDuckGoSearchProvider,
    HTTPSearchProvider,
    LLMSearchQueryRewriter,
    MiniMaxMCPSearchProvider,
    SearchResult,
    SearchService,
    StaticSearchProvider,
    WebPageContent,
    WebPageReader,
)
from agent.config import runtime_config


# ==================== Echo Skill ====================

class TestEchoSkill:
    def setup_method(self):
        self.skill = EchoSkill()

    def test_metadata(self):
        meta = self.skill.metadata()
        assert meta.name == "echo"
        assert len(meta.parameters) == 1
        assert meta.parameters[0].name == "text"

    @pytest.mark.asyncio
    async def test_execute(self):
        result = await self.skill.execute(text="hello world")
        assert result.success is True
        assert result.data["echoed"] == "hello world"
        assert "hello world" in result.display_text

    @pytest.mark.asyncio
    async def test_execute_empty(self):
        result = await self.skill.execute(text="")
        assert result.success is True
        assert result.data["echoed"] == ""

    @pytest.mark.asyncio
    async def test_execute_no_args(self):
        result = await self.skill.execute()
        assert result.success is True
        assert result.data["echoed"] == ""

    def test_to_tool_definition(self):
        td = self.skill.to_tool_definition()
        assert td["name"] == "echo"
        assert "parameters" in td
        assert "text" in td["parameters"]["properties"]


# ==================== Agent Tool Skill ====================

class TestAgentToolSkill:
    def setup_method(self):
        agent = get_agent("weight_loss_v1")
        assert agent is not None
        self.skill = AgentToolSkill(agent)

    def test_metadata_marks_workflow_tool(self):
        meta = self.skill.metadata()
        assert meta.name == "weight_loss_v1"
        assert "agent" in meta.tags
        assert "workflow" in meta.tags
        assert meta.source == "system"
        assert "do not call it merely because the user mentions meals" in meta.description

    def test_tool_definition_exposes_agent_arguments(self):
        td = self.skill.to_tool_definition()
        assert td["name"] == "weight_loss_v1"
        assert set(td["parameters"]["required"]) == {"task", "reason"}
        assert "task" in td["parameters"]["properties"]
        assert "context" in td["parameters"]["properties"]

    @pytest.mark.asyncio
    async def test_execute_is_reserved_for_engine(self):
        result = await self.skill.execute(task="记录午餐", reason="测试")
        assert result.success is False
        assert result.data["agent_workflow"] is True
        assert result.data["agent_id"] == "weight_loss_v1"
        assert "agent engine" in result.error


# ==================== DateTime Skill ====================

class TestDateTimeSkill:
    def setup_method(self):
        self.skill = DateTimeSkill()

    def test_metadata(self):
        meta = self.skill.metadata()
        assert meta.name == "datetime"
        assert len(meta.parameters) == 2

    @pytest.mark.asyncio
    async def test_execute_default_utc(self):
        result = await self.skill.execute()
        assert result.success is True
        assert "datetime" in result.data
        assert result.data["timezone"] == "UTC"
        assert "timestamp" in result.data

    @pytest.mark.asyncio
    async def test_execute_with_timezone(self):
        result = await self.skill.execute(timezone="Asia/Shanghai")
        assert result.success is True
        assert result.data["timezone"] == "Asia/Shanghai"

    @pytest.mark.asyncio
    async def test_execute_with_format(self):
        result = await self.skill.execute(format="%Y-%m-%d")
        assert result.success is True
        # Should be in YYYY-MM-DD format
        assert len(result.data["datetime"]) == 10

    @pytest.mark.asyncio
    async def test_execute_invalid_timezone(self):
        result = await self.skill.execute(timezone="Invalid/Zone")
        assert result.success is False
        assert "Unknown timezone" in result.error

    @pytest.mark.asyncio
    async def test_display_text(self):
        result = await self.skill.execute(timezone="UTC")
        assert result.display_text is not None
        assert "UTC" in result.display_text


# ==================== Calculator Skill ====================

class TestCalculatorSkill:
    def setup_method(self):
        self.skill = CalculatorSkill()

    def test_metadata(self):
        meta = self.skill.metadata()
        assert meta.name == "calculator"
        assert len(meta.parameters) == 1
        assert meta.parameters[0].name == "expression"

    @pytest.mark.asyncio
    async def test_basic_addition(self):
        result = await self.skill.execute(expression="2 + 3")
        assert result.success is True
        assert result.data["result"] == 5

    @pytest.mark.asyncio
    async def test_multiplication(self):
        result = await self.skill.execute(expression="42 * 17 + 3")
        assert result.success is True
        assert result.data["result"] == 717

    @pytest.mark.asyncio
    async def test_division(self):
        result = await self.skill.execute(expression="100 / 4")
        assert result.success is True
        assert result.data["result"] == 25.0

    @pytest.mark.asyncio
    async def test_power(self):
        result = await self.skill.execute(expression="2 ** 10")
        assert result.success is True
        assert result.data["result"] == 1024

    @pytest.mark.asyncio
    async def test_modulo(self):
        result = await self.skill.execute(expression="17 % 5")
        assert result.success is True
        assert result.data["result"] == 2

    @pytest.mark.asyncio
    async def test_floor_division(self):
        result = await self.skill.execute(expression="17 // 5")
        assert result.success is True
        assert result.data["result"] == 3

    @pytest.mark.asyncio
    async def test_negative_numbers(self):
        result = await self.skill.execute(expression="-5 + 3")
        assert result.success is True
        assert result.data["result"] == -2

    @pytest.mark.asyncio
    async def test_nested_parentheses(self):
        result = await self.skill.execute(expression="(2 + 3) * (4 - 1)")
        assert result.success is True
        assert result.data["result"] == 15

    @pytest.mark.asyncio
    async def test_float_numbers(self):
        result = await self.skill.execute(expression="3.14 * 2")
        assert result.success is True
        assert abs(result.data["result"] - 6.28) < 0.001

    @pytest.mark.asyncio
    async def test_division_by_zero(self):
        result = await self.skill.execute(expression="1 / 0")
        assert result.success is False
        assert "zero" in result.error.lower()

    @pytest.mark.asyncio
    async def test_empty_expression(self):
        result = await self.skill.execute(expression="")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_no_args(self):
        result = await self.skill.execute()
        assert result.success is False

    @pytest.mark.asyncio
    async def test_invalid_expression(self):
        result = await self.skill.execute(expression="hello + world")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reject_function_calls(self):
        """Should not allow arbitrary function calls like __import__."""
        result = await self.skill.execute(expression="__import__('os').system('ls')")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_reject_variable_access(self):
        """Should not allow variable name access."""
        result = await self.skill.execute(expression="x + 1")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_display_text(self):
        result = await self.skill.execute(expression="1 + 1")
        assert result.display_text == "1 + 1 = 2"


# ==================== Search Skill ====================

class TestSearchSkill:
    def setup_method(self):
        self.skill = SearchSkill()

    def test_metadata(self):
        meta = self.skill.metadata()
        assert meta.name == "search"
        assert meta.source == "builtin"
        assert "必须先调用 search 再回答" in meta.description
        assert "可核验实体或编号" in meta.description
        assert "未验证的解释" in meta.description
        assert "医疗" in meta.description
        assert "法律" in meta.description
        assert "金融" in meta.description
        assert "安全风险" in meta.description
        assert "open_url" in meta.description
        assert {p.name for p in meta.parameters} == {
            "query",
            "sources",
            "limit",
            "open_results",
            "include_images",
            "image_limit",
            "open_limit",
            "page_chars",
        }
        parameters = {parameter.name: parameter for parameter in meta.parameters}
        assert parameters["include_images"].default is True
        assert parameters["image_limit"].default == 3

    @pytest.mark.asyncio
    async def test_static_search_provider(self):
        service = SearchService(
            providers=[
                StaticSearchProvider(
                    documents=[
                        {
                            "title": "Memory System",
                            "content": "role memory and persona memory",
                            "url": "local://memory",
                        },
                        {
                            "title": "Other",
                            "content": "unrelated",
                        },
                    ]
                )
            ]
        )

        results = await service.search("persona", limit=3)

        assert len(results) == 1
        assert results[0].title == "Memory System"
        assert results[0].url == "local://memory"

    @pytest.mark.asyncio
    async def test_http_search_provider_coerces_payload_and_request(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            seen["authorization"] = request.headers.get("authorization")
            return httpx.Response(
                200,
                json={
                    "items": [
                        {
                            "name": "Agent Search Quality",
                            "summary": "BM25 ranking and recall variants.",
                            "link": "https://example.com/search-quality",
                            "source": "external-index",
                            "published": "2026-07-01",
                            "metadata": {"rank": 1},
                        },
                        {
                            "title": "Ignored by limit",
                            "url": "https://example.com/ignored",
                        },
                    ]
                },
            )

        provider = HTTPSearchProvider(
            name="http",
            base_url="https://search.example/api",
            api_key="secret-token",
            query_param="query",
            transport=httpx.MockTransport(handler),
        )

        results = await provider.search("agent search", limit=1)

        assert seen["url"] == "https://search.example/api?query=agent+search&limit=1"
        assert seen["authorization"] == "Bearer secret-token"
        assert len(results) == 1
        assert results[0].title == "Agent Search Quality"
        assert results[0].snippet == "BM25 ranking and recall variants."
        assert results[0].url == "https://example.com/search-quality"
        assert results[0].source == "external-index"
        assert results[0].metadata == {"rank": 1, "published": "2026-07-01"}

    @pytest.mark.asyncio
    async def test_duckduckgo_provider_parses_results_and_skips_ads(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(
                200,
                text="""
                <html><body>
                  <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Farticle">Useful Result</a>
                  <a class="result__snippet">A focused search snippet.</a>
                  <a class="result__a" href="https://duckduckgo.com/y.js?ad_domain=ad.example">Sponsored Result</a>
                  <a class="result__snippet">Ad snippet.</a>
                </body></html>
                """,
            )

        provider = DuckDuckGoSearchProvider(
            base_url="https://duck.example/html/",
            transport=httpx.MockTransport(handler),
        )

        results = await provider.search("agent search", limit=5)

        assert seen["url"] == "https://duck.example/html/?q=agent+search"
        assert len(results) == 1
        assert results[0].title == "Useful Result"
        assert results[0].snippet == "A focused search snippet."
        assert results[0].url == "https://example.com/article"
        assert results[0].source == "web"

    @pytest.mark.asyncio
    async def test_bing_rss_provider_parses_items_and_pub_date(self):
        seen = {}

        def handler(request):
            seen["url"] = str(request.url)
            return httpx.Response(
                200,
                text="""
                <rss><channel>
                  <item>
                    <title>Agent Search Ranking</title>
                    <link>https://example.com/ranking</link>
                    <description>Ranking and recall quality.</description>
                    <pubDate>Wed, 01 Jul 2026 10:00:00 GMT</pubDate>
                  </item>
                  <item>
                    <title></title>
                    <link>https://example.com/missing-title</link>
                  </item>
                </channel></rss>
                """,
            )

        provider = BingRSSSearchProvider(
            base_url="https://bing.example/search",
            transport=httpx.MockTransport(handler),
        )

        results = await provider.search("agent search", limit=5)

        assert seen["url"] == "https://bing.example/search?q=agent+search&format=rss"
        assert len(results) == 1
        assert results[0].title == "Agent Search Ranking"
        assert results[0].snippet == "Ranking and recall quality."
        assert results[0].url == "https://example.com/ranking"
        assert results[0].metadata["pub_date"] == "Wed, 01 Jul 2026 10:00:00 GMT"

    @pytest.mark.asyncio
    async def test_search_service_retries_flaky_provider(self):
        class FlakyProvider:
            name = "flaky"

            def __init__(self):
                self.calls = 0

            async def search(self, query, *, limit=5):
                self.calls += 1
                if self.calls < 3:
                    raise RuntimeError("temporary outage")
                return [
                    SearchResult(
                        title="Recovered Result",
                        snippet=query,
                        url="https://example.com/recovered",
                        source=self.name,
                    )
                ]

        provider = FlakyProvider()
        service = SearchService(
            providers=[provider],
            retry_attempts=3,
            retry_delay=0,
        )

        results = await service.search("agent tools", limit=1)

        assert provider.calls == 3
        assert results[0].title == "Recovered Result"
        assert service.last_provider_errors == []

    @pytest.mark.asyncio
    async def test_search_service_falls_back_after_provider_failure(self):
        class FailingProvider:
            name = "minimax-mcp"

            async def search(self, query, *, limit=5):
                raise RuntimeError("mcp returned invalid json")

        class FallbackProvider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Fallback Result",
                        snippet=query,
                        url="https://example.com/fallback",
                        source=self.name,
                    )
                ]

        service = SearchService(
            providers=[FailingProvider(), FallbackProvider()],
            retry_attempts=2,
            retry_delay=0,
        )

        results = await service.search("MCP tools", limit=3)

        assert len(results) == 1
        assert results[0].source == "web"
        assert "minimax-mcp: mcp returned invalid json" in service.last_provider_errors

    @pytest.mark.asyncio
    async def test_search_service_reranks_default_provider_noise(self):
        class NoisyProvider:
            name = "bing-rss"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Homemade crispy french fries",
                        snippet="A recipe with potatoes, oil, and salt.",
                        url="https://example.com/fries",
                        source=self.name,
                    )
                ]

        class RelevantProvider:
            name = "minimax-mcp"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Dify Agent RAG engineering practice",
                        snippet="Agent workflow, Dify knowledge base, and RAG evaluation.",
                        url="https://example.com/dify-agent-rag",
                        source=self.name,
                    )
                ]

        service = SearchService(
            providers=[NoisyProvider(), RelevantProvider()],
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search("Agent 工程实践 Dify RAG latest news 2026", limit=2)

        assert [result.title for result in results] == [
            "Dify Agent RAG engineering practice",
        ]

    @pytest.mark.asyncio
    async def test_search_service_bm25_filters_low_relevance_noise(self):
        class NoisyProvider:
            name = "bing-rss"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="2026 - Wikipedia",
                        snippet="2026 is the current year.",
                        url="https://en.wikipedia.org/wiki/2026",
                        source=self.name,
                    ),
                    SearchResult(
                        title="FIFA World Cup 2026 schedule",
                        snippet="Match schedule, fixtures, teams, and stadiums.",
                        url="https://www.fifa.com/worldcup2026/schedule",
                        source=self.name,
                    ),
                    SearchResult(
                        title="2026 Calendar",
                        snippet="Yearly calendar.",
                        url="https://example.com/calendar-2026",
                        source=self.name,
                    ),
                ]

        class MovieProvider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title=f"2026最新高分上映电影汇总 {index}",
                        snippet="口碑电影推荐和上映片单。",
                        url=f"https://example.com/movie/{index}",
                        source=self.name,
                    )
                    for index in range(3)
                ]

        service = SearchService(
            providers=[NoisyProvider(), MovieProvider()],
            retry_attempts=1,
            retry_delay=0,
            min_provider_coverage=2,
        )

        results = await service.search("2026年最新上映的高口碑电影推荐", limit=6)

        assert results
        assert {result.source for result in results} == {"web"}
        assert all("电影" in result.title for result in results)

    @pytest.mark.asyncio
    async def test_search_service_ranks_full_query_relevance_without_keyword_filtering(self):
        class Provider:
            name = "bing-rss"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="chéngrén: 成人 - Adult, Grown-up [Contextual Chinese Dictionary]",
                        snippet="成人 means adult or grown-up in Chinese.",
                        url="https://contextualchinese.com/%E6%88%90%E4%BA%BA",
                        source=self.name,
                    ),
                    SearchResult(
                        title="成人用品-成人用品价格、图片、排行",
                        snippet="成人用品排行和图片。",
                        url="https://www.1688.com/market/adult-products.html",
                        source=self.name,
                    ),
                    SearchResult(
                        title="成人电影+",
                        snippet="限制级大尺度影片片单。",
                        url="https://www.example.com/adult-movies",
                        source=self.name,
                    ),
                    SearchResult(
                        title="成人钢琴入门教材推荐",
                        snippet="成人零基础钢琴学习可从拜厄、车尔尼和哈农开始。",
                        url="https://example.com/adult-piano-beginner",
                        source=self.name,
                    ),
                    SearchResult(
                        title="拜厄钢琴基础教程",
                        snippet="适合零基础钢琴入门的教材和练习路径。",
                        url="https://example.com/beyer-piano",
                        source=self.name,
                    ),
                ]

        service = SearchService(
            providers=[Provider()],
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search("成人钢琴入门 教材 推荐 拜厄 车尔尼 哈农", limit=6)
        titles = [result.title for result in results]

        assert titles[:2] == ["成人钢琴入门教材推荐", "拜厄钢琴基础教程"]
        assert "成人用品-成人用品价格、图片、排行" in titles

    @pytest.mark.asyncio
    async def test_search_service_llm_rerank_filters_irrelevant_candidates(self):
        class Provider:
            name = "bing-rss"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Euro sign - Wikipedia",
                        snippet="The euro sign is the currency symbol used for the euro.",
                        url="https://en.wikipedia.org/wiki/Euro_sign",
                        source=self.name,
                    ),
                    SearchResult(
                        title="Euro Truck Simulator 2 DLC Page",
                        snippet="Steam DLC page for Euro Truck Simulator 2.",
                        url="https://store.steampowered.com/dlc/227300/Euro_Truck_Simulator_2/",
                        source=self.name,
                    ),
                    SearchResult(
                        title="ETS2 DLC buying guide",
                        snippet="Map DLC recommendations for ETS2.",
                        url="https://example.com/ets2-dlc-guide",
                        source=self.name,
                    ),
                ]

        class FakeReranker:
            name = "fake-llm"
            max_candidates = 5

            async def rerank(self, query, results, *, limit, query_context=None):
                selected = []
                decisions = []
                for index, result in enumerate(results, start=1):
                    relevant = (
                        "Euro Truck Simulator 2" in result.title
                        or "ETS2" in result.title
                    )
                    decisions.append(
                        {
                            "index": index,
                            "score": 0.92 if relevant else 0.05,
                            "reason": "matches game DLC intent" if relevant else "different meaning",
                            "title": result.title,
                            "url": result.url,
                        }
                    )
                    if relevant:
                        selected.append(result)
                return selected[:limit], {
                    "status": "completed",
                    "model": "fake-reranker",
                    "threshold": 0.35,
                    "candidate_count": len(results),
                    "judged_count": len(decisions),
                    "kept_count": len(selected[:limit]),
                    "decisions": decisions,
                }

        service = SearchService(
            providers=[Provider()],
            reranker=FakeReranker(),
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search("Euro Truck Simulator 2 DLC list", limit=5)
        titles = [result.title for result in results]

        assert "Euro sign - Wikipedia" not in titles
        assert titles == ["Euro Truck Simulator 2 DLC Page", "ETS2 DLC buying guide"]
        rerank_node = next(node for node in service.last_trace_nodes if node["node"] == "llm_rerank")
        assert rerank_node["status"] == "completed"
        assert rerank_node["provider"] == "fake-llm"
        assert rerank_node["kept_count"] == 2

    @pytest.mark.asyncio
    async def test_search_service_llm_rerank_failure_falls_back_to_ranking(self):
        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Agent search ranking",
                        snippet="Search ranking and recall details.",
                        url="https://example.com/search-ranking",
                        source=self.name,
                    )
                ]

        class FailingReranker:
            name = "fake-llm"
            max_candidates = 5

            async def rerank(self, query, results, *, limit, query_context=None):
                raise RuntimeError("rerank unavailable")

        service = SearchService(
            providers=[Provider()],
            reranker=FailingReranker(),
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search("agent search ranking", limit=1)

        assert [result.title for result in results] == ["Agent search ranking"]
        rerank_node = next(node for node in service.last_trace_nodes if node["node"] == "llm_rerank")
        assert rerank_node["status"] == "partial"
        assert "rerank unavailable" in rerank_node["error"]

    @pytest.mark.asyncio
    async def test_search_service_llm_rerank_sees_raw_candidates_beyond_bm25(self):
        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Semiconductor foundry procurement landscape",
                        snippet="Supplier concentration and manufacturing capacity analysis.",
                        url="https://example.com/procurement-landscape",
                        source=self.name,
                    ),
                    SearchResult(
                        title="Enterprise vendor renewal calendar",
                        snippet="Internal procurement dates and generic planning notes.",
                        url="https://example.com/vendor-calendar",
                        source=self.name,
                    )
                ]

        class FakeReranker:
            name = "fake-llm"
            max_candidates = 5

            async def rerank(self, query, results, *, limit, query_context=None):
                return results[:limit], {
                    "status": "completed",
                    "model": "fake-reranker",
                    "threshold": 0.35,
                    "candidate_count": len(results),
                    "judged_count": len(results),
                    "kept_count": len(results[:limit]),
                    "decisions": [
                        {
                            "index": index,
                            "score": 0.9,
                            "reason": "semantic match",
                            "title": result.title,
                            "url": result.url,
                        }
                        for index, result in enumerate(results, start=1)
                    ],
                }

        service = SearchService(
            providers=[Provider()],
            reranker=FakeReranker(),
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search("量子芯片供应链调研", limit=1)

        assert [result.title for result in results] == [
            "Semiconductor foundry procurement landscape"
        ]
        ranking_node = next(node for node in service.last_trace_nodes if node["node"] == "ranking")
        assert ranking_node["output_count"] == 0
        rerank_node = next(node for node in service.last_trace_nodes if node["node"] == "llm_rerank")
        assert rerank_node["input_count"] == 2
        assert rerank_node["output_count"] == 1

    @pytest.mark.asyncio
    async def test_llm_reranker_prompt_includes_rewrite_and_retrieval_context(self):
        from agent.llm.base import LLMResponse
        from agent.search.service import LLMSearchReranker

        class Provider:
            def __init__(self):
                self.messages = []

            async def chat(self, messages, tools=None, temperature=0.7, cache=None):
                self.messages = messages
                return LLMResponse(
                    content=json.dumps(
                        {
                            "results": [
                                {
                                    "index": 1,
                                    "score": 0.86,
                                    "reason": "exact product match",
                                }
                            ]
                        }
                    ),
                    model="fake-model",
                    usage={"input": 10, "output": 5},
                )

        provider = Provider()
        reranker = LLMSearchReranker(
            provider,
            name="llm:fake",
            min_score=0.5,
        )
        result = SearchResult(
            title="Dunlop Fingerboard 01 Cleaner & Prep",
            snippet="Formula 65 Fingerboard 01 Cleaner and Prep.",
            url="https://example.com/fingerboard-01",
            source="web",
            metadata={
                "retrieval_query": "Dunlop Formula 01 Fingerboard Cleaner",
                "retrieval_query_index": 1,
            },
        )

        selected, metadata = await reranker.rerank(
            "Dunlop 01 02 清洁保养剂",
            [result],
            limit=1,
            query_context={
                "strategy": "keyword_recall",
                "queries": [
                    "Dunlop 01 02 清洁保养剂",
                    "Dunlop Formula 01 Fingerboard Cleaner",
                ],
            },
        )

        prompt = "\n".join(str(message.content) for message in provider.messages)
        assert selected == [result]
        assert metadata["threshold"] == 0.5
        assert "搜索查询上下文 JSON" in prompt
        assert "Dunlop 01 02 清洁保养剂" in prompt
        assert "Dunlop Formula 01 Fingerboard Cleaner" in prompt
        assert '"retrieval_query": "Dunlop Formula 01 Fingerboard Cleaner"' in prompt
        assert "显式约束" in prompt
        assert "文档形态" in prompt
        assert metadata["query_context"]["recall_queries"] == [
            "Dunlop 01 02 清洁保养剂",
            "Dunlop Formula 01 Fingerboard Cleaner",
        ]

    @pytest.mark.asyncio
    async def test_llm_query_rewriter_uses_model_knowledge_and_keeps_lexical_fallback(self):
        from agent.llm.base import LLMResponse
        from agent.search.recall import build_query_rewrite_plan

        class Provider:
            def __init__(self):
                self.messages = []

            async def chat(self, messages, tools=None, temperature=0.7, cache=None):
                self.messages = messages
                return LLMResponse(
                    content=json.dumps(
                        {
                            "queries": [
                                "ETS2 DLC complete list Steam",
                                "欧洲卡车模拟2 DLC 列表 最新",
                                "Euro Truck Simulator 2 downloadable content wiki",
                            ],
                            "reason": "add common acronym, Chinese title, and content synonym",
                        }
                    ),
                    model="fake-model",
                    usage={"input": 11, "output": 6},
                )

        provider = Provider()
        rewriter = LLMSearchQueryRewriter(
            provider,
            name="llm:fake",
            max_queries=4,
        )
        lexical_plan = build_query_rewrite_plan(
            "Euro Truck Simulator 2 DLC list latest",
            max_queries=4,
        )

        plan = await rewriter.rewrite(
            "Euro Truck Simulator 2 DLC list latest",
            max_queries=4,
            lexical_plan=lexical_plan,
        )

        prompt = "\n".join(str(message.content) for message in provider.messages)
        assert "可以使用模型的通用知识" in prompt
        assert "同时出现中文 query 和英文 query" in prompt
        assert "language_policy" in prompt
        assert "不要把未被用户表达支持" in prompt
        assert plan["strategy"] == "llm_semantic_rewrite"
        assert plan["queries"][0] == lexical_plan["queries"][0]
        assert plan["queries"][1] == "欧洲卡车模拟2 DLC 列表 最新"
        assert "ETS2 DLC complete list Steam" in plan["queries"]
        assert "Euro Truck Simulator 2 downloadable content wiki" in plan["queries"]
        assert plan["lexical_queries"] == lexical_plan["queries"]
        assert plan["language_policy"]["original_language"] == "latin"
        assert plan["model"] == "fake-model"

    @pytest.mark.asyncio
    async def test_search_service_uses_llm_query_rewriter_variants_for_recall(self):
        original_query = "Dify RAG Agent 工程实践 评测 benchmark"
        rewrite_query = "Dify RAG evaluation benchmark engineering practice"

        class Rewriter:
            name = "fake-rewriter"
            max_queries = 2

            async def rewrite(self, query, *, max_queries, lexical_plan=None):
                return {
                    "node": "query_rewrite",
                    "status": "completed",
                    "policy_id": "fake",
                    "policy": "fake policy",
                    "strategy": "llm_semantic_rewrite",
                    "original_query": query,
                    "queries": [query, rewrite_query],
                    "lexical_queries": (lexical_plan or {}).get("queries", []),
                    "provider": self.name,
                }

        class Provider:
            name = "web"
            recall_query_limit = 2

            def __init__(self):
                self.calls = []

            async def search(self, query, *, limit=5):
                self.calls.append(query)
                if query == rewrite_query:
                    return [
                        SearchResult(
                            title="Dify RAG evaluation benchmark practice",
                            snippet="Engineering practice for evaluating Dify RAG agent workflows.",
                            url="https://example.com/dify-rag-eval",
                            source=self.name,
                        )
                    ]
                return []

        provider = Provider()
        service = SearchService(
            providers=[provider],
            query_rewriter=Rewriter(),
            retry_attempts=1,
            retry_delay=0,
            recall_max_queries=2,
        )

        results = await service.search(original_query, limit=1)

        assert provider.calls == [original_query, rewrite_query]
        assert [result.title for result in results] == [
            "Dify RAG evaluation benchmark practice"
        ]
        assert results[0].metadata["retrieval_query"] == rewrite_query
        assert service.last_query_rewrite["strategy"] == "llm_semantic_rewrite"
        rewrite_node = service.last_trace_nodes[0]
        assert rewrite_node["provider"] == "fake-rewriter"
        assert rewrite_node["queries"] == [original_query, rewrite_query]

    @pytest.mark.asyncio
    async def test_search_service_preserves_specialized_market_query_results(self):
        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="宠物用品行业市场报告",
                        snippet="宠物用品市场规模和渠道分析。",
                        url="https://example.com/pet-products-market",
                        source=self.name,
                    )
                ]

        service = SearchService(
            providers=[Provider()],
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search("宠物用品 行业市场报告", limit=3)

        assert [result.title for result in results] == ["宠物用品行业市场报告"]

    @pytest.mark.asyncio
    async def test_search_service_boosts_official_brand_domain(self):
        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Dunlop 01 Fingerboard Cleaner And Prep - Equipboard",
                        snippet="User-submitted gear notes.",
                        url="https://equipboard.com/items/jim-dunlop-01-fingerboard-cleaner-and-prep",
                        source=self.name,
                    ),
                    SearchResult(
                        title="FORMULA 65 FINGERBOARD 01 CLEANER & PREP - Dunlop",
                        snippet="Cleaner and prep for unfinished fingerboards.",
                        url="https://www.jimdunlop.com/formula-65-fingerboard-01-cleaner-prep/",
                        source=self.name,
                    ),
                ]

        service = SearchService(
            providers=[Provider()],
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search(
            "Dunlop 6531 Fingerboard 01 Cleaner 指板清洁剂 用途",
            limit=2,
        )

        assert results[0].url == "https://www.jimdunlop.com/formula-65-fingerboard-01-cleaner-prep/"

    @pytest.mark.asyncio
    async def test_search_service_reranks_compact_cjk_query(self):
        class NoisyProvider:
            name = "http"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="2026 - Wikipedia",
                        snippet="2026 is a common year.",
                        url="https://example.com/year-2026",
                        source=self.name,
                    )
                ]

        class RelevantProvider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="2026最新高分上映电影汇总",
                        snippet="口碑电影推荐和上映片单。",
                        url="https://example.com/movies-2026",
                        source=self.name,
                    )
                ]

        service = SearchService(
            providers=[NoisyProvider(), RelevantProvider()],
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search("2026年最新上映的高口碑电影推荐", limit=2)

        assert [result.source for result in results] == ["web"]

    @pytest.mark.asyncio
    async def test_search_service_web_alias_prefers_html_web_provider(self):
        class WebProvider:
            name = "web"

            def __init__(self):
                self.calls = 0

            async def search(self, query, *, limit=5):
                self.calls += 1
                await asyncio.sleep(0.01)
                return [
                    SearchResult(
                        title=f"炝锅面教程 {index}",
                        snippet=query,
                        url=f"https://example.com/web/{index}",
                        source=self.name,
                    )
                    for index in range(limit)
                ]

        class SlowMCPProvider:
            name = "minimax-mcp"

            def __init__(self):
                self.calls = 0
                self.cancelled = False

            async def search(self, query, *, limit=5):
                self.calls += 1
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
                return []

        class BingProvider:
            name = "bing-rss"

            def __init__(self):
                self.calls = 0
                self.cancelled = False

            async def search(self, query, *, limit=5):
                self.calls += 1
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
                return []

        web = WebProvider()
        mcp = SlowMCPProvider()
        bing = BingProvider()
        service = SearchService(
            providers=[mcp, bing, web],
            retry_attempts=1,
            retry_delay=0,
            min_provider_coverage=1,
        )

        results = await service.search("炝锅面教程", sources=["web"], limit=3)

        assert len(results) == 3
        assert {result.source for result in results} == {"web"}
        assert web.calls == 1
        assert mcp.calls == 1
        assert mcp.cancelled
        assert bing.calls == 1
        assert bing.cancelled

    @pytest.mark.asyncio
    async def test_search_service_web_alias_fans_out_and_interleaves_sources(self):
        class Provider:
            def __init__(self, name):
                self.name = name
                self.calls = []

            async def search(self, query, *, limit=5):
                self.calls.append(limit)
                return [
                    SearchResult(
                        title=f"{query} {self.name} result {index}",
                        snippet=query,
                        url=f"https://example.com/{self.name}/{index}",
                        source=self.name,
                    )
                    for index in range(limit)
                ]

        web = Provider("web")
        mcp = Provider("minimax-mcp")
        bing = Provider("bing-rss")
        service = SearchService(
            providers=[bing, mcp, web],
            retry_attempts=1,
            retry_delay=0,
            min_provider_coverage=3,
        )

        results = await service.search(
            "agent search coverage",
            sources=["web"],
            limit=6,
        )

        assert web.calls == [12]
        assert mcp.calls == [12]
        assert bing.calls == [12]
        assert {result.source for result in results} == {
            "web",
            "minimax-mcp",
            "bing-rss",
        }

    @pytest.mark.asyncio
    async def test_search_service_web_alias_selects_web_sources_case_insensitively(self):
        class Provider:
            def __init__(self, name):
                self.name = name
                self.calls = 0

            async def search(self, query, *, limit=5):
                self.calls += 1
                return [
                    SearchResult(
                        title=f"{self.name} agent search result",
                        snippet=query,
                        url=f"https://example.com/{self.name}",
                        source=self.name,
                    )
                ]

        local = Provider("local")
        http_provider = Provider("http")
        web = Provider("web")
        bing = Provider("bing-rss")
        service = SearchService(
            providers=[local, http_provider, web, bing],
            retry_attempts=1,
            retry_delay=0,
            min_provider_coverage=2,
        )

        results = await service.search(
            "agent search",
            sources=[" WEB ", "BING-RSS"],
            limit=5,
        )

        assert local.calls == 0
        assert http_provider.calls == 0
        assert web.calls == 1
        assert bing.calls == 1
        assert {result.source for result in results} == {"web", "bing-rss"}

    @pytest.mark.asyncio
    async def test_search_service_deduplicates_same_url_across_sources(self):
        class Provider:
            def __init__(self, name):
                self.name = name

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title=f"{self.name} Agent Search Ranking",
                        snippet="Agent search ranking and recall.",
                        url="https://example.com/shared-result",
                        source=self.name,
                    )
                ]

        service = SearchService(
            providers=[Provider("web"), Provider("bing-rss")],
            retry_attempts=1,
            retry_delay=0,
            min_provider_coverage=2,
        )

        results = await service.search("agent search ranking", limit=5)

        assert len(results) == 1
        assert results[0].url == "https://example.com/shared-result"

    @pytest.mark.asyncio
    async def test_search_service_caps_provider_limit_after_multiplier(self):
        class Provider:
            name = "web"

            def __init__(self):
                self.seen_limits = []

            async def search(self, query, *, limit=5):
                self.seen_limits.append(limit)
                return [
                    SearchResult(
                        title=f"Agent search result {index}",
                        snippet="Agent search ranking and recall.",
                        url=f"https://example.com/result/{index}",
                        source=self.name,
                    )
                    for index in range(limit)
                ]

        provider = Provider()
        service = SearchService(
            providers=[provider],
            retry_attempts=1,
            retry_delay=0,
            provider_limit_multiplier=3,
        )

        results = await service.search("agent search", limit=15)

        assert provider.seen_limits == [20]
        assert len(results) == 15

    @pytest.mark.asyncio
    async def test_search_service_expands_fallback_queries_for_recall(self):
        original_query = "2026年最新上映的高口碑电影推荐"

        class VariantProvider:
            name = "web"
            recall_query_limit = 2

            def __init__(self):
                self.calls = []

            async def search(self, query, *, limit=5):
                self.calls.append(query)
                if query == original_query:
                    return [
                        SearchResult(
                            title="Annual sports calendar",
                            snippet="Fixtures, dates, and venues.",
                            url="https://example.com/sports-calendar",
                            source=self.name,
                        )
                    ]
                return [
                    SearchResult(
                        title="2026最新上映高口碑电影推荐",
                        snippet="电影片单、口碑和上映信息。",
                        url="https://example.com/movies-2026",
                        source=self.name,
                    )
                ]

        provider = VariantProvider()
        service = SearchService(
            providers=[provider],
            retry_attempts=1,
            retry_delay=0,
            recall_max_queries=2,
        )

        results = await service.search(original_query, limit=3)

        assert len(provider.calls) == 2
        assert provider.calls[0] == original_query
        assert provider.calls[1] != original_query
        assert "电影" in provider.calls[1]
        assert [result.title for result in results] == ["2026最新上映高口碑电影推荐"]
        assert results[0].metadata["retrieval_query"] == provider.calls[1]
        assert results[0].metadata["retrieval_query_index"] == 1
        assert service.last_query_variants == provider.calls

    def test_search_query_variants_use_cjk_phrase_chunks(self):
        from agent.search.recall import build_query_rewrite_plan, build_query_variants

        variants = build_query_variants("2026年最新上映的高口碑电影推荐", max_queries=2)
        brand_variants = build_query_variants(
            "Dunlop 6531 Fingerboard 01 Cleaner 指板清洁剂 用途",
            max_queries=2,
        )
        anchored_plan = build_query_rewrite_plan(
            "成人钢琴入门 教材 拜厄 车尔尼 哈农",
            max_queries=3,
        )
        product_plan = build_query_rewrite_plan(
            "Euro Truck Simulator 2 DLC list complete Steam wiki",
            max_queries=3,
        )
        site_plan = build_query_rewrite_plan(
            "site:store.steampowered.com Euro Truck Simulator 2 DLC",
            max_queries=3,
        )
        boolean_plan = build_query_rewrite_plan(
            '"Euro Truck Simulator 2" "Greece" OR "West Balkans" review worth it',
            max_queries=3,
        )
        compact_model_plan = build_query_rewrite_plan(
            "Dunlop65 01 02 三瓶 清洁 保养剂 电吉他 分别作用",
            max_queries=3,
        )

        assert variants == [
            "2026年最新上映的高口碑电影推荐",
            "2026 最新上映 高口碑电影推荐",
        ]
        assert brand_variants == [
            "Dunlop 6531 Fingerboard 01 Cleaner 指板清洁剂 用途",
            "6531 01 dunlop fingerboard cleaner 指板清洁剂 用途",
        ]
        assert anchored_plan["node"] == "query_rewrite"
        assert anchored_plan["policy_id"] == "lexical_recall_no_inference_v1"
        assert "召回阶段的词法改写节点" in anchored_plan["policy"]
        assert anchored_plan["strategy"] == "anchor_rewrite"
        assert anchored_plan["queries"][:2] == [
            "成人钢琴入门 教材 拜厄 车尔尼 哈农",
            "拜厄钢琴教材 车尔尼 哈农",
        ]
        assert product_plan["strategy"] == "phrase_rewrite"
        assert product_plan["queries"][:3] == [
            '"Euro Truck Simulator 2" DLC list complete Steam wiki',
            "Euro Truck Simulator 2 DLC list complete Steam wiki",
            "ETS2 DLC list complete Steam wiki",
        ]
        assert compact_model_plan["strategy"] == "alnum_boundary_rewrite"
        assert compact_model_plan["queries"][:2] == [
            "Dunlop 65 01 02 三瓶 清洁 保养剂 电吉他 分别作用",
            "Dunlop65 01 02 三瓶 清洁 保养剂 电吉他 分别作用",
        ]
        assert site_plan["strategy"] == "syntax_preserving_rewrite"
        assert site_plan["queries"] == [
            'site:store.steampowered.com "Euro Truck Simulator 2" DLC',
            "site:store.steampowered.com Euro Truck Simulator 2 DLC",
        ]
        assert all("site store" not in query for query in site_plan["queries"])
        assert boolean_plan["queries"] == [
            '"Euro Truck Simulator 2" "Greece" OR "West Balkans" review worth it'
        ]

    def test_search_ranking_keeps_numeric_model_terms(self):
        from agent.search.ranking import rank_search_results, search_query_terms

        assert "4090" in search_query_terms("RTX4090 显卡 评测")

        results = [
            SearchResult(
                title="RTX 4080 显卡评测",
                snippet="NVIDIA RTX graphics card benchmark.",
                url="https://example.com/rtx-4080",
                source="fixture",
            ),
            SearchResult(
                title="RTX 4090 显卡评测",
                snippet="NVIDIA RTX 4090 graphics card benchmark.",
                url="https://example.com/rtx-4090",
                source="fixture",
            ),
        ]

        ranked = rank_search_results("RTX4090 显卡 评测", results)

        assert ranked[0].result.title == "RTX 4090 显卡评测"

    @pytest.mark.asyncio
    async def test_search_service_uses_query_rewrite_anchors_before_ranking(self):
        original_query = "成人钢琴入门 教材 拜厄 车尔尼 哈农"

        class RewriteProvider:
            name = "web"
            recall_query_limit = 2

            def __init__(self):
                self.calls = []

            async def search(self, query, *, limit=5):
                self.calls.append(query)
                if query.startswith("拜厄钢琴教材"):
                    return [
                        SearchResult(
                            title="拜厄钢琴基本教程与车尔尼哈农搭配",
                            snippet="适合钢琴入门教材选择，包含拜厄、车尔尼、哈农练习顺序。",
                            url="https://example.com/beyer-piano-books",
                            source=self.name,
                        )
                    ]
                return [
                    SearchResult(
                        title="Unrelated result",
                        snippet="Only one broad context word is present.",
                        url="https://example.com/unrelated",
                        source=self.name,
                    )
                ]

        provider = RewriteProvider()
        service = SearchService(
            providers=[provider],
            retry_attempts=1,
            retry_delay=0,
            recall_max_queries=2,
        )

        results = await service.search(original_query, limit=1)

        assert provider.calls == [
            "成人钢琴入门 教材 拜厄 车尔尼 哈农",
            "拜厄钢琴教材 车尔尼 哈农",
        ]
        assert service.last_query_rewrite["node"] == "query_rewrite"
        assert service.last_query_rewrite["policy_id"] == "lexical_recall_no_inference_v1"
        assert "召回阶段的词法改写节点" in service.last_query_rewrite["policy"]
        assert service.last_query_rewrite["strategy"] == "anchor_rewrite"
        assert service.last_query_variants == provider.calls
        assert [result.title for result in results] == ["拜厄钢琴基本教程与车尔尼哈农搭配"]
        assert [node["node"] for node in service.last_trace_nodes] == [
            "query_rewrite",
            "recall",
            "ranking",
            "llm_rerank",
        ]
        assert service.last_trace_nodes[0]["policy_id"] == "lexical_recall_no_inference_v1"
        assert "召回阶段的词法改写节点" in service.last_trace_nodes[0]["policy"]
        recall_node = service.last_trace_nodes[1]
        assert recall_node["mode"] == "sequential"
        assert recall_node["attempt_count"] == 2
        assert recall_node["result_count"] == 2
        ranking_node = service.last_trace_nodes[2]
        assert ranking_node["input_count"] == 2
        assert ranking_node["output_count"] == 1
        assert ranking_node["top_results"][0]["retrieval_query"] == provider.calls[1]
        rerank_node = service.last_trace_nodes[3]
        assert rerank_node["status"] == "skipped"
        assert rerank_node["reason"] == "disabled"

    @pytest.mark.asyncio
    async def test_search_service_respects_provider_recall_query_limit(self):
        class Provider:
            def __init__(self, name, recall_query_limit):
                self.name = name
                self.recall_query_limit = recall_query_limit
                self.calls = []

            async def search(self, query, *, limit=5):
                self.calls.append(query)
                return [
                    SearchResult(
                        title=f"{self.name} 2026高口碑电影推荐 {len(self.calls)}",
                        snippet=f"{query} 电影片单。",
                        url=f"https://example.com/{self.name}/{len(self.calls)}",
                        source=self.name,
                    )
                ]

        http_provider = Provider("http", 1)
        web_provider = Provider("web", 2)
        service = SearchService(
            providers=[web_provider, http_provider],
            retry_attempts=1,
            retry_delay=0,
            min_provider_coverage=2,
            recall_max_queries=3,
        )

        await service.search("2026年最新上映的高口碑电影推荐", limit=5)

        assert len(http_provider.calls) == 1
        assert len(web_provider.calls) == 2
        assert http_provider.calls[0] == web_provider.calls[0]
        assert web_provider.calls[1] != web_provider.calls[0]

    @pytest.mark.asyncio
    async def test_search_service_discards_concurrent_recall_timeout_as_empty_results(self):
        class SlowProvider:
            name = "web"

            async def search(self, query, *, limit=5):
                await asyncio.sleep(10)
                return [
                    SearchResult(
                        title="Slow agent search result",
                        snippet=query,
                        url="https://example.com/slow",
                        source=self.name,
                    )
                ]

        class FastProvider:
            name = "bing-rss"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Fast agent search result",
                        snippet="Agent search ranking and recall.",
                        url="https://example.com/fast",
                        source=self.name,
                    )
                ]

        service = SearchService(
            providers=[SlowProvider(), FastProvider()],
            retry_attempts=1,
            retry_delay=0,
            min_provider_coverage=2,
            recall_timeout_seconds=0.01,
        )

        results = await service.search("agent search", limit=1)

        assert [result.title for result in results] == ["Fast agent search result"]
        assert service.last_provider_errors == []
        recall_node = next(node for node in service.last_trace_nodes if node["node"] == "recall")
        assert recall_node["status"] == "partial"
        assert recall_node["timed_out_count"] == 1
        assert any(attempt["status"] == "timed_out" for attempt in recall_node["attempts"])

    @pytest.mark.asyncio
    async def test_search_service_treats_sequential_recall_timeout_as_empty_results(self):
        class SlowProvider:
            name = "web"

            async def search(self, query, *, limit=5):
                await asyncio.sleep(10)
                return [
                    SearchResult(
                        title="Slow agent search result",
                        snippet=query,
                        url="https://example.com/slow",
                        source=self.name,
                    )
                ]

        service = SearchService(
            providers=[SlowProvider()],
            retry_attempts=1,
            retry_delay=0,
            recall_timeout_seconds=0.01,
        )

        results = await service.search("agent search", limit=1)

        assert results == []
        assert service.last_provider_errors == []
        recall_node = next(node for node in service.last_trace_nodes if node["node"] == "recall")
        assert recall_node["status"] == "partial"
        assert recall_node["timed_out_count"] == 1

    @pytest.mark.asyncio
    async def test_search_service_raises_when_multi_query_provider_fails(self):
        class FailingProvider:
            name = "web"
            recall_query_limit = 2

            async def search(self, query, *, limit=5):
                raise RuntimeError(f"blocked: {query}")

        service = SearchService(
            providers=[FailingProvider()],
            retry_attempts=1,
            retry_delay=0,
            recall_max_queries=2,
        )

        with pytest.raises(RuntimeError) as exc:
            await service.search("2026年最新上映的高口碑电影推荐", limit=3)

        assert "web: blocked" in str(exc.value)
        assert len(service.last_provider_errors) == 2

    @pytest.mark.asyncio
    async def test_search_service_web_alias_continues_after_low_relevance_results(self):
        class NoisyWebProvider:
            name = "web"

            def __init__(self):
                self.calls = 0

            async def search(self, query, *, limit=5):
                self.calls += 1
                return [
                    SearchResult(
                        title=f"2026 Calendar {index}",
                        snippet="Public holidays and yearly calendar.",
                        url=f"https://example.com/calendar/{index}",
                        source=self.name,
                    )
                    for index in range(limit)
                ]

        class RelevantMCPProvider:
            name = "minimax-mcp"

            def __init__(self):
                self.calls = 0

            async def search(self, query, *, limit=5):
                self.calls += 1
                await asyncio.sleep(0.01)
                return [
                    SearchResult(
                        title=f"2026最新上映高口碑电影推荐 {index}",
                        snippet="电影片单、口碑和上映信息。",
                        url=f"https://example.com/movie/{index}",
                        source=self.name,
                    )
                    for index in range(limit)
                ]

        class BingProvider:
            name = "bing-rss"

            def __init__(self):
                self.calls = 0
                self.cancelled = False

            async def search(self, query, *, limit=5):
                self.calls += 1
                try:
                    await asyncio.sleep(10)
                except asyncio.CancelledError:
                    self.cancelled = True
                    raise
                return []

        mcp = RelevantMCPProvider()
        bing = BingProvider()
        web = NoisyWebProvider()
        service = SearchService(
            providers=[bing, mcp, web],
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search(
            "2026年最新上映的高口碑电影推荐",
            sources=["web"],
            limit=3,
        )

        assert [result.source for result in results] == ["minimax-mcp"] * 3
        assert web.calls == 1
        assert mcp.calls == 1
        assert bing.calls == 1
        assert bing.cancelled

    @pytest.mark.asyncio
    async def test_search_skill_uses_service(self, monkeypatch):
        seen = {}

        class FakeService:
            provider_names = ["fake"]

            async def search(
                self,
                query,
                *,
                sources=None,
                limit=5,
                include_images=False,
                image_limit=3,
            ):
                seen.update(
                    {
                        "limit": limit,
                        "include_images": include_images,
                        "image_limit": image_limit,
                    }
                )
                return [
                    SearchResult(
                        title="Result",
                        snippet=query,
                        url="https://example.com",
                        source="fake",
                        metadata={"thumbnail_url": "https://example.com/result-thumb.jpg"},
                    )
                ]

        monkeypatch.setattr(
            SearchService,
            "from_runtime_config",
            classmethod(lambda cls: FakeService()),
        )

        result = await self.skill.execute(query="agent memory", limit=99)

        assert result.success is True
        assert result.data["results"][0]["title"] == "Result"
        assert result.data["results"][0]["thumbnail_url"] == "https://example.com/result-thumb.jpg"
        assert result.data["results"][0]["image_url"] == "https://example.com/result-thumb.jpg"
        assert result.data["results"][0]["media_url"] == "https://example.com/result-thumb.jpg"
        assert result.data["results"][0]["media_type"] == "image"
        assert result.data["image_count"] == 1
        assert result.data["opened_results"] == 0
        assert "Result" in result.display_text
        assert seen == {
            "limit": 20,
            "include_images": True,
            "image_limit": 3,
        }

    @pytest.mark.asyncio
    async def test_search_skill_opens_pure_url_without_search_provider(self, monkeypatch):
        async def fake_open_url(self, url, *, max_chars=6000):
            return WebPageContent(
                url=url,
                final_url=url,
                title="菜鸟做贡献 自己翻译的dunlop护养说明",
                description="Dunlop 护养说明",
                content="01 指板清洁与预备剂。02 指板深度护养剂。",
                content_type="text/html",
                status_code=200,
                metadata={
                    "thumbnail_url": "https://news.guitarschina.com/images/dunlop.jpg",
                    "image_url": "https://news.guitarschina.com/images/dunlop.jpg",
                    "media_url": "https://news.guitarschina.com/images/dunlop.jpg",
                    "media_type": "image",
                },
            )

        async def fake_validate_image(self, url):
            return url

        monkeypatch.setattr(SearchService, "open_url", fake_open_url)
        monkeypatch.setattr(WebPageReader, "validate_image", fake_validate_image)

        result = await self.skill.execute(
            query="【https://news.guitarschina.com/?p=7569】",
            page_chars=6000,
        )

        assert result.success is True
        assert result.data["direct_url_open"] is True
        assert result.data["sources"] == ["direct-url"]
        assert result.data["opened_results"] == 1
        assert result.data["results"][0]["url"] == "https://news.guitarschina.com/?p=7569"
        assert result.data["results"][0]["image_url"] == (
            "https://news.guitarschina.com/images/dunlop.jpg"
        )
        assert result.data["results"][0]["media_type"] == "image"
        assert result.data["image_count"] == 1
        assert "dunlop" in result.data["results"][0]["title"].lower()

    @pytest.mark.asyncio
    async def test_search_skill_direct_url_removes_unreachable_page_image(self, monkeypatch):
        bad_image = "https://cdn.example.com/unreachable-direct.jpg"

        async def fake_open_url(self, url, *, max_chars=6000):
            return WebPageContent(
                url=url,
                final_url=url,
                title="Direct URL validation",
                description=f"Description before {bad_image} description after.",
                content=f"Content before {bad_image} content after.",
                content_type="text/html",
                status_code=200,
                metadata={
                    "thumbnail_url": bad_image,
                    "image_url": bad_image,
                    "media_url": bad_image,
                    "media_type": "image",
                },
            )

        async def reject_image(self, url):
            raise ValueError("image returned 404")

        monkeypatch.setattr(SearchService, "open_url", fake_open_url)
        monkeypatch.setattr(WebPageReader, "validate_image", reject_image)

        result = await self.skill.execute(query="https://example.com/direct")

        assert result.success is True
        assert result.data["image_count"] == 0
        assert result.data["results"][0]["image_url"] == ""
        serialized = json.dumps(result.data)
        assert bad_image not in serialized
        assert "Description before  description after." in result.data[
            "results"
        ][0]["snippet"]
        assert result.data["search_trace"][-1]["invalid_count"] == 1

    @pytest.mark.asyncio
    async def test_search_skill_direct_url_omits_images_when_disabled(self, monkeypatch):
        page_image = "https://cdn.example.com/direct-disabled.jpg"

        async def fake_open_url(self, url, *, max_chars=6000):
            return WebPageContent(
                url=url,
                final_url=url,
                title="Direct image disabled",
                description=f"Keep before {page_image} keep after.",
                content="Readable direct page.",
                content_type="text/html",
                status_code=200,
                metadata={
                    "thumbnail_url": page_image,
                    "image_url": page_image,
                    "media_url": page_image,
                    "media_type": "image",
                },
            )

        async def should_not_validate(self, url):
            raise AssertionError("include_images=false should not fetch the image")

        monkeypatch.setattr(SearchService, "open_url", fake_open_url)
        monkeypatch.setattr(WebPageReader, "validate_image", should_not_validate)

        result = await self.skill.execute(
            query="https://example.com/direct-disabled",
            include_images=False,
        )

        assert result.success is True
        assert result.data["image_count"] == 0
        assert page_image not in json.dumps(result.data)
        assert "Keep before  keep after." in result.data["results"][0]["snippet"]
        assert all(
            node["node"] != "image_enrichment"
            for node in result.data["search_trace"]
        )

    @pytest.mark.asyncio
    async def test_search_skill_normalizes_sources_and_open_options(self, monkeypatch):
        seen = {}

        class FakeService:
            provider_names = ["web"]
            last_provider_errors = []
            last_query_variants = ["agent search"]
            last_trace_nodes = [
                {
                    "node": "query_rewrite",
                    "status": "completed",
                    "strategy": "keyword_recall",
                    "original_query": "agent search",
                    "queries": ["agent search"],
                    "query_count": 1,
                },
                {
                    "node": "recall",
                    "status": "completed",
                    "providers": ["web"],
                    "attempt_count": 1,
                    "result_count": 1,
                },
            ]

            async def search(
                self,
                query,
                *,
                sources=None,
                limit=5,
                open_results=False,
                open_limit=3,
                page_chars=6000,
                include_images=False,
                image_limit=3,
            ):
                seen.update(
                    {
                        "query": query,
                        "sources": sources,
                        "limit": limit,
                        "open_results": open_results,
                        "open_limit": open_limit,
                        "page_chars": page_chars,
                        "include_images": include_images,
                        "image_limit": image_limit,
                    }
                )
                return [
                    SearchResult(
                        title="Opened Result",
                        snippet=query,
                        url="https://example.com/opened",
                        source="web",
                        metadata={"page": {"title": "Opened"}},
                    )
                ]

        monkeypatch.setattr(
            SearchService,
            "from_runtime_config",
            classmethod(lambda cls: FakeService()),
        )

        result = await self.skill.execute(
            query="agent search",
            sources=[" WEB ", "bing-rss"],
            limit=999,
            open_results="yes",
            include_images="off",
            image_limit=99,
            open_limit=99,
            page_chars=20,
        )

        assert result.success is True
        assert seen == {
            "query": "agent search",
            "sources": ["WEB", "bing-rss"],
            "limit": 20,
            "open_results": True,
            "open_limit": 3,
            "page_chars": 500,
            "include_images": False,
            "image_limit": 5,
        }
        assert result.data["query_variants"] == ["agent search"]
        assert [node["node"] for node in result.data["search_trace"]] == [
            "query_rewrite",
            "recall",
        ]
        assert result.data["opened_results"] == 1

    @pytest.mark.asyncio
    async def test_search_skill_failure_includes_query_variants_and_provider_errors(self, monkeypatch):
        class FakeService:
            provider_names = ["web"]
            last_provider_errors = ["web: blocked"]
            last_query_variants = ["original query", "variant query"]

            async def search(
                self,
                query,
                *,
                sources=None,
                limit=5,
                include_images=False,
                image_limit=3,
            ):
                raise RuntimeError("network blocked")

        monkeypatch.setattr(
            SearchService,
            "from_runtime_config",
            classmethod(lambda cls: FakeService()),
        )

        result = await self.skill.execute(query="original query")

        assert result.success is False
        assert "network blocked" in result.error
        assert result.data["query"] == "original query"
        assert result.data["query_variants"] == ["original query", "variant query"]
        assert result.data["provider_errors"] == ["web: blocked"]

    @pytest.mark.asyncio
    async def test_search_skill_includes_provider_errors_on_success(self, monkeypatch):
        class FakeService:
            provider_names = ["web", "bing-rss"]
            last_provider_errors = ["web: blocked"]

            async def search(
                self,
                query,
                *,
                sources=None,
                limit=5,
                include_images=False,
                image_limit=3,
            ):
                return [
                    SearchResult(
                        title="Fallback Result",
                        snippet=query,
                        url="https://example.com/fallback",
                        source="bing-rss",
                    )
                ]

        monkeypatch.setattr(
            SearchService,
            "from_runtime_config",
            classmethod(lambda cls: FakeService()),
        )

        result = await self.skill.execute(query="agent memory")

        assert result.success is True
        assert result.data["provider_errors"] == ["web: blocked"]

    @pytest.mark.asyncio
    async def test_web_page_reader_extracts_html(self):
        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text="""
                <html>
                  <head>
                    <title>Example Article</title>
                    <meta name="description" content="Short summary.">
                    <meta property="article:published_time" content="2026-07-26T08:30:00Z">
                    <script>ignoreMe()</script>
                  </head>
                  <body>
                    <article>
                      <h1>Example Article</h1>
                      <p>First paragraph with useful details.</p>
                      <p>Second paragraph.</p>
                    </article>
                  </body>
                </html>
                """,
            )

        reader = WebPageReader(transport=httpx.MockTransport(handler))

        page = await reader.open("https://example.com/article", max_chars=1000)

        assert page.title == "Example Article"
        assert page.description == "Short summary."
        assert page.metadata["published_at"] == "2026-07-26T08:30:00Z"
        assert "First paragraph with useful details." in page.content
        assert "ignoreMe" not in page.content

    @pytest.mark.asyncio
    async def test_web_page_reader_extracts_json_ld_published_date(self):
        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="""
                <html>
                  <head>
                    <title>JSON-LD Article</title>
                    <script type="application/ld+json">
                      {"@type":"NewsArticle","datePublished":"2026-07-25T09:15:00Z"}
                    </script>
                  </head>
                  <body><article>Verified article body.</article></body>
                </html>
                """,
            )

        reader = WebPageReader(transport=httpx.MockTransport(handler))
        page = await reader.open("https://example.com/json-ld-article")

        assert page.metadata["published_at"] == "2026-07-25T09:15:00Z"
        assert "datePublished" not in page.content

    @pytest.mark.parametrize(
        ("head_markup", "expected_image_url"),
        [
            (
                """
                <meta name="twitter:image" content="/fallback/twitter.jpg">
                <base href="/article-assets/">
                <meta property="og:image" content="hero.webp">
                """,
                "https://example.com/article-assets/hero.webp",
            ),
            (
                '<meta name="twitter:image" content="../images/twitter-card.png">',
                "https://example.com/images/twitter-card.png",
            ),
            (
                '<link rel="alternate image_src" href="//cdn.example.com/cards/link-card.jpg">',
                "https://cdn.example.com/cards/link-card.jpg",
            ),
            (
                """
                <meta property="og:image" content="data:image/png;base64,invalid">
                <meta name="twitter:image" content="/fallback/valid.jpg">
                """,
                "https://example.com/fallback/valid.jpg",
            ),
        ],
    )
    @pytest.mark.asyncio
    async def test_web_page_reader_extracts_and_resolves_page_images(
        self,
        head_markup,
        expected_image_url,
    ):
        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=f"""
                <html>
                  <head>
                    <title>Image metadata</title>
                    {head_markup}
                  </head>
                  <body><p>Readable body.</p></body>
                </html>
                """,
            )

        reader = WebPageReader(transport=httpx.MockTransport(handler))

        page = await reader.open("https://example.com/articles/story", max_chars=1000)
        media = await reader.open_media("https://example.com/articles/story")

        assert page.metadata["thumbnail_url"] == expected_image_url
        assert page.metadata["image_url"] == expected_image_url
        assert page.metadata["media_url"] == expected_image_url
        assert page.metadata["media_type"] == "image"
        assert media["thumbnail_url"] == expected_image_url
        assert media["image_url"] == expected_image_url
        assert media["media_url"] == expected_image_url
        assert media["media_type"] == "image"
        assert media["_image_candidates"][0] == expected_image_url

    @pytest.mark.asyncio
    async def test_web_page_media_reader_rejects_private_redirects(self):
        seen_urls = []

        def handler(request):
            seen_urls.append(str(request.url))
            return httpx.Response(
                302,
                headers={"location": "http://127.0.0.1/private-preview"},
            )

        reader = WebPageReader(transport=httpx.MockTransport(handler))

        with pytest.raises(ValueError, match="Private or local"):
            await reader.open_media("https://example.com/article")

        assert seen_urls == ["https://example.com/article"]

    @pytest.mark.asyncio
    async def test_web_page_image_validator_accepts_octet_stream_jpeg(self):
        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "application/octet-stream"},
                content=b"\xff\xd8\xff\xe0validated-jpeg",
            )

        reader = WebPageReader(transport=httpx.MockTransport(handler))

        validated_url = await reader.validate_image(
            "https://cdn.example.com/signed-image?id=123"
        )

        assert validated_url == "https://cdn.example.com/signed-image?id=123"

    @pytest.mark.asyncio
    async def test_web_page_image_validator_rejects_non_image_and_private_redirect(self):
        seen_urls = []

        def handler(request):
            seen_urls.append(str(request.url))
            if request.url.path == "/redirect":
                return httpx.Response(
                    302,
                    headers={"location": "http://127.0.0.1/private-image"},
                )
            return httpx.Response(
                200,
                headers={"content-type": "application/xml"},
                content=b"<?xml version='1.0'?><Error>missing</Error>",
            )

        reader = WebPageReader(transport=httpx.MockTransport(handler))

        with pytest.raises(ValueError, match="Unsupported image content type"):
            await reader.validate_image("https://example.com/not-an-image")
        with pytest.raises(ValueError, match="Private or local"):
            await reader.validate_image("https://example.com/redirect")

        assert seen_urls == [
            "https://example.com/not-an-image",
            "https://example.com/redirect",
        ]

    @pytest.mark.asyncio
    async def test_search_service_opens_result_pages(self):
        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Result",
                        snippet="",
                        url="https://example.com/article",
                        source=self.name,
                        metadata={
                            "thumbnail_url": "https://example.com/search-thumb.jpg",
                        },
                    )
                ]

        def handler(request):
            if request.url.path.endswith((".jpg", ".webp", ".png")):
                return httpx.Response(
                    200,
                    headers={"content-type": "image/jpeg"},
                    content=b"\xff\xd8\xff\xe0validated-image",
                )
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text=(
                    "<html><head><title>Opened</title>"
                    '<meta property="og:image" content="/images/opened-hero.jpg">'
                    '<meta property="article:published_time" content="2026-07-26T08:30:00Z">'
                    "</head><body><p>Opened page body.</p></body></html>"
                ),
            )

        service = SearchService(
            providers=[Provider()],
            page_reader=WebPageReader(transport=httpx.MockTransport(handler)),
        )

        results = await service.search("details", limit=1, open_results=True)

        assert results[0].metadata["page"]["title"] == "Opened"
        assert "Opened page body." in results[0].metadata["page"]["content"]
        assert results[0].metadata["published_at"] == "2026-07-26T08:30:00Z"
        assert results[0].thumbnail_url == "https://example.com/images/opened-hero.jpg"
        assert results[0].image_url == "https://example.com/images/opened-hero.jpg"
        assert results[0].media_url == "https://example.com/images/opened-hero.jpg"
        assert results[0].media_type == "image"
        assert results[0].metadata["image_url"] == "https://example.com/images/opened-hero.jpg"
        assert [node["node"] for node in service.last_trace_nodes] == [
            "query_rewrite",
            "recall",
            "ranking",
            "llm_rerank",
            "open_results",
            "image_enrichment",
        ]
        open_node = service.last_trace_nodes[-2]
        assert open_node["opened_count"] == 1
        assert open_node["error_count"] == 0
        image_node = service.last_trace_nodes[-1]
        assert image_node["probed_count"] == 1
        assert image_node["validated_count"] == 1
        assert image_node["invalid_count"] == 0

    @pytest.mark.asyncio
    async def test_search_service_enriches_only_missing_images_with_bounded_concurrency(self):
        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Agent image existing",
                        snippet="Agent image result.",
                        url="https://example.com/existing",
                        source=self.name,
                        thumbnail_url="https://example.com/existing.jpg",
                    ),
                    SearchResult(
                        title="Agent image first missing",
                        snippet="Agent image result.",
                        url="https://example.com/first",
                        source=self.name,
                    ),
                    SearchResult(
                        title="Agent image second missing",
                        snippet="Agent image result.",
                        url="https://example.com/second",
                        source=self.name,
                    ),
                    SearchResult(
                        title="Agent image beyond limit",
                        snippet="Agent image result.",
                        url="https://example.com/beyond",
                        source=self.name,
                    ),
                ]

        class MediaReader:
            def __init__(self):
                self.requested = []
                self.validated = []
                self.active = 0
                self.max_active = 0

            async def open_media(self, url):
                self.requested.append(url)
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                await asyncio.sleep(0)
                self.active -= 1
                if url.endswith("/first"):
                    return {
                        "thumbnail_url": "https://example.com/first.jpg",
                        "image_url": "https://example.com/first.jpg",
                        "media_url": "https://example.com/first.jpg",
                        "media_type": "image",
                    }
                return {}

            async def validate_image(self, url):
                self.validated.append(url)
                self.active += 1
                self.max_active = max(self.max_active, self.active)
                await asyncio.sleep(0)
                self.active -= 1
                return url

        reader = MediaReader()
        service = SearchService(
            providers=[Provider()],
            page_reader=reader,
        )

        results = await service.search(
            "agent image",
            limit=4,
            include_images=True,
            image_limit=2,
        )

        by_url = {result.url: result for result in results}
        assert reader.requested == ["https://example.com/first"]
        assert reader.validated == [
            "https://example.com/existing.jpg",
            "https://example.com/first.jpg",
        ]
        assert reader.max_active == 2
        assert by_url["https://example.com/existing"].thumbnail_url.endswith("existing.jpg")
        assert by_url["https://example.com/first"].image_url.endswith("first.jpg")
        assert by_url["https://example.com/second"].image_url == ""
        assert by_url["https://example.com/beyond"].image_url == ""
        assert all("page" not in result.metadata for result in results)

        image_node = service.last_trace_nodes[-1]
        assert image_node["node"] == "image_enrichment"
        assert image_node["candidate_count"] == 4
        assert image_node["probed_count"] == 2
        assert image_node["enriched_count"] == 2
        assert image_node["validated_count"] == 2
        assert image_node["invalid_count"] == 0
        assert image_node["image_count"] == 2
        assert image_node["error_count"] == 0

    @pytest.mark.asyncio
    async def test_search_service_validates_images_and_continues_until_target(self):
        bad_provider = "https://cdn.example.com/bad-provider.jpg"
        bad_og = "https://cdn.example.com/bad-og.jpg"
        bad_second = "https://cdn.example.com/bad-second.jpg"
        good_first = "https://cdn.example.com/good-first"
        good_third = "https://cdn.example.com/good-third"

        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Image validation first",
                        snippet=f"Keep before {bad_provider} keep after.",
                        url="https://example.com/first",
                        source=self.name,
                        thumbnail_url=bad_provider,
                        metadata={
                            "page": {
                                "content": f"Nested before {bad_provider} nested after.",
                                "metadata": {
                                    "pagemap": {
                                        "cse_thumbnail": [{"src": bad_provider}]
                                    }
                                },
                            }
                        },
                    ),
                    SearchResult(
                        title="Image validation second",
                        snippet="Image validation candidate.",
                        url="https://example.com/second",
                        source=self.name,
                    ),
                    SearchResult(
                        title="Image validation third",
                        snippet="Image validation candidate.",
                        url="https://example.com/third",
                        source=self.name,
                    ),
                ]

        def handler(request):
            path = request.url.path
            if path == "/first":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text=(
                        "<html><head>"
                        f'<meta property="og:image" content="{bad_og}">'
                        f'<meta name="twitter:image" content="{good_first}">'
                        "</head></html>"
                    ),
                )
            if path == "/second":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text=(
                        "<html><head>"
                        f'<meta property="og:image" content="{bad_second}">'
                        "</head></html>"
                    ),
                )
            if path == "/third":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text=(
                        "<html><head>"
                        f'<meta property="og:image" content="{good_third}">'
                        "</head></html>"
                    ),
                )
            if path in {
                "/bad-provider.jpg",
                "/bad-og.jpg",
                "/bad-second.jpg",
            }:
                return httpx.Response(
                    404,
                    headers={"content-type": "application/xml"},
                    content=b"<Error>missing</Error>",
                )
            if path == "/good-first":
                return httpx.Response(
                    200,
                    headers={"content-type": "image/png"},
                    content=b"\x89PNG\r\n\x1a\nvalidated-png",
                )
            if path == "/good-third":
                return httpx.Response(
                    200,
                    headers={"content-type": "application/octet-stream"},
                    content=b"\xff\xd8\xff\xe0validated-jpeg",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        service = SearchService(
            providers=[Provider()],
            page_reader=WebPageReader(transport=httpx.MockTransport(handler)),
        )

        results = await service.search(
            "image validation",
            limit=3,
            include_images=True,
            image_limit=2,
        )

        by_url = {result.url: result for result in results}
        assert by_url["https://example.com/first"].image_url == good_first
        assert by_url["https://example.com/second"].image_url == ""
        assert by_url["https://example.com/third"].image_url == good_third
        serialized = json.dumps(
            [result.model_dump(mode="json") for result in results]
        )
        assert bad_provider not in serialized
        assert "Keep before  keep after." in by_url[
            "https://example.com/first"
        ].snippet
        assert "Nested before  nested after." in by_url[
            "https://example.com/first"
        ].metadata["page"]["content"]

        image_node = service.last_trace_nodes[-1]
        assert image_node["candidate_count"] == 3
        assert image_node["probed_count"] == 3
        assert image_node["validated_count"] == 2
        assert image_node["enriched_count"] == 2
        assert image_node["invalid_count"] == 3
        assert image_node["validation_attempt_count"] == 5
        assert image_node["image_count"] == 2

    @pytest.mark.asyncio
    async def test_search_service_scrubs_unselected_initial_image_candidates(self):
        valid_image = "https://cdn.example.com/selected.jpg"
        unselected_image = "https://cdn.example.com/unselected.jpg"

        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Initial image candidates",
                        snippet=f"Keep before {unselected_image} keep after.",
                        url="https://example.com/candidates",
                        source=self.name,
                        metadata={
                            "images": [valid_image, unselected_image],
                            "rich_snippet": {"top": unselected_image},
                        },
                    )
                ]

        class MediaReader:
            async def validate_image(self, url):
                assert url == valid_image
                return url

            async def open_media(self, url):
                raise AssertionError("A valid provider image should skip page discovery")

        service = SearchService(
            providers=[Provider()],
            page_reader=MediaReader(),
        )

        results = await service.search(
            "initial image candidates",
            limit=1,
            include_images=True,
            image_limit=1,
        )

        serialized = json.dumps(results[0].model_dump(mode="json"))
        assert results[0].image_url == valid_image
        assert valid_image in serialized
        assert unselected_image not in serialized
        assert "Keep before  keep after." in results[0].snippet

    @pytest.mark.asyncio
    async def test_search_service_validates_and_scrubs_images_found_only_in_text(self):
        bad_image = "https://cdn.example.com/signed-preview?id=dead"
        article_url = "https://example.com/ordinary-article.html"

        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Text image validation",
                        snippet=(
                            f"Keep markdown ![preview]({bad_image}) and "
                            f"ordinary article {article_url}."
                        ),
                        url="https://example.com/text-image",
                        source=self.name,
                        metadata={
                            "page": {
                                "description": "Keep this page description.",
                                "content": (
                                    f"Keep HTML <img src='{bad_image}'> content."
                                ),
                            }
                        },
                    )
                ]

        class MediaReader:
            def __init__(self):
                self.validated = []

            async def validate_image(self, url):
                self.validated.append(url)
                raise ValueError("image returned 404")

            async def open_media(self, url):
                return {}

        reader = MediaReader()
        service = SearchService(
            providers=[Provider()],
            page_reader=reader,
        )

        results = await service.search(
            "text image validation",
            limit=1,
            include_images=True,
            image_limit=1,
        )

        serialized = json.dumps(results[0].model_dump(mode="json"))
        assert reader.validated == [bad_image]
        assert bad_image not in serialized
        assert article_url in serialized
        assert "Keep markdown  and ordinary article" in results[0].snippet
        assert "![preview]" not in results[0].snippet
        assert "Keep HTML  content." in results[0].metadata[
            "page"
        ]["content"]
        assert "<img" not in results[0].metadata["page"]["content"]
        assert service.last_trace_nodes[-1]["invalid_count"] == 1

    @pytest.mark.asyncio
    async def test_open_results_removes_rejected_image_urls_from_page_content(self):
        bad_image = "https://cdn.example.com/dead-preview.jpg"

        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Open image validation",
                        snippet=f"Summary before {bad_image} summary after.",
                        url="https://example.com/open-result",
                        source=self.name,
                    )
                ]

        def handler(request):
            if request.url.path == "/open-result":
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html"},
                    text=(
                        "<html><head>"
                        f'<meta property="og:image" content="{bad_image}">'
                        "</head><body><article>"
                        f"Page before {bad_image} page after."
                        "</article></body></html>"
                    ),
                )
            if request.url.path == "/dead-preview.jpg":
                return httpx.Response(
                    404,
                    headers={"content-type": "application/xml"},
                    content=b"<Error>missing</Error>",
                )
            raise AssertionError(f"Unexpected URL: {request.url}")

        service = SearchService(
            providers=[Provider()],
            page_reader=WebPageReader(transport=httpx.MockTransport(handler)),
        )

        results = await service.search(
            "open image validation",
            limit=1,
            open_results=True,
            include_images=False,
        )

        result = results[0]
        serialized = json.dumps(result.model_dump(mode="json"))
        assert bad_image not in serialized
        assert "Summary before  summary after." in result.snippet
        assert "Page before  page after." in result.metadata["page"]["content"]
        assert result.image_url == ""
        assert service.last_trace_nodes[-1]["invalid_count"] == 1

    @pytest.mark.asyncio
    async def test_search_service_records_open_errors_and_skips_private_urls(self):
        class Provider:
            name = "web"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title="Agent details public",
                        snippet="Agent details.",
                        url="https://example.com/broken",
                        source=self.name,
                    ),
                    SearchResult(
                        title="Agent details local",
                        snippet="Agent details.",
                        url="http://localhost/private",
                        source=self.name,
                    ),
                ]

        def handler(request):
            return httpx.Response(500, text="server error")

        service = SearchService(
            providers=[Provider()],
            page_reader=WebPageReader(transport=httpx.MockTransport(handler)),
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search(
            "agent details",
            limit=2,
            open_results=True,
            open_limit=3,
        )

        by_url = {result.url: result for result in results}
        assert "500 Internal Server Error" in by_url["https://example.com/broken"].metadata["page"]["error"]
        assert "page" not in by_url["http://localhost/private"].metadata

    @pytest.mark.asyncio
    async def test_search_skill_reports_missing_provider(self, monkeypatch):
        monkeypatch.setattr(
            SearchService,
            "from_runtime_config",
            classmethod(lambda cls: SearchService()),
        )

        result = await self.skill.execute(query="agent memory")

        assert result.success is False
        assert "No search providers" in result.error

    def test_minimax_mcp_payload_to_search_results(self):
        provider = MiniMaxMCPSearchProvider(api_key="test-key")

        assert provider._args == ["--with", "mcp<2", "minimax-coding-plan-mcp", "-y"]

        results = provider._coerce_payload(
            {
                "organic": [
                    {
                        "title": "MiniMax MCP Docs",
                        "link": "https://platform.minimaxi.com/docs/token-plan/mcp-guide",
                        "snippet": "Token Plan MCP provides web_search.",
                        "date": "2026-06-18",
                        "thumbnail": "https://example.com/thumb.jpg",
                        "video_url": "https://example.com/demo.mp4",
                    }
                ],
                "base_resp": {"status_code": 0, "status_msg": "success"},
            },
            limit=5,
        )

        assert len(results) == 1
        assert results[0].title == "MiniMax MCP Docs"
        assert results[0].url == "https://platform.minimaxi.com/docs/token-plan/mcp-guide"
        assert results[0].source == "minimax-mcp"
        assert results[0].metadata["date"] == "2026-06-18"
        assert results[0].metadata["thumbnail_url"] == "https://example.com/thumb.jpg"
        assert results[0].metadata["image_url"] == "https://example.com/thumb.jpg"
        assert results[0].metadata["video_url"] == "https://example.com/demo.mp4"
        assert results[0].metadata["media_type"] == "video"
        assert results[0].thumbnail_url == "https://example.com/thumb.jpg"
        assert results[0].image_url == "https://example.com/thumb.jpg"
        assert results[0].media_url == "https://example.com/demo.mp4"
        assert results[0].media_type == "video"

    @pytest.mark.asyncio
    async def test_minimax_mcp_allows_large_stdio_responses(self, monkeypatch):
        provider = MiniMaxMCPSearchProvider(api_key="test-key")
        captured = {}
        proc = object()

        async def fake_create_subprocess_exec(*args, **kwargs):
            captured.update(kwargs)
            return proc

        async def fake_mcp_request(_proc, *, request_id, method, params):
            if request_id == 1:
                return {"result": {}}
            return {
                "result": {
                    "content": [
                        {"type": "text", "text": '{"organic": []}'},
                    ]
                }
            }

        async def no_op(*args, **kwargs):
            return None

        monkeypatch.setattr(asyncio, "create_subprocess_exec", fake_create_subprocess_exec)
        monkeypatch.setattr(provider, "_mcp_request", fake_mcp_request)
        monkeypatch.setattr(provider, "_mcp_notification", no_op)
        monkeypatch.setattr(provider, "_stop_process", no_op)

        payload = await provider._call_web_search("latest AI agent news")

        assert payload == {"organic": []}
        assert captured["limit"] == 4 * 1024 * 1024

    def test_search_service_registers_minimax_mcp_provider(self):
        keys = [
            "llm.minimax.api_key",
            "search.minimax.enabled",
            "search.minimax.command",
            "search.minimax.args",
            "search.web.enabled",
        ]
        previous = {key: runtime_config.get(key) for key in keys}
        try:
            runtime_config.update(
                {
                    "llm.minimax.api_key": "test-key",
                    "search.minimax.enabled": "true",
                    "search.minimax.command": "uvx",
                    "search.minimax.args": '["minimax-coding-plan-mcp","-y"]',
                    "search.web.enabled": "false",
                }
            )

            service = SearchService.from_runtime_config()

            assert "minimax-mcp" in service.provider_names
            provider = next(item for item in service._providers if item.name == "minimax-mcp")
            assert provider._args == ["--with", "mcp<2", "minimax-coding-plan-mcp", "-y"]
        finally:
            runtime_config.update(previous)

    def test_search_service_from_runtime_config_reads_broad_retrieval_settings(self):
        keys = [
            "llm.minimax.api_key",
            "search.bing.enabled",
            "search.local.documents",
            "search.minimax.enabled",
            "search.min_provider_coverage",
            "search.provider_limit_multiplier",
            "search.recall.max_queries",
            "search.recall.timeout_seconds",
            "search.rewrite.enabled",
            "search.rewrite.max_queries",
            "search.rewrite.provider",
            "search.rewrite.timeout_seconds",
            "search.rerank.enabled",
            "search.rerank.max_candidates",
            "search.rerank.min_score",
            "search.rerank.provider",
            "search.rerank.timeout_seconds",
            "search.web.enabled",
        ]
        previous = {key: runtime_config.get(key) for key in keys}
        try:
            runtime_config.update(
                {
                    "llm.minimax.api_key": "",
                    "search.bing.enabled": "false",
                    "search.local.documents": '[{"title":"Runtime Search","content":"runtime config search quality"}]',
                    "search.minimax.enabled": "false",
                    "search.min_provider_coverage": "4",
                    "search.provider_limit_multiplier": "3",
                    "search.recall.max_queries": "5",
                    "search.recall.timeout_seconds": "12.5",
                    "search.rewrite.enabled": "false",
                    "search.rewrite.max_queries": "6",
                    "search.rewrite.provider": "minimax",
                    "search.rewrite.timeout_seconds": "9",
                    "search.rerank.enabled": "false",
                    "search.rerank.max_candidates": "7",
                    "search.rerank.min_score": "0.42",
                    "search.rerank.provider": "minimax",
                    "search.rerank.timeout_seconds": "8",
                    "search.web.enabled": "false",
                }
            )

            service = SearchService.from_runtime_config()

            assert service.provider_names == ["local"]
            assert service._min_provider_coverage == 4
            assert service._provider_limit_multiplier == 3
            assert service._recall_max_queries == 5
            assert service._recall_timeout_seconds == 12.5
            assert service._query_rewriter is None
            assert service._reranker is None
        finally:
            runtime_config.update(previous)


class TestOpenURLSkill:
    def setup_method(self):
        self.skill = OpenURLSkill()

    def test_metadata(self):
        meta = self.skill.metadata()
        assert meta.name == "open_url"
        assert "先调用 search" in meta.description
        assert "官方" in meta.description
        assert "高可信 URL" in meta.description
        assert {p.name for p in meta.parameters} == {"url", "max_chars"}

    @pytest.mark.asyncio
    async def test_execute_uses_page_reader(self, monkeypatch):
        async def fake_open_url(self, url, *, max_chars=6000):
            return WebPageContent(
                url=url,
                final_url=url,
                title="Opened Page",
                content="Readable page content.",
                content_type="text/html",
                status_code=200,
            )

        monkeypatch.setattr(SearchService, "open_url", fake_open_url)

        result = await self.skill.execute(url="https://example.com/page")

        assert result.success is True
        assert result.data["page"]["title"] == "Opened Page"
        assert "Readable page content." in result.display_text

    @pytest.mark.asyncio
    async def test_execute_reports_silent_network_errors(self, monkeypatch):
        class SilentConnectError(Exception):
            def __str__(self):
                return ""

        class EndOfStream(Exception):
            def __str__(self):
                return ""

        async def fake_open_url(self, url, *, max_chars=6000):
            try:
                raise SilentConnectError(EndOfStream())
            except SilentConnectError as cause:
                raise SilentConnectError() from cause

        monkeypatch.setattr(SearchService, "open_url", fake_open_url)

        result = await self.skill.execute(url="https://example.com/page")

        assert result.success is False
        assert "Open URL failed: SilentConnectError" in result.error
        assert "EndOfStream" in result.error


class TestDriveSkills:
    def client(self, handler):
        return DriveGatewayClient(
            "http://gateway.test",
            transport=httpx.MockTransport(handler),
        )

    @pytest.mark.asyncio
    async def test_ls_resolves_drive_path_with_engine_user_context(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-User-ID"] == "alice"
            if request.method == "GET" and request.url.path == "/api/drive/tree":
                return httpx.Response(
                    200,
                    json={
                        "flat_items": [
                            {"id": "root", "parent_id": "", "type": "folder", "name": "我的网盘"},
                            {"id": "folder-1", "parent_id": "root", "type": "folder", "name": "Research"},
                            {"id": "file-1", "parent_id": "folder-1", "type": "file", "name": "Notes.md", "size": 12},
                        ]
                    },
                )
            if request.method == "GET" and request.url.path == "/api/drive/items":
                assert request.url.params.get("parent_id") == "folder-1"
                return httpx.Response(
                    200,
                    json={"items": [{"id": "file-1", "parent_id": "folder-1", "type": "file", "name": "Notes.md", "size": 12}]},
                )
            return httpx.Response(404, json={"error": "not found"})

        skill = DriveListSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(path="/Research", _user_id="alice")

        assert result.success is True
        assert result.data["folder"]["id"] == "folder-1"
        assert result.data["items"][0]["name"] == "Notes.md"
        assert "Notes.md" in result.display_text

    @pytest.mark.asyncio
    async def test_search_drive_uses_gateway_search(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-User-ID"] == "alice"
            assert request.url.path == "/api/drive/search"
            assert request.url.params.get("q") == "embedding"
            return httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "item": {"id": "file-1", "type": "file", "name": "RAG.md", "size": 42},
                            "score": 10,
                            "snippet": "embedding search",
                        }
                    ]
                },
            )

        skill = DriveSearchSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(query="embedding", _user_id="alice")

        assert result.success is True
        assert result.data["results"][0]["item"]["id"] == "file-1"
        assert "embedding search" in result.display_text

    @pytest.mark.asyncio
    async def test_read_drive_returns_text_content(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-User-ID"] == "alice"
            assert request.method == "GET"
            assert request.url.path == "/api/drive/items/file-1"
            return httpx.Response(
                200,
                json={
                    "item": {
                        "id": "file-1",
                        "parent_id": "folder-1",
                        "type": "file",
                        "name": "Notes.md",
                        "content": "Readable drive content.",
                        "size": 23,
                    }
                },
            )

        skill = DriveReadSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(item_id="file-1", _user_id="alice")

        assert result.success is True
        assert result.data["content"] == "Readable drive content."
        assert "Readable drive content." in result.display_text

    @pytest.mark.asyncio
    async def test_read_drive_returns_extracted_binary_document_text(self):
        async def handler(request: httpx.Request) -> httpx.Response:
            assert request.url.path == "/api/drive/items/file-pdf"
            return httpx.Response(
                200,
                json={
                    "item": {
                        "id": "file-pdf",
                        "type": "file",
                        "name": "Contract.pdf",
                        "mime_type": "application/pdf",
                        "encoding": "base64",
                        "content": "JVBERi0xLjQ=",
                        "extracted_text": "Parsed contract clause.",
                        "extraction_status": "completed",
                        "extraction_metadata": {"page_count": 1},
                    }
                },
            )

        skill = DriveReadSkill(client_factory=lambda: self.client(handler))
        result = await skill.execute(item_id="file-pdf", _user_id="alice")

        assert result.success is True
        assert result.data["content"] == "Parsed contract clause."
        assert result.data["encoding"] == "base64"
        assert result.data["extraction_status"] == "completed"
        assert "JVBERi0xLjQ=" not in result.display_text

    @pytest.mark.asyncio
    async def test_read_drive_resolves_display_path_and_returns_item_path(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-User-ID"] == "alice"
            if request.method == "GET" and request.url.path == "/api/drive/tree":
                return httpx.Response(
                    200,
                    json={
                        "flat_items": [
                            {"id": "root", "parent_id": "", "type": "folder", "name": "我的网盘"},
                            {"id": "folder-1", "parent_id": "root", "type": "folder", "name": "knowledge"},
                            {"id": "file-1", "parent_id": "folder-1", "type": "file", "name": "Notes.md", "size": 12},
                        ]
                    },
                )
            if request.method == "GET" and request.url.path == "/api/drive/items/file-1":
                return httpx.Response(
                    200,
                    json={
                        "item": {
                            "id": "file-1",
                            "parent_id": "folder-1",
                            "type": "file",
                            "name": "Notes.md",
                            "content": "Readable drive content.",
                            "size": 23,
                        }
                    },
                )
            return httpx.Response(404, json={"error": "not found"})

        skill = DriveReadSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(path="`我的网盘 / knowledge / Notes.md`", _user_id="alice")

        assert result.success is True
        assert result.data["item"]["path"] == "/knowledge/Notes.md"
        assert result.data["content"] == "Readable drive content."

    @pytest.mark.asyncio
    async def test_save_drive_injects_user_id_into_gateway_body(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.headers["X-User-ID"] == "bob"
            if request.method == "GET" and request.url.path == "/api/drive/tree":
                return httpx.Response(
                    200,
                    json={
                        "flat_items": [
                            {"id": "root", "parent_id": "", "type": "folder", "name": "我的网盘"},
                            {"id": "folder-1", "parent_id": "root", "type": "folder", "name": "Notes"},
                        ]
                    },
                )
            if request.method == "GET" and request.url.path == "/api/drive/items":
                assert request.url.params.get("parent_id") == "folder-1"
                return httpx.Response(200, json={"items": []})
            if request.method == "POST" and request.url.path == "/api/drive/files":
                captured.update(json.loads(request.content.decode("utf-8")))
                return httpx.Response(
                    201,
                    json={
                        "item": {
                            "id": "file-2",
                            "parent_id": "folder-1",
                            "type": "file",
                            "name": "todo.md",
                            "content": "write me",
                            "size": 8,
                        }
                    },
                )
            return httpx.Response(404, json={"error": "not found"})

        skill = DriveSaveSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(path="/Notes/todo.md", content="write me", _user_id="bob")

        assert result.success is True
        assert captured["user_id"] == "bob"
        assert captured["parent_id"] == "folder-1"
        assert captured["name"] == "todo.md"
        assert captured["content"] == "write me"

    @pytest.mark.asyncio
    async def test_save_drive_defaults_to_knowledge_folder_and_creates_it(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/api/drive/tree":
                return httpx.Response(
                    200,
                    json={
                        "flat_items": [
                            {"id": "root", "parent_id": "", "type": "folder", "name": "我的网盘"},
                        ]
                    },
                )
            if request.method == "GET" and request.url.path == "/api/drive/items":
                return httpx.Response(200, json={"items": []})
            if request.method == "POST" and request.url.path == "/api/drive/folders":
                body = json.loads(request.content.decode("utf-8"))
                assert body["parent_id"] == "root"
                assert body["name"] == "知识库"
                return httpx.Response(
                    201,
                    json={
                        "item": {
                            "id": "knowledge",
                            "parent_id": "root",
                            "type": "folder",
                            "name": "知识库",
                        }
                    },
                )
            if request.method == "POST" and request.url.path == "/api/drive/files":
                captured.update(json.loads(request.content.decode("utf-8")))
                return httpx.Response(
                    201,
                    json={
                        "item": {
                            "id": "qa-file",
                            "parent_id": "knowledge",
                            "type": "file",
                            "name": "qa.md",
                            "content": "# Q&A",
                            "size": 5,
                        }
                    },
                )
            return httpx.Response(404, json={"error": "not found"})

        skill = DriveSaveSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(name="qa.md", content="# Q&A", _user_id="alice")

        assert result.success is True
        assert captured["parent_id"] == "knowledge"
        assert captured["name"] == "qa.md"

    @pytest.mark.asyncio
    async def test_update_drive_updates_file_by_path(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/api/drive/tree":
                return httpx.Response(
                    200,
                    json={
                        "flat_items": [
                            {"id": "root", "parent_id": "", "type": "folder", "name": "我的网盘"},
                            {"id": "knowledge", "parent_id": "root", "type": "folder", "name": "知识库"},
                            {"id": "file-1", "parent_id": "knowledge", "type": "file", "name": "old.md"},
                        ]
                    },
                )
            if request.method == "PUT" and request.url.path == "/api/drive/items/file-1":
                captured.update(json.loads(request.content.decode("utf-8")))
                return httpx.Response(
                    200,
                    json={
                        "item": {
                            "id": "file-1",
                            "parent_id": "knowledge",
                            "type": "file",
                            "name": "new.md",
                            "content": "# New",
                            "summary": "updated",
                            "tags": ["知识"],
                            "size": 5,
                        }
                    },
                )
            return httpx.Response(404, json={"error": "not found"})

        skill = DriveUpdateSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(
            path="/知识库/old.md",
            name="new.md",
            content="# New",
            summary="updated",
            tags="知识",
            _user_id="alice",
        )

        assert result.success is True
        assert captured["user_id"] == "alice"
        assert captured["name"] == "new.md"
        assert captured["content"] == "# New"
        assert captured["tags"] == ["知识"]
        assert result.data["item"]["path"] == "/知识库/new.md"

    @pytest.mark.asyncio
    async def test_delete_drive_resolves_path_and_deletes_item(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append((request.method, request.url.path))
            if request.method == "GET" and request.url.path == "/api/drive/tree":
                return httpx.Response(
                    200,
                    json={
                        "flat_items": [
                            {"id": "root", "parent_id": "", "type": "folder", "name": "我的网盘"},
                            {"id": "file-1", "parent_id": "root", "type": "file", "name": "old.md"},
                        ]
                    },
                )
            if request.method == "DELETE" and request.url.path == "/api/drive/items/file-1":
                return httpx.Response(200, json={"status": "deleted"})
            return httpx.Response(404, json={"error": "not found"})

        skill = DriveDeleteSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(path="/old.md", _user_id="alice")

        assert result.success is True
        assert result.data["deleted"]["id"] == "file-1"
        assert ("DELETE", "/api/drive/items/file-1") in requests

    @pytest.mark.asyncio
    async def test_share_drive_returns_public_url(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/api/drive/items/file-1":
                return httpx.Response(
                    200,
                    json={"item": {"id": "file-1", "parent_id": "root", "type": "file", "name": "notes.md"}},
                )
            if request.method == "PUT" and request.url.path == "/api/drive/items/file-1/share":
                body = json.loads(request.content.decode("utf-8"))
                assert body["enabled"] is True
                return httpx.Response(
                    200,
                    json={
                        "item": {
                            "id": "file-1",
                            "parent_id": "root",
                            "type": "file",
                            "name": "notes.md",
                            "share_enabled": True,
                            "share_token": "token-1",
                        }
                    },
                )
            if request.method == "GET" and request.url.path == "/api/drive/tree":
                return httpx.Response(
                    200,
                    json={
                        "flat_items": [
                            {"id": "root", "parent_id": "", "type": "folder", "name": "我的网盘"},
                            {"id": "file-1", "parent_id": "root", "type": "file", "name": "notes.md"},
                        ]
                    },
                )
            return httpx.Response(404, json={"error": "not found"})

        skill = DriveShareSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(item_id="file-1", enabled=True, _user_id="alice")

        assert result.success is True
        assert result.data["share_url"] == "http://gateway.test/share/drive/token-1"

    @pytest.mark.asyncio
    async def test_archive_url_to_drive_saves_markdown_in_knowledge_folder(self):
        captured = {}

        class FakeSearch:
            async def open_url(self, url, *, max_chars):
                assert url == "https://example.com/article"
                assert max_chars == 12000
                return WebPageContent(
                    url=url,
                    final_url=url,
                    title="Example Article",
                    description="A useful page",
                    content="Readable article body.",
                    content_type="text/html",
                    status_code=200,
                )

        def handler(request: httpx.Request) -> httpx.Response:
            if request.method == "GET" and request.url.path == "/api/drive/tree":
                return httpx.Response(
                    200,
                    json={
                        "flat_items": [
                            {"id": "root", "parent_id": "", "type": "folder", "name": "我的网盘"},
                        ]
                    },
                )
            if request.method == "GET" and request.url.path == "/api/drive/items":
                return httpx.Response(200, json={"items": []})
            if request.method == "POST" and request.url.path == "/api/drive/folders":
                body = json.loads(request.content.decode("utf-8"))
                folder_id = "knowledge" if body["name"] == "知识库" else "archive"
                parent_id = "root" if body["name"] == "知识库" else "knowledge"
                return httpx.Response(
                    201,
                    json={"item": {"id": folder_id, "parent_id": parent_id, "type": "folder", "name": body["name"]}},
                )
            if request.method == "POST" and request.url.path == "/api/drive/files":
                captured.update(json.loads(request.content.decode("utf-8")))
                return httpx.Response(
                    201,
                    json={
                        "item": {
                            "id": "archive-file",
                            "parent_id": "archive",
                            "type": "file",
                            "name": captured["name"],
                            "mime_type": captured["mime_type"],
                            "summary": captured["summary"],
                            "size": len(captured["content"]),
                        }
                    },
                )
            return httpx.Response(404, json={"error": "not found"})

        skill = ArchiveURLToDriveSkill(
            client_factory=lambda: self.client(handler),
            search_factory=FakeSearch,
        )
        assert skill.metadata().default_policy == "auto"

        result = await skill.execute(
            url="https://example.com/article",
            name="example.md",
            _user_id="alice",
        )

        assert result.success is True
        assert captured["parent_id"] == "archive"
        assert captured["name"] == "example.md"
        assert "# Example Article" in captured["content"]
        assert "https://example.com/article" in captured["content"]
        assert "Readable article body." in captured["content"]


class TestPulseSkills:
    def client(self, handler):
        return PulseGatewayClient(
            "http://gateway.test",
            transport=httpx.MockTransport(handler),
        )

    @pytest.mark.asyncio
    async def test_get_pulse_returns_ranked_recommendations(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/pulse"
            assert request.url.params.get("date") == "2026-07-16"
            assert request.headers["X-User-ID"] == "alice"
            return httpx.Response(
                200,
                json={
                    "date": "2026-07-16",
                    "generated_at": "2026-07-16T08:00:00Z",
                    "refreshing": False,
                    "candidate_count": 20,
                    "recommended_count": 1,
                    "topics": [
                        {
                            "id": "topic-1",
                            "name": "AI Agent",
                            "keywords": ["Agent"],
                        }
                    ],
                    "modules": [
                        {
                            "key": "topic_hot",
                            "title": "关注 Topic",
                            "summary": "今日追踪",
                            "items": [{"id": "pulse-1"}],
                        }
                    ],
                    "items": [
                        {
                            "id": "pulse-1",
                            "date": "2026-07-16",
                            "topic_id": "topic-1",
                            "topic_name": "AI Agent",
                            "source": "topic_hot",
                            "title": "Agent 产品出现新进展",
                            "summary": "值得关注的新变化。",
                            "heat_score": 88,
                            "detail": {
                                "recommendation_reason": "匹配订阅 Topic",
                                "key_points": ["产品", "生态"],
                                "suggested_questions": ["有哪些变化？"],
                                "news_sources": [
                                    {
                                        "title": "Official update",
                                        "url": "https://example.com/update",
                                        "source": "official",
                                    }
                                ],
                            },
                        }
                    ],
                },
            )

        skill = PulseGetSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(date="2026-07-16", _user_id="alice")

        assert result.success is True
        assert result.data["items"][0]["title"] == "Agent 产品出现新进展"
        assert result.data["items"][0]["news_sources"][0]["url"] == "https://example.com/update"
        assert "Agent 产品出现新进展" in result.display_text

    @pytest.mark.asyncio
    async def test_refresh_pulse_waits_and_returns_new_feed(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/pulse/refresh"
            captured.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "date": "2026-07-16",
                    "refreshing": False,
                    "items": [
                        {
                            "id": "pulse-1",
                            "title": "刷新后的推荐",
                            "summary": "新内容",
                            "heat_score": 90,
                            "detail": {},
                        }
                    ],
                },
            )

        skill = PulseRefreshSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(date="2026-07-16", wait=True, _user_id="alice")

        assert result.success is True
        assert captured["user_id"] == "alice"
        assert captured["date"] == "2026-07-16"
        assert captured["wait"] is True
        assert result.data["waited"] is True
        assert "Refreshed Pulse" in result.display_text

    @pytest.mark.asyncio
    async def test_list_pulse_topics_returns_existing_topics(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/pulse/topics"
            return httpx.Response(
                200,
                json={
                    "topics": [
                        {"id": "topic-1", "name": "AI", "keywords": ["Agent"]},
                    ]
                },
            )

        skill = PulseListTopicsSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(_user_id="alice")

        assert result.success is True
        assert result.data["total"] == 1
        assert result.data["topics"][0]["name"] == "AI"
        assert "id" not in result.data["topics"][0]

    @pytest.mark.asyncio
    async def test_upsert_pulse_topic_prepares_unique_prefix_for_approval(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/pulse/topics"
            assert request.headers["X-User-ID"] == "alice"
            return httpx.Response(
                200,
                json={
                    "topics": [
                        {
                            "id": "c16e9bfc-3165-41d9-86be-14631e245253",
                            "name": "AI热门新闻",
                            "keywords": ["AI"],
                        },
                        {
                            "id": "f2e3dbf9-5b68-420d-b25f-7f66f9060843",
                            "name": "大模型产品动态",
                            "keywords": ["模型发布"],
                        },
                    ]
                },
            )

        skill = PulseUpsertTopicSkill(client_factory=lambda: self.client(handler))
        prepared = await skill.prepare_arguments(
            topic_id="c16e9bfc",
            _user_id="alice",
        )

        assert prepared["topic_id"] == "c16e9bfc-3165-41d9-86be-14631e245253"
        assert prepared["name"] == "AI热门新闻"
        assert prepared["_user_id"] == "alice"

    @pytest.mark.asyncio
    async def test_upsert_pulse_topic_rejects_missing_or_ambiguous_prefix(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "topics": [
                        {"id": "abcddcba-1111-4111-8111-111111111111", "name": "One"},
                        {"id": "abcddcba-2222-4222-8222-222222222222", "name": "Two"},
                    ]
                },
            )

        skill = PulseUpsertTopicSkill(client_factory=lambda: self.client(handler))

        with pytest.raises(ValueError, match="ambiguous"):
            await skill.prepare_arguments(topic_id="abcddcba", _user_id="alice")
        with pytest.raises(ValueError, match="not found"):
            await skill.prepare_arguments(topic_id="deadbeef", _user_id="alice")

    @pytest.mark.asyncio
    async def test_upsert_pulse_topic_resolves_original_name_for_rename(self):
        def handler(_: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "topics": [
                        {
                            "id": "c16e9bfc-3165-41d9-86be-14631e245253",
                            "name": "旧名称",
                            "keywords": ["Agent"],
                        }
                    ]
                },
            )

        skill = PulseUpsertTopicSkill(client_factory=lambda: self.client(handler))
        prepared = await skill.prepare_arguments(
            original_name="旧名称",
            name="新名称",
            _user_id="alice",
        )

        assert prepared["topic_id"] == "c16e9bfc-3165-41d9-86be-14631e245253"
        assert prepared["original_name"] == "旧名称"
        assert prepared["name"] == "新名称"

    @pytest.mark.asyncio
    async def test_upsert_pulse_topic_creates_and_updates(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            body = json.loads(request.content.decode("utf-8"))
            requests.append((request.method, request.url.path, body))
            if request.method == "POST":
                return httpx.Response(
                    201,
                    json={
                        "topic": {
                            "id": "topic-1",
                            "name": body["name"],
                            "keywords": body["keywords"],
                        }
                    },
                )
            return httpx.Response(
                200,
                json={
                    "topic": {
                        "id": "topic-1",
                        "name": "机器人",
                        "keywords": body["keywords"],
                    }
                },
            )

        skill = PulseUpsertTopicSkill(client_factory=lambda: self.client(handler))

        created = await skill.execute(
            name="机器人",
            keywords="具身智能、供应链，机器人;控制器",
            _user_id="alice",
        )
        updated = await skill.execute(
            topic_id="topic-1",
            keywords="具身智能",
            _user_id="alice",
        )

        assert created.success is True
        assert created.data["topic"]["keywords"] == ["具身智能", "供应链", "机器人", "控制器"]
        assert updated.success is True
        assert updated.data["topic"]["keywords"] == ["具身智能"]
        assert "enabled" not in requests[0][2]
        assert "enabled" not in requests[1][2]
        assert requests[0][0:2] == ("POST", "/api/pulse/topics")
        assert requests[1][0:2] == ("PUT", "/api/pulse/topics/topic-1")

    @pytest.mark.asyncio
    async def test_delete_pulse_topic_resolves_name_before_approval_and_deletes(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append((request.method, request.url.path))
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "topics": [
                            {
                                "id": "c16e9bfc-3165-41d9-86be-14631e245253",
                                "name": "旧关注",
                                "keywords": ["legacy"],
                            }
                        ]
                    },
                )
            return httpx.Response(200, json={"status": "deleted"})

        skill = PulseDeleteTopicSkill(client_factory=lambda: self.client(handler))
        prepared = await skill.prepare_arguments(name="旧关注", _user_id="alice")

        assert prepared["topic_id"] == "c16e9bfc-3165-41d9-86be-14631e245253"
        assert prepared["name"] == "旧关注"
        result = await skill.execute(**prepared)
        assert result.success is True
        assert result.data["deleted"]["name"] == "旧关注"
        assert "id" not in result.data["deleted"]
        assert requests == [
            ("GET", "/api/pulse/topics"),
            ("DELETE", "/api/pulse/topics/c16e9bfc-3165-41d9-86be-14631e245253"),
        ]
        assert skill.metadata().default_policy == "confirm"
        assert skill.metadata().access == "destructive"

    @pytest.mark.asyncio
    async def test_optimize_pulse_topics_returns_read_only_analysis_context(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/pulse/topic-optimization"
            assert request.url.params.get("lookback_days") == "45"
            assert request.headers["X-User-ID"] == "alice"
            return httpx.Response(
                200,
                json={
                    "lookback_days": 45,
                    "current_topics": [
                        {"id": "topic-1", "name": "AI Agent", "keywords": ["Agent"]}
                    ],
                    "candidate_interest_signals": [{"theme": "AI 应用与 Agent", "count": 3}],
                    "recent_user_intents": [{"text": "最近在研究 Agent 评测"}],
                    "history": {
                        "summary": {"sampled_cluster_count": 4},
                        "overlap_candidates": [{"left_topic_id": "topic-1", "right_topic_id": "topic-2"}],
                        "retrieval_runs": [{"id": "run-1", "query_count": 8}],
                    },
                    "workflow": {"analysis_only": True},
                },
            )

        skill = PulseOptimizeTopicsSkill(client_factory=lambda: self.client(handler))
        result = await skill.execute(lookback_days=45, _user_id="alice")

        assert result.success is True
        assert result.data["workflow"]["analysis_only"] is True
        assert result.data["current_topics"][0]["name"] == "AI Agent"
        assert "id" not in result.data["current_topics"][0]
        assert result.data["candidate_interest_signals"][0]["theme"] == "AI 应用与 Agent"
        assert result.data["topic_semantics"]["existing_topics_source"] == "current_topics_only"
        assert result.data["topic_semantics"]["management_actions"] == [
            "add",
            "update",
            "delete",
        ]
        assert result.data["history"]["summary"]["sampled_cluster_count"] == 4
        assert "left_topic_id" not in result.data["history"]["overlap_candidates"][0]
        assert "right_topic_id" not in result.data["history"]["overlap_candidates"][0]
        assert "Only current_topics are existing subscriptions" in result.display_text
        assert skill.metadata().access == "read"
        assert skill.metadata().default_policy == "auto"
        assert PulseUpsertTopicSkill().metadata().default_policy == "confirm"
        assert PulseDeleteTopicSkill().metadata().default_policy == "confirm"


class TestTodoSkills:
    def client(self, handler):
        return TodoGatewayClient(
            "http://gateway.test",
            transport=httpx.MockTransport(handler),
        )

    @pytest.mark.asyncio
    async def test_create_todo_injects_user_and_conversation_context(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "POST"
            assert request.url.path == "/api/todos"
            assert request.headers["X-User-ID"] == "alice"
            captured.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                201,
                json={
                    "todo": {
                        "id": "todo-1",
                        "title": "提交周报",
                        "status": "open",
                        "due_date": "2026-07-12",
                        "priority": "high",
                        "repeat_rule": "once",
                        "tags": ["work"],
                    }
                },
            )

        skill = TodoCreateSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(
            title="提交周报",
            due_date="2026-07-12",
            priority="high",
            tags="work",
            _user_id="alice",
            _conversation_id="conv-1",
        )

        assert result.success is True
        assert result.data["todo"]["id"] == "todo-1"
        assert captured["user_id"] == "alice"
        assert captured["origin_conversation_id"] == "conv-1"
        assert captured["title"] == "提交周报"
        assert captured["due_date"] == "2026-07-12"
        assert captured["tags"] == ["work"]
        assert "提交周报" in result.display_text

    @pytest.mark.asyncio
    async def test_list_todos_returns_candidate_ids(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/todos"
            assert request.headers["X-User-ID"] == "alice"
            assert request.url.params.get("scope") == "today"
            assert request.url.params.get("date") == "2026-07-11"
            return httpx.Response(
                200,
                json={
                    "scope": "today",
                    "date": "2026-07-11",
                    "items": [
                        {
                            "id": "todo-1",
                            "title": "提交周报",
                            "status": "open",
                            "due_date": "2026-07-11",
                            "priority": "normal",
                            "repeat_rule": "once",
                        }
                    ],
                    "counts": {"today": 1},
                },
            )

        skill = TodoListSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(scope="today", date="2026-07-11", _user_id="alice")

        assert result.success is True
        assert result.data["items"][0]["id"] == "todo-1"
        assert "todo-1" in result.display_text

    @pytest.mark.asyncio
    async def test_update_todo_marks_done(self):
        captured = {}

        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "PUT"
            assert request.url.path == "/api/todos/todo-1"
            assert request.headers["X-User-ID"] == "alice"
            captured.update(json.loads(request.content.decode("utf-8")))
            return httpx.Response(
                200,
                json={
                    "todo": {
                        "id": "todo-1",
                        "title": "提交周报",
                        "status": "done",
                        "due_date": "2026-07-11",
                        "priority": "normal",
                        "repeat_rule": "once",
                    }
                },
            )

        skill = TodoUpdateSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(todo_id="todo-1", status="completed", _user_id="alice")

        assert result.success is True
        assert captured["user_id"] == "alice"
        assert captured["status"] == "done"
        assert result.data["todo"]["status"] == "done"

    @pytest.mark.asyncio
    async def test_get_todo_returns_detail(self):
        def handler(request: httpx.Request) -> httpx.Response:
            assert request.method == "GET"
            assert request.url.path == "/api/todos/todo-1"
            return httpx.Response(
                200,
                json={
                    "todo": {
                        "id": "todo-1",
                        "title": "提交周报",
                        "status": "open",
                        "notes": "Friday",
                        "priority": "normal",
                        "repeat_rule": "once",
                    }
                },
            )

        skill = TodoGetSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(todo_id="todo-1", _user_id="alice")

        assert result.success is True
        assert result.data["todo"]["notes"] == "Friday"

    @pytest.mark.asyncio
    async def test_delete_todo_reads_then_deletes(self):
        requests = []

        def handler(request: httpx.Request) -> httpx.Response:
            requests.append((request.method, request.url.path))
            if request.method == "GET":
                return httpx.Response(
                    200,
                    json={
                        "todo": {
                            "id": "todo-1",
                            "title": "提交周报",
                            "status": "open",
                            "priority": "normal",
                            "repeat_rule": "once",
                        }
                    },
                )
            if request.method == "DELETE":
                return httpx.Response(200, json={"status": "deleted"})
            return httpx.Response(404, json={"error": "not found"})

        skill = TodoDeleteSkill(client_factory=lambda: self.client(handler))

        result = await skill.execute(todo_id="todo-1", _user_id="alice")

        assert result.success is True
        assert result.data["deleted"]["id"] == "todo-1"
        assert requests == [
            ("GET", "/api/todos/todo-1"),
            ("DELETE", "/api/todos/todo-1"),
        ]
