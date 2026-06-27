"""Unit tests for builtin skills."""
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
    async def test_search_service_treats_web_source_as_generic_web_alias(self):
        class SlowMCPProvider:
            name = "minimax-mcp"

            def __init__(self):
                self.calls = 0

            async def search(self, query, *, limit=5):
                self.calls += 1
                raise RuntimeError("should not be needed when bing has enough results")

        class BingProvider:
            name = "bing-rss"

            async def search(self, query, *, limit=5):
                return [
                    SearchResult(
                        title=f"Bing Result {index}",
                        snippet=query,
                        url=f"https://example.com/{index}",
                        source=self.name,
                    )
                    for index in range(limit)
                ]

        mcp = SlowMCPProvider()
        service = SearchService(
            providers=[mcp, BingProvider()],
            retry_attempts=1,
            retry_delay=0,
        )

        results = await service.search("炝锅面教程", sources=["web"], limit=3)

        assert len(results) == 3
        assert {result.source for result in results} == {"bing-rss"}
        assert mcp.calls == 0

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


class TestOpenURLSkill:
    def setup_method(self):
        self.skill = OpenURLSkill()

    def test_metadata(self):
        meta = self.skill.metadata()
        assert meta.name == "open_url"
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
