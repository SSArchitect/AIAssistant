"""Narrow tools over the shared Volcengine professional-dataset transport."""
from __future__ import annotations

from agent.search.datapro import DataProClient, DataProError, datapro_enabled
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class _DatasetSearchSkill(Skill):
    auto_discover = False
    policy_parent = "professional_search"
    tool_name = ""
    description = ""
    keywords: list[str] = []
    array_limits: dict[str, int] = {}

    def parameters(self) -> list[SkillParameter]:
        return [SkillParameter(name="query", type="string", description="明确指标、实体、地区和时间范围的查询。", min_length=1)]

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name=self.tool_name,
            description=self.description + (
                "通过火山引擎专业数据集检索，保留原始数值、单位、时间和统计口径；"
                "引用真实 URL 或数据集来源，无 URL 时不编造链接、不声称已打开网页。"
                "缺少数据或失败时如实说明，不推断缺失数值。"
            ),
            parameters=self.parameters() + [SkillParameter(
                name="limit", type="integer", description="本地保留条数，不改变服务端查询或计费。",
                required=False, default=20, minimum=1, maximum=49,
            )],
            enabled=datapro_enabled(), tags=["search", "datapro", self.tool_name],
            domains=["search"], routing_keywords=self.keywords,
            access="external", parallel_safe=True, idempotent=True,
            max_calls_per_run=4, timeout_seconds=130,
        )

    def to_tool_definition(self) -> dict:
        definition = super().to_tool_definition()
        definition["metadata"]["policy_parent"] = self.policy_parent
        for name, maximum in self.array_limits.items():
            definition["parameters"]["properties"][name].update(minItems=1, maxItems=maximum)
        return definition

    @staticmethod
    def text(arguments: dict, name: str) -> str:
        value = arguments.get(name)
        if not isinstance(value, str) or not value.strip():
            raise ValueError(f"{name} is required and must be a non-empty string")
        return value.strip()

    def entities(self, arguments: dict, name: str) -> list[str]:
        value = arguments.get(name)
        maximum = self.array_limits[name]
        if not isinstance(value, list) or not 1 <= len(value) <= maximum:
            raise ValueError(f"{name} must contain 1 to {maximum} explicit names or codes")
        if any(not isinstance(item, str) or not item.strip() for item in value):
            raise ValueError(f"{name} must contain non-empty names or codes")
        return [item.strip() for item in value]

    def query(self, arguments: dict) -> str:
        raise NotImplementedError

    async def execute(self, **kwargs) -> SkillResult:
        try:
            query = self.query(kwargs)
            limit = kwargs.get("limit", 20)
            if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 49:
                raise ValueError("limit must be an integer from 1 to 49")
        except ValueError as error:
            return SkillResult(success=False, error=str(error), error_code="invalid_arguments")
        if not datapro_enabled():
            return SkillResult(success=False, error="Professional datasets are disabled or missing a Volcengine API key", error_code="not_configured")
        try:
            data = await DataProClient.from_runtime_config().search(query, limit=limit)
        except DataProError as error:
            return SkillResult(success=False, error=str(error), error_code=error.error_code, data=error.data)
        return SkillResult(success=True, data=data)


class FinanceSearchSkill(_DatasetSearchSkill):
    auto_discover = True
    tool_name = "finance_search"
    description = (
        "金融证券数据：仅按具体证券名称或代码查询财报、行情、估值和金融指标，一次最多3只。"
        "不支持按板块、概念或龙头股条件筛选证券；未确定标的时先用 search 确认，"
        "已在上下文确定标的则直接填入 securities。不得把‘CPO龙头股’当作证券名称。"
        "必须明确指标和时间，不将报告期、单季或累计等口径混用。"
    )
    keywords = ["金融", "股票", "证券", "财报", "季报", "半年报", "营收", "净利润", "盈利", "行情",
                "市盈率", "市值", "净资产收益率", "roe", "k线", "赚了多少钱", "龙头股",
                "financial", "finance", "stock", "revenue", "earnings"]
    array_limits = {"securities": 3}

    def parameters(self) -> list[SkillParameter]:
        return [
            SkillParameter(name="securities", type="array", description="1–3 个已确定的证券名称或代码，不能填板块/筛选条件。", items={"type": "string", "minLength": 1}),
            SkillParameter(name="indicators", type="string", description="具体指标，如营业收入、归母净利润、市值、市盈率。", min_length=1),
            SkillParameter(name="period", type="string", description="明确日期或报告期，如2026年半年报、2026年9月8日。", min_length=1),
        ]

    def query(self, arguments: dict) -> str:
        securities = self.entities(arguments, "securities")
        indicators = self.text(arguments, "indicators")
        period = self.text(arguments, "period")
        return f"金融数据库：{'；'.join(securities)}；指标：{indicators}；时间：{period}"


