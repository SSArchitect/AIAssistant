import asyncio
import json

import httpx
import pytest

from agent.config import RuntimeConfig, runtime_config
from agent.search.datapro import DATAPRO_URL, DataProClient, DataProError
from agent.skills.builtin.professional_search import ProfessionalSearchSkill
from agent.skills.registry import SkillRegistry
from agent.skills.router import ToolRouter
from agent.skills.builtin.tool_search import ToolSearchSkill


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(runtime_config, "_data", {"llm.doubao.api_key": "volcengine-key"})


def dataset():
    return {"code": 0, "trace_id": "trace-123", "dataset_type": "macro", "items": [
        {"source_system": "IMF", "time_raw": "2018-Q1", "value": 10.043051},
        {"查询代码": "002594.SZ", "table": {"ROE": [1.65], "报告期": ["20260331"]}},
    ], "hint": "季度数据"}


def server(payload=None, *, sse=False, structured=False, tool_result=None, schema=None):
    calls = []
    def handle(request):
        assert str(request.url) == DATAPRO_URL
        assert request.headers["X-Agent-Plan-Key"] == "volcengine-key"
        assert "Authorization" not in request.headers
        assert request.headers["Accept"] == "application/json, text/event-stream"
        if request.method == "DELETE":
            assert request.headers["Mcp-Session-Id"] == "session-123"
            calls.append({"method": "DELETE"})
            return httpx.Response(204)
        body = json.loads(request.content)
        calls.append(body)
        method = body["method"]
        if method == "initialize":
            assert body["params"]["protocolVersion"] == "2025-03-26"
            result = {"protocolVersion": "2025-03-26", "capabilities": {}, "serverInfo": {"name": "datapro", "version": "1"}}
        else:
            assert request.headers["Mcp-Session-Id"] == "session-123"
            assert request.headers["MCP-Protocol-Version"] == "2025-03-26"
            if method == "notifications/initialized":
                assert "id" not in body
                return httpx.Response(202)
            if method == "tools/list":
                result = {"tools": [{"name": "dataPro_search", "inputSchema": schema if schema is not None else {
                    "type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"],
                }}]}
            else:
                assert method == "tools/call"
                assert body["params"]["name"] == "dataPro_search"
                assert set(body["params"]["arguments"]) == {"query"}
                value = payload if payload is not None else dataset()
                result = tool_result if tool_result is not None else (
                    {"structuredContent": value} if structured else {"content": [{"type": "text", "text": json.dumps(value, ensure_ascii=False)}]}
                )
        message = {"jsonrpc": "2.0", "id": body["id"], "result": result}
        headers = {"Mcp-Session-Id": "session-123"} if method == "initialize" else {}
        if sse:
            notification = {"jsonrpc": "2.0", "method": "notifications/progress", "params": {}}
            return httpx.Response(200, headers={**headers, "Content-Type": "text/event-stream"}, text=(
                ': keepalive\r\nevent: message\r\ndata: ' + json.dumps(notification) + '\r\n\r\n'
                + 'event: message\r\ndata: ' + json.dumps(message, ensure_ascii=False) + '\r\n\r\n'
            ))
        return httpx.Response(200, headers=headers, json=message)
    return httpx.MockTransport(handle), calls


@pytest.mark.asyncio
@pytest.mark.parametrize("sse", [False, True])
@pytest.mark.parametrize("structured", [False, True])
async def test_protocol_and_structured_dataset_without_urls(sse, structured):
    transport, calls = server(sse=sse, structured=structured)
    result = await DataProClient(api_key="volcengine-key", transport=transport).search(" 宏观经济季度指标 ")
    assert result["items"] == dataset()["items"]
    assert result["trace_id"] == "trace-123"
    assert result["dataset_type"] == "macro"
    assert result["source"] == "volcengine-datapro"
    assert result["truncated"] is False
    assert calls[3]["params"]["arguments"] == {"query": "宏观经济季度指标"}
    assert [call["method"] for call in calls] == ["initialize", "notifications/initialized", "tools/list", "tools/call", "DELETE"]


