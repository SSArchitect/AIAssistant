from __future__ import annotations

from agent.search.datapro import DataProClient, DataProError, datapro_enabled
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class ProfessionalSearchSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="professional_search",
            description=(
                "专业数据检索：查询企业工商、企业风险（司法/处罚）、金融指标/行情/财报、宏观经济、"
                "汽车配置/销量和学术论文时优先使用。通过火山引擎专业数据集按 query 自动路由。"
                "query 保留公司全称或代码、指标、时间、地区、车型等用户给定条件，不添加未验证事实。"
                "金融查询必须提供具体证券名称或代码，一次最多3只；不能用板块、概念、龙头股等条件筛选证券。"
                "若要找某板块的龙头或筛选标的，先用 search 确认证券，再用本工具查指标。"
                "结果包含结构化表格和数据来源；保留统计口径、单位和时间，引用实际返回的 URL 或数据集/来源标识，"
                "无 URL 时不要编造链接或声称已打开网页。普通新闻、网页和其他事实使用 search。"
                "无结果或失败时明确说明，可再用 search 补充来源。"
            ),
            parameters=[
                SkillParameter(name="query", type="string", description="专业数据查询，明确实体、指标、时间和地区。", min_length=1),
                SkillParameter(name="limit", type="integer", description="本地保留的结果条数，不改变服务端检索或计费。", required=False, default=20, minimum=1, maximum=49),
            ],
            enabled=datapro_enabled(),
            discoverable=False,
            tags=["search", "professional", "datapro", "finance", "academic"],
            domains=["search"],
            routing_keywords=[
                "专业检索", "专业数据", "工商", "企业风险", "司法", "行政处罚", "统一信用代码",
                "股票", "财报", "季报", "金融", "宏观", "盈利", "roe", "k线", "行情",
                "汽车", "车型", "销量", "论文", "文献", "学术", "期刊",
                "官司", "诉讼", "经营状况", "股东", "法人", "统一社会信用代码",
                "营收", "净利润", "赚了多少钱", "市盈率", "市值", "净资产收益率",
                "国内生产总值", "gdp", "cpi", "pmi", "新能源车", "研究资料",
                "litigation", "revenue", "earnings", "company registry", "research literature",
                "financial", "stock", "academic", "paper", "vehicle", "datapro",
            ],
            access="external", parallel_safe=True, idempotent=True,
            max_calls_per_run=4, timeout_seconds=130,
        )

    async def execute(self, **kwargs) -> SkillResult:
        query = kwargs.get("query")
        if not isinstance(query, str) or not query.strip():
            return SkillResult(success=False, error="query is required", error_code="invalid_arguments")
        limit = kwargs.get("limit", 20)
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 49:
            return SkillResult(success=False, error="limit must be an integer from 1 to 49", error_code="invalid_arguments")
        if not datapro_enabled():
            return SkillResult(success=False, error="Professional search is disabled or missing a Volcengine API key", error_code="not_configured")
        try:
            data = await DataProClient.from_runtime_config().search(query, limit=limit)
        except DataProError as exc:
            return SkillResult(success=False, error=str(exc), error_code=exc.error_code, data=exc.data)
        return SkillResult(success=True, data=data)