class CompanySearchSkill(_DatasetSearchSkill):
    auto_discover = True
    tool_name = "company_search"
    description = "企业数据：按公司全称或统一社会信用代码查询工商/股东/经营信息，或司法诉讼/行政处罚等企业风险，一次最多5家。上市证券财务指标使用 finance_search。"
    keywords = ["工商", "企业风险", "司法", "行政处罚", "信用代码", "官司", "诉讼", "经营状况", "股东", "法人", "litigation", "company registry"]
    array_limits = {"companies": 5}

    def parameters(self) -> list[SkillParameter]:
        return [
            SkillParameter(name="companies", type="array", description="1–5 家企业全称或统一社会信用代码，避免简称。", items={"type": "string", "minLength": 1}),
            SkillParameter(name="dataset", type="string", description="business：工商经营；risk：司法/行政处罚等风险。", enum=["business", "risk"]),
            SkillParameter(name="query", type="string", description="需要查询的信息维度及时间范围。", min_length=1),
        ]

    def query(self, arguments: dict) -> str:
        companies = self.entities(arguments, "companies")
        dataset = arguments.get("dataset")
        if dataset not in ("business", "risk"):
            raise ValueError("dataset must be business or risk")
        prefix = "企业工商数据库" if dataset == "business" else "企业风险数据库"
        return f"{prefix}：{'；'.join(companies)}；{self.text(arguments, 'query')}"


class MacroSearchSkill(_DatasetSearchSkill):
    auto_discover = True
    tool_name = "macro_search"
    description = "宏观经济数据：查询国家/地区、产业链和经济指标时序；query 应明确指标、地域、时间和单位，单次最多10个指标。具体股票财务数据使用 finance_search。"
    keywords = ["宏观", "国内生产总值", "gdp", "cpi", "pmi", "通胀", "失业率", "macro", "inflation"]

    def query(self, arguments: dict) -> str:
        return "宏观经济数据库：" + self.text(arguments, "query")


class VehicleSearchSkill(_DatasetSearchSkill):
    auto_discover = True
    tool_name = "vehicle_search"
    description = "中国汽车数据：configuration 查询车型参数配置，单次最多5款；sales 查询品牌/车型销量，单次最多3个车系或车型、6个月。query 明确品牌、车型、版本；销量另需明确地域和时间。"
    keywords = ["汽车", "车型", "销量", "新能源车", "车身尺寸", "vehicle", "car sales"]

    def parameters(self) -> list[SkillParameter]:
        return [SkillParameter(name="dataset", type="string", description="configuration：汽车配置；sales：汽车销量。", enum=["configuration", "sales"]), *super().parameters()]

    def query(self, arguments: dict) -> str:
        dataset = arguments.get("dataset")
        if dataset not in ("configuration", "sales"):
            raise ValueError("dataset must be configuration or sales")
        prefix = "中国汽车车型配置库" if dataset == "configuration" else "中国汽车品牌销量数据"
        return prefix + "：" + self.text(arguments, "query")


class AcademicSearchSkill(_DatasetSearchSkill):
    auto_discover = True
    tool_name = "academic_search"
    description = "科研学术检索：查海外英文学术论文、科研期刊、文献和研究资料；query 明确研究方向和检索条件，最多49篇。对已有文本润色、改写不需要检索。"
    keywords = ["论文", "文献", "学术", "期刊", "研究资料", "academic", "paper", "research literature"]

    def query(self, arguments: dict) -> str:
        return "科研学术数据搜索：" + self.text(arguments, "query")