@pytest.mark.asyncio
async def test_local_limit_preserves_complete_rows_and_reports_truncation():
    transport, _ = server()
    result = await DataProClient(api_key="volcengine-key", transport=transport).search("财报", limit=1)
    assert result["items"] == dataset()["items"][:1]
    assert result["returned_count"] == 1
    assert result["truncated"] is True


@pytest.mark.asyncio
async def test_academic_metadata_and_empty_matches():
    for items in [[], [{"name": "Paper", "url": "https://arxiv.org/abs/1234", "abstract": "a" * 1200,
                        "extra_data": {"authors": "Author", "cite_by": 12}, "date_published": "2026-01-01"}]]:
        transport, _ = server({"code": 0, "items": items, "total": len(items)})
        result = await DataProClient(api_key="volcengine-key", transport=transport).search("学术论文")
        assert result["items"] == items
        assert result["total"] == len(items)


@pytest.mark.asyncio
async def test_live_finance_response_shape_preserves_records_and_caliber():
    payload = {"code": 0, "msg": "success", "dataset_type": "stock_finance", "items": [{
        "security_code": "000858.SZ", "records": [{
            "indicator_name": "单季度.营业收入", "value": 100.25, "unit": "元",
            "time_scope": "period", "period": {"period_id": "2026Q1", "granularity": "quarter"},
            "caliber": {"年度": "2026", "季度": "第一季度", "报表类型": "合并报表"},
        }, {"indicator_name": "业绩快报-营业收入", "value": None, "unit": "元"}],
    }]}
    transport, _ = server(payload, structured=True, sse=True)
    result = await DataProClient(api_key="volcengine-key", transport=transport).search("五粮液季度业绩季报数据", limit=1)
    assert result["items"] == payload["items"]
    assert result["truncated"] is False


@pytest.mark.asyncio
@pytest.mark.parametrize("tool_result", [
    {"isError": True, "content": [{"type": "text", "text": "volcengine-key"}]},
    {"structuredContent": {"code": 401, "msg": "volcengine-key", "items": []}},
    {"structuredContent": {"code": 0, "items": None}},
    {"structuredContent": {"code": 0, "items": [None]}},
    {"content": [{"type": "text", "text": "volcengine-key"}]},
    {"content": []},
])
async def test_safe_upstream_errors(tool_result):
    transport, calls = server(tool_result=tool_result)
    with pytest.raises(DataProError) as exc:
        await DataProClient(api_key="volcengine-key", transport=transport).search("test")
    assert "volcengine-key" not in str(exc.value)
    assert calls[-1]["method"] == "DELETE"


@pytest.mark.asyncio
@pytest.mark.parametrize("schema", [{}, {"properties": {"query": {"type": "integer"}}},
    {"properties": {"query": {"type": "string"}}, "required": ["query", "secret"]}])
async def test_changed_tool_contract_does_not_issue_paid_call(schema):
    transport, calls = server(schema=schema)
    with pytest.raises(DataProError, match="schema"):
        await DataProClient(api_key="volcengine-key", transport=transport).search("test")
    assert "tools/call" not in [c["method"] for c in calls]


@pytest.mark.asyncio
@pytest.mark.parametrize("status", [401, 403, 429, 500])
async def test_http_failures_are_safe(status):
    transport = httpx.MockTransport(lambda r: httpx.Response(status, text="volcengine-key"))
    with pytest.raises(DataProError) as exc:
        await DataProClient(api_key="volcengine-key", transport=transport).search("test")
    assert "volcengine-key" not in str(exc.value)
    assert ("authentication" if status in {401, 403} else str(status)) in str(exc.value)


