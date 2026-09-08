import pytest

from agent.config import runtime_config
from agent.search.datapro import DataProClient
from agent.skills.builtin.dataset_search import (
    FinanceSearchSkill, CompanySearchSkill, MacroSearchSkill, VehicleSearchSkill, AcademicSearchSkill,
)
from agent.skills.builtin.professional_search import ProfessionalSearchSkill
from agent.skills.builtin.tool_search import ToolSearchSkill
from agent.skills.registry import SkillRegistry
from agent.skills.router import ToolRouter


TOOLS = [FinanceSearchSkill, CompanySearchSkill, MacroSearchSkill, VehicleSearchSkill, AcademicSearchSkill]


@pytest.fixture
def configured(monkeypatch):
    monkeypatch.setattr(runtime_config, "_data", {"llm.doubao.api_key": "test-key"})


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments,expected", [
    (FinanceSearchSkill, {"securities": ["中际旭创", "新易盛", "天孚通信"], "indicators": "市值 市盈率", "period": "2026年9月"}, "金融数据库：中际旭创；新易盛；天孚通信；指标：市值 市盈率；时间：2026年9月"),
    (CompanySearchSkill, {"companies": ["企业全称"], "dataset": "business", "query": "股东"}, "企业工商数据库：企业全称；股东"),
    (CompanySearchSkill, {"companies": ["企业全称"], "dataset": "risk", "query": "行政处罚"}, "企业风险数据库：企业全称；行政处罚"),
    (MacroSearchSkill, {"query": "中国2025年GDP"}, "宏观经济数据库：中国2025年GDP"),
    (VehicleSearchSkill, {"dataset": "configuration", "query": "理想L9 Ultra配置"}, "中国汽车车型配置库：理想L9 Ultra配置"),
    (VehicleSearchSkill, {"dataset": "sales", "query": "比亚迪汉2026年1月全国销量"}, "中国汽车品牌销量数据：比亚迪汉2026年1月全国销量"),
    (AcademicSearchSkill, {"query": "自动驾驶2025年研究论文"}, "科研学术数据搜索：自动驾驶2025年研究论文"),
])
async def test_domain_tool_builds_specific_query_and_preserves_data(configured, monkeypatch, tool, arguments, expected):
    payload = {"items": [{"table": {"value": [1.23], "unit": ["元"]}}]}
    calls = []

    class Client:
        async def search(self, query, *, limit):
            calls.append((query, limit))
            return payload

    monkeypatch.setattr(DataProClient, "from_runtime_config", classmethod(lambda cls: Client()))
    result = await tool().execute(**arguments, limit=2)
    assert result.success and result.data == payload
    assert calls == [(expected, 2)]


@pytest.mark.asyncio
@pytest.mark.parametrize("tool,arguments", [
    (FinanceSearchSkill, {"query": "CPO板块龙头股"}),
    (FinanceSearchSkill, {"securities": [], "indicators": "营收", "period": "2026"}),
    (FinanceSearchSkill, {"securities": ["a"] * 4, "indicators": "营收", "period": "2026"}),
    (FinanceSearchSkill, {"securities": [" "], "indicators": "营收", "period": "2026"}),
    (FinanceSearchSkill, {"securities": "a", "indicators": "营收", "period": "2026"}),
    (FinanceSearchSkill, {"securities": ["a"], "indicators": "营收"}),
    (FinanceSearchSkill, {"securities": ["a"], "indicators": [], "period": "2026"}),
    (CompanySearchSkill, {"companies": ["a"] * 6, "dataset": "risk", "query": "诉讼"}),
    (CompanySearchSkill, {"companies": ["a"], "dataset": "unknown", "query": "诉讼"}),
    (MacroSearchSkill, {"query": " "}),
    (VehicleSearchSkill, {"dataset": "unknown", "query": "汽车"}),
    (AcademicSearchSkill, {"query": "论文", "limit": 0}),
])
async def test_invalid_domain_arguments_fail_before_network(configured, monkeypatch, tool, arguments):
    monkeypatch.setattr(DataProClient, "from_runtime_config", classmethod(lambda cls: pytest.fail("must not request")))
    result = await tool().execute(**arguments)
    assert not result.success and result.error_code == "invalid_arguments"


def test_finance_and_company_schema_require_bounded_entity_lists(configured):
    finance = FinanceSearchSkill().to_tool_definition()["parameters"]
    assert set(finance["required"]) == {"securities", "indicators", "period"}
    assert "query" not in finance["properties"]
    assert finance["properties"]["securities"]["minItems"] == 1
    assert finance["properties"]["securities"]["maxItems"] == 3
    company = CompanySearchSkill().to_tool_definition()["parameters"]
    assert company["properties"]["companies"]["maxItems"] == 5
    assert company["properties"]["dataset"]["enum"] == ["business", "risk"]


@pytest.mark.asyncio
async def test_legacy_tool_is_available_for_compatibility_but_never_discovered(configured):
    registry = SkillRegistry()
    registry.auto_discover("agent.skills.builtin")
    catalog = registry.get_tool_definitions()
    assert registry.get("professional_search") is not None
    assert {cls.tool_name for cls in TOOLS} <= {t.name for t in catalog}
    assert not ProfessionalSearchSkill().metadata().discoverable
    for query in ["professional_search", "专业检索金融企业汽车论文", "宏观GDP"]:
        assert "professional_search" not in {t.name for t in ToolRouter().route(catalog, query=query).tools}
        found = await ToolSearchSkill(lambda: catalog).execute(query=query, limit=10)
        assert "professional_search" not in {m["name"] for m in found.data["matches"]}


@pytest.mark.asyncio
@pytest.mark.parametrize("policy", ["deny", "confirm"])
@pytest.mark.parametrize("tool", TOOLS)
async def test_split_tools_inherit_legacy_policy_unless_explicitly_overridden(configured, tool, policy):
    from agent.schemas.chat import ChatRequest
    from agent.skills.governance import ToolGovernance
    from agent.trace import TraceStore

    store = TraceStore()
    run = store.start_run(conversation_id="policy", input_text="test", agent_id="super_chat", runtime="self")
    governance = ToolGovernance(store)
    request = ChatRequest(conversation_id="policy", message="看看", tool_policies={"professional_search": policy})
    decision = governance.authorize(skill=tool(), request=request, run_id=run.run_id, arguments={})
    assert not decision.allowed and decision.policy == policy
    request.tool_policies[tool.tool_name] = "auto"
    decision = governance.authorize(skill=tool(), request=request, run_id=run.run_id, arguments={})
    assert decision.allowed


def test_legacy_disable_filters_all_domain_tools_from_catalog_and_discovery(configured):
    from agent.orchestrator.engine import AgentEngine

    registry = SkillRegistry()
    registry.auto_discover("agent.skills.builtin")
    engine = AgentEngine(registry)
    catalog = engine._tool_definitions_for_agent("super_chat", {"professional_search"})
    assert not ({"professional_search", *(cls.tool_name for cls in TOOLS)} & {t.name for t in catalog})
    catalog = engine._tool_definitions_for_agent("super_chat", {"finance_search"})
    assert "finance_search" not in {t.name for t in catalog}
    assert "company_search" in {t.name for t in catalog}


@pytest.mark.parametrize("tool", TOOLS)
def test_shared_dataset_switch_disables_every_tool(configured, tool):
    runtime_config.update({"search.datapro.enabled": "false"})
    assert not tool().metadata().enabled
