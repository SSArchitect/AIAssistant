"""Unit tests for builtin skills."""
import asyncio

import httpx
import pytest
from agent.skills.builtin.echo import EchoSkill
from agent.skills.builtin.datetime_skill import DateTimeSkill
from agent.skills.builtin.calculator import CalculatorSkill
from agent.skills.builtin.agent_tool import AgentToolSkill
from agent.skills.builtin.open_url import OpenURLSkill
from agent.skills.builtin.search import SearchSkill
from agent.skills.base import Skill
from agent.runtime.registry import get_agent
from agent.search import (
    BingRSSSearchProvider,
    DuckDuckGoSearchProvider,
    HTTPSearchProvider,
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

    def test_metadata_marks_terminal_routing_tool(self):
        meta = self.skill.metadata()
        assert meta.name == "weight_loss_v1"
        assert "agent" in meta.tags
        assert "terminal" in meta.tags
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
        assert result.data["terminal"] is True
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
        assert "品牌、型号、产品编号" in meta.description
        assert "药剂、清洁剂" in meta.description
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
            "open_limit",
            "page_chars",
        }

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
        from agent.search.recall import build_query_variants

        variants = build_query_variants("2026年最新上映的高口碑电影推荐", max_queries=2)
        brand_variants = build_query_variants(
            "Dunlop 6531 Fingerboard 01 Cleaner 指板清洁剂 用途",
            max_queries=2,
        )

        assert variants == [
            "2026年最新上映的高口碑电影推荐",
            "2026 最新上映 高口碑电影推荐",
        ]
        assert brand_variants == [
            "Dunlop 6531 Fingerboard 01 Cleaner 指板清洁剂 用途",
            "6531 01 dunlop fingerboard cleaner 指板清洁剂 用途",
        ]

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

            async def search(self, query, *, sources=None, limit=5):
                seen["limit"] = limit
                return [
                    SearchResult(
                        title="Result",
                        snippet=query,
                        url="https://example.com",
                        source="fake",
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
        assert "Result" in result.display_text
        assert seen["limit"] == 20

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
            )

        monkeypatch.setattr(SearchService, "open_url", fake_open_url)

        result = await self.skill.execute(
            query="【https://news.guitarschina.com/?p=7569】",
            page_chars=6000,
        )

        assert result.success is True
        assert result.data["direct_url_open"] is True
        assert result.data["sources"] == ["direct-url"]
        assert result.data["opened_results"] == 1
        assert result.data["results"][0]["url"] == "https://news.guitarschina.com/?p=7569"
        assert "dunlop" in result.data["results"][0]["title"].lower()

    @pytest.mark.asyncio
    async def test_search_skill_normalizes_sources_and_open_options(self, monkeypatch):
        seen = {}

        class FakeService:
            provider_names = ["web"]
            last_provider_errors = []
            last_query_variants = ["agent search"]

            async def search(
                self,
                query,
                *,
                sources=None,
                limit=5,
                open_results=False,
                open_limit=3,
                page_chars=6000,
            ):
                seen.update(
                    {
                        "query": query,
                        "sources": sources,
                        "limit": limit,
                        "open_results": open_results,
                        "open_limit": open_limit,
                        "page_chars": page_chars,
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
        }
        assert result.data["query_variants"] == ["agent search"]
        assert result.data["opened_results"] == 1

    @pytest.mark.asyncio
    async def test_search_skill_failure_includes_query_variants_and_provider_errors(self, monkeypatch):
        class FakeService:
            provider_names = ["web"]
            last_provider_errors = ["web: blocked"]
            last_query_variants = ["original query", "variant query"]

            async def search(self, query, *, sources=None, limit=5):
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

            async def search(self, query, *, sources=None, limit=5):
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
        assert "First paragraph with useful details." in page.content
        assert "ignoreMe" not in page.content

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
                    )
                ]

        def handler(request):
            return httpx.Response(
                200,
                headers={"content-type": "text/html"},
                text="<html><head><title>Opened</title></head><body><p>Opened page body.</p></body></html>",
            )

        service = SearchService(
            providers=[Provider()],
            page_reader=WebPageReader(transport=httpx.MockTransport(handler)),
        )

        results = await service.search("details", limit=1, open_results=True)

        assert results[0].metadata["page"]["title"] == "Opened"
        assert "Opened page body." in results[0].metadata["page"]["content"]

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
                    "search.web.enabled": "false",
                }
            )

            service = SearchService.from_runtime_config()

            assert service.provider_names == ["local"]
            assert service._min_provider_coverage == 4
            assert service._provider_limit_multiplier == 3
            assert service._recall_max_queries == 5
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