@pytest.mark.asyncio
async def test_timeout_and_connection_failure():
    async def slow(request):
        await asyncio.sleep(1)
        return httpx.Response(500)
    with pytest.raises(DataProError, match="timed out"):
        await DataProClient(api_key="key", timeout=0.01, transport=httpx.MockTransport(slow)).search("test")
    def disconnected(request):
        raise httpx.ConnectError("volcengine-key", request=request)
    with pytest.raises(DataProError, match="connection failed"):
        await DataProClient(api_key="key", transport=httpx.MockTransport(disconnected)).search("test")


@pytest.mark.asyncio
@pytest.mark.parametrize("response", [
    {"jsonrpc": "2.0", "id": 1, "error": {"message": "volcengine-key"}},
    {"jsonrpc": "2.0", "id": 99, "result": {}},
    {"jsonrpc": "2.0", "id": 1, "result": []},
    [],
])
async def test_invalid_rpc(response):
    with pytest.raises(DataProError):
        await DataProClient(api_key="key", transport=httpx.MockTransport(lambda r: httpx.Response(200, json=response))).search("test")


@pytest.mark.asyncio
async def test_response_size_bound(monkeypatch):
    monkeypatch.setattr("agent.search.datapro.MAX_RESPONSE_BYTES", 100)
    transport, _ = server()
    with pytest.raises(DataProError, match="size limit"):
        await DataProClient(api_key="volcengine-key", transport=transport).search("test")


def test_key_reuse_override_and_runtime_disable(configured):
    assert DataProClient.from_runtime_config()._api_key == "volcengine-key"
    assert ProfessionalSearchSkill().metadata().enabled
    runtime_config.update({"search.datapro.api_key": "dedicated-key", "search.datapro.timeout": "30"})
    assert DataProClient.from_runtime_config()._api_key == "dedicated-key"
    assert DataProClient.from_runtime_config()._timeout == 30
    runtime_config.update({"search.datapro.enabled": "false"})
    assert not ProfessionalSearchSkill().metadata().enabled
    runtime_config.update({"search.datapro.enabled": "true", "search.datapro.api_key": "", "llm.doubao.api_key": ""})
    assert not ProfessionalSearchSkill().metadata().enabled


def test_yaml_defaults():
    config = RuntimeConfig()
    assert config.get("search.datapro.enabled") == "true"
    assert config.get("search.datapro.timeout") == "60"


@pytest.mark.asyncio
async def test_skill_uses_client_and_preserves_data(configured, monkeypatch):
    transport, _ = server()
    client = DataProClient(api_key="volcengine-key", transport=transport)
    monkeypatch.setattr(DataProClient, "from_runtime_config", classmethod(lambda cls: client))
    result = await ProfessionalSearchSkill().execute(query="金融财报", limit=2)
    assert result.success
    assert result.data["items"] == dataset()["items"]
    client._transport = httpx.MockTransport(lambda r: httpx.Response(403))
    result = await ProfessionalSearchSkill().execute(query="金融财报")
    assert not result.success and result.error_code == "professional_search_failed"
    assert "volcengine-key" not in result.error


@pytest.mark.asyncio
@pytest.mark.parametrize("kwargs", [{}, {"query": " "}, {"query": 1}, {"query": "q", "limit": 0},
    {"query": "q", "limit": 50}, {"query": "q", "limit": True}, {"query": "q", "limit": "a"}])
async def test_invalid_arguments_do_not_call_client(configured, kwargs):
    result = await ProfessionalSearchSkill().execute(**kwargs)
    assert not result.success and result.error_code == "invalid_arguments"


@pytest.mark.asyncio
async def test_disabled_skill_does_not_call_client(configured):
    runtime_config.update({"search.datapro.enabled": "false"})
    result = await ProfessionalSearchSkill().execute(query="test")
    assert not result.success and result.error_code == "not_configured"


@pytest.mark.parametrize("query", ["查企业工商信息", "比亚迪股票ROE", "宏观经济指标", "汽车车型销量", "自动驾驶学术论文"])
def test_tool_discovery_and_routing(configured, query):
    registry = SkillRegistry()
    registry.auto_discover("agent.skills.builtin")
    assert registry.get("professional_search") is not None
    routed = ToolRouter().route(registry.get_tool_definitions(), query=query)
    assert "professional_search" in {t.name for t in routed.tools}
    casual = ToolRouter().route(registry.get_tool_definitions(), query="你好")
    assert "professional_search" not in {t.name for t in casual.tools}


@pytest.mark.asyncio
@pytest.mark.parametrize("query", [
    "看看这家公司有没有官司", "比亚迪去年赚了多少钱", "新能源车卖得怎么样",
    "帮我找自动驾驶的研究资料", "查一下国内生产总值", "公司股东和经营状况",
    "上市公司净利润", "查一下GDP", "find corporate litigation data",
])
async def test_colloquial_queries_route_and_discover_professional_search(configured, query):
    registry = SkillRegistry()
    registry.auto_discover("agent.skills.builtin")
    catalog = registry.get_tool_definitions()
    route = ToolRouter().route(catalog, query=query)
    assert "professional_search" in {t.name for t in route.tools}
    found = await ToolSearchSkill(lambda: catalog).execute(query=query, limit=1)
    assert found.data["matches"][0]["name"] == "professional_search"


@pytest.mark.asyncio
async def test_tool_search_respects_exposure_and_disabled_tools(configured):
    registry = SkillRegistry()
    registry.register(ProfessionalSearchSkill())
    discovery = ToolSearchSkill(registry.get_tool_definitions)
    found = await discovery.execute(query="专业数据查询")
    assert found.data["matches"][0]["name"] == "professional_search"
    exposed = await discovery.execute(query="专业数据查询", _exposed_tool_names=["professional_search"])
    assert exposed.data["matches"] == []
    excluded = await discovery.execute(query="专业数据查询", _allowed_tool_names=["search"])
    assert excluded.data["matches"] == []
    runtime_config.update({"search.datapro.enabled": "false"})
    disabled = await discovery.execute(query="专业数据查询")
    assert disabled.data["matches"] == []


@pytest.mark.asyncio
async def test_agent_discovers_then_executes_professional_search(configured, monkeypatch):
    from unittest.mock import AsyncMock
    from agent.llm.base import LLMResponse, ToolCall
    from agent.orchestrator.engine import AgentEngine
    from agent.schemas.chat import ChatRequest

    transport, calls = server()
    client = DataProClient(api_key="volcengine-key", transport=transport)
    monkeypatch.setattr(DataProClient, "from_runtime_config", classmethod(lambda cls: client))
    registry = SkillRegistry()
    registry.register(ProfessionalSearchSkill())
    engine = AgentEngine(registry)
    provider = AsyncMock()
    provider.chat.side_effect = [
        LLMResponse(content="", tool_calls=[ToolCall(id="discover", name="tool_search", arguments={"query": "查询专业金融数据"})], model="test"),
        LLMResponse(content="", tool_calls=[ToolCall(id="retrieve", name="professional_search", arguments={"query": "比亚迪ROE", "limit": 2})], model="test"),
        LLMResponse(content="已取得数据。", model="test"),
    ]
    monkeypatch.setattr(engine, "_get_provider", lambda *args, **kwargs: provider)
    result = await engine.process(ChatRequest(conversation_id="datapro-discovery", message="请使用专用能力完成这项工作", memory_enabled=False))
    first = {t.name for t in provider.chat.await_args_list[0].kwargs["tools"]}
    second = {t.name for t in provider.chat.await_args_list[1].kwargs["tools"]}
    assert "tool_search" in first and "professional_search" not in first
    assert "professional_search" in second
    assert {"tool_search", "professional_search"}.issubset(result.skills_used)
    assert any(e.type == "tools.expanded" and "professional_search" in e.payload["added_tools"] for e in result.events)
    assert any(e.type == "tool.governance.allowed" for e in result.events)
    assert len([c for c in calls if c["method"] == "tools/call"]) == 1
    messages = provider.chat.await_args_list[2].args[0]
    assert any(m.role == "tool" and "10.043051" in str(m.content) and "002594.SZ" in str(m.content) for m in messages)
