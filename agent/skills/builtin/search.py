from __future__ import annotations

from agent.search import SearchService, search_result_from_page, single_public_http_url
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class SearchSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="search",
            description=(
                "默认事实检索工具；当回答需要外部知识、当前事实或可核验来源时，必须先调用 search 再回答，"
                "不要凭模型记忆裸答。覆盖场景包括可核验实体或编号、产品或服务、使用方法、"
                "维修保养、兼容性、错误码、规格、版本、价格、库存、新闻、政策、医疗、法律、"
                "金融、投资和安全风险。优先找官方、一手或高可信来源；回答时引用结果 URL，"
                "区分搜索片段和已验证正文，不要把薄弱来源包装成已验证事实。"
                "如果仅有标题和摘要不足以回答，或涉及产品说明、安全使用、维修、医疗、法律、金融等高风险细节，"
                "设置 open_results=true 打开前几条网页读取正文；也可先 search 找到官方页后再调用 open_url 核验。"
                "如果用户或查询参数已经是明确的 http/https URL，不要把 URL 当关键词搜索；应直接读取该页面正文。"
                "普通联网检索通常不要指定具体 provider；如果结果偏题，保留完整问题并加入关键实体、"
                "官方机构/站点、地区、年份、榜单或评分来源等限定词后重试，而不是只搜年份或泛词。"
                "构造 query 时只写用户表达过、上下文已给出或可机械规范化的检索词；不要把未验证的解释、"
                "归类、材质、形态、用途或结论写进 query。"
                "写作、翻译、整理用户已提供内容、情绪陪伴、纯创意和一般代码解释通常不需要搜索。"
            ),
            parameters=[
                SkillParameter(
                    name="query",
                    type="string",
                    description=(
                        "搜索关键词或自然语言查询；保留完整意图，并包含实体名、编号、错误码、版本、"
                        "地点、时间、官方机构、站点、榜单/评分来源等可核验细节。避免只用年份、"
                        "最近、最新、推荐等泛词。不要加入用户没有表达且上下文无法推出的事实或结论。"
                    ),
                    required=True,
                ),
                SkillParameter(
                    name="sources",
                    type="string",
                    description=(
                        "可选来源名称，用英文逗号分隔。普通联网检索留空或用 web；"
                        "web 表示通用网络搜索别名，会自动选择可用网页 provider。"
                        "仅调试或强制来源时指定 local、http、bing-rss 或 minimax-mcp；"
                        "不要为普通事实检索单独指定 bing-rss。"
                    ),
                    required=False,
                ),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="返回结果数量上限。默认 5；普通检索建议 5-8，研究流程最多可请求 20。",
                    required=False,
                    default=5,
                ),
                SkillParameter(
                    name="open_results",
                    type="boolean",
                    description=(
                        "是否打开前几条搜索结果读取网页正文。默认 false；需要核验官方页、产品/设备/药剂使用说明、"
                        "安全风险、维修保养、医疗、法律、金融或其他高风险细节时设为 true。"
                    ),
                    required=False,
                    default=False,
                ),
                SkillParameter(
                    name="open_limit",
                    type="integer",
                    description="open_results=true 时打开的结果数量，最多 3。默认 3。",
                    required=False,
                    default=3,
                ),
                SkillParameter(
                    name="page_chars",
                    type="integer",
                    description="每个网页正文保留字符数，默认 6000，最多 12000。",
                    required=False,
                    default=6000,
                ),
            ],
            tags=["search", "retrieval", "api"],
            source="builtin",
        )

    async def execute(self, **kwargs) -> SkillResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return SkillResult(success=False, error="query is required")

        try:
            limit = int(kwargs.get("limit") or 5)
        except (TypeError, ValueError):
            limit = 5
        limit = max(1, min(limit, 20))
        open_results = _coerce_bool(kwargs.get("open_results"), default=False)
        try:
            open_limit = int(kwargs.get("open_limit") or 3)
        except (TypeError, ValueError):
            open_limit = 3
        open_limit = max(1, min(open_limit, 3))
        try:
            page_chars = int(kwargs.get("page_chars") or 6000)
        except (TypeError, ValueError):
            page_chars = 6000
        page_chars = max(500, min(page_chars, 12000))

        raw_source_value = kwargs.get("sources")
        if isinstance(raw_source_value, list):
            raw_sources = ",".join(str(item) for item in raw_source_value)
        else:
            raw_sources = str(raw_source_value or "").strip()
        sources = [
            item.strip()
            for item in raw_sources.split(",")
            if item.strip()
        ] or None

        direct_url = single_public_http_url(query)
        if direct_url:
            query_rewrite = _direct_url_query_rewrite(query)
            search_trace = _direct_url_search_trace(query_rewrite, direct_url)
            try:
                page = await SearchService().open_url(direct_url, max_chars=page_chars)
            except Exception as e:
                return SkillResult(
                    success=False,
                    error=f"Open URL failed: {e}",
                    data={
                        "query": query,
                        "query_rewrite": query_rewrite,
                        "search_trace": search_trace,
                        "url": direct_url,
                        "direct_url_open": True,
                    },
                )
            result = search_result_from_page(page)
            return SkillResult(
                success=True,
                data={
                    "query": query,
                    "query_rewrite": query_rewrite,
                    "search_trace": search_trace,
                    "query_variants": [query],
                    "results": [result.model_dump(mode="json")],
                    "sources": ["direct-url"],
                    "provider_errors": [],
                    "opened_results": 1,
                    "direct_url_open": True,
                },
                display_text=f"1. {result.title} - {result.url}",
            )

        service = SearchService.from_runtime_config()
        if not service.provider_names:
            return SkillResult(
                success=False,
                error=(
                    "No search providers configured. Set search.local.documents, "
                    "search.http.base_url, search.minimax.enabled, or search.web.enabled."
                ),
            )

        provider_errors = getattr(service, "last_provider_errors", [])
        try:
            if open_results:
                results = await service.search(
                    query,
                    sources=sources,
                    limit=limit,
                    open_results=True,
                    open_limit=open_limit,
                    page_chars=page_chars,
                )
            else:
                results = await service.search(query, sources=sources, limit=limit)
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Search failed: {e}",
                data={
                    "query": query,
                    "query_rewrite": getattr(service, "last_query_rewrite", None) or _fallback_query_rewrite(query),
                    "search_trace": getattr(service, "last_trace_nodes", None) or _fallback_search_trace(query),
                    "query_variants": getattr(service, "last_query_variants", None) or [query],
                    "sources": service.provider_names,
                    "provider_errors": getattr(service, "last_provider_errors", provider_errors),
                },
            )
        provider_errors = getattr(service, "last_provider_errors", provider_errors)
        query_variants = getattr(service, "last_query_variants", None) or [query]
        query_rewrite = getattr(service, "last_query_rewrite", None) or _fallback_query_rewrite(query)
        search_trace = getattr(service, "last_trace_nodes", None) or _fallback_search_trace(query)

        data = [result.model_dump(mode="json") for result in results]
        opened_count = sum(
            1
            for item in data
            if isinstance(item.get("metadata"), dict)
            and isinstance(item["metadata"].get("page"), dict)
            and not item["metadata"]["page"].get("error")
        )
        if not results:
            return SkillResult(
                success=True,
                data={
                    "query": query,
                    "query_rewrite": query_rewrite,
                    "search_trace": search_trace,
                    "query_variants": query_variants,
                    "results": [],
                    "sources": service.provider_names,
                    "provider_errors": provider_errors,
                    "opened_results": 0,
                },
                display_text=f"No search results for: {query}",
            )

        display_lines = [
            f"{index + 1}. {result.title}"
            + (f" - {result.url}" if result.url else "")
            for index, result in enumerate(results)
        ]
        return SkillResult(
            success=True,
            data={
                "query": query,
                "query_rewrite": query_rewrite,
                "search_trace": search_trace,
                "query_variants": query_variants,
                "results": data,
                "sources": service.provider_names,
                "provider_errors": provider_errors,
                "opened_results": opened_count,
            },
            display_text="\n".join(display_lines),
        )


def _coerce_bool(value, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "y", "on"}:
        return True
    if normalized in {"0", "false", "no", "n", "off"}:
        return False
    return default


def _fallback_query_rewrite(query: str) -> dict:
    return {
        "node": "query_rewrite",
        "strategy": "keyword_recall",
        "original_query": query,
        "queries": [query],
    }


def _direct_url_query_rewrite(query: str) -> dict:
    return {
        "node": "query_rewrite",
        "strategy": "direct_url",
        "original_query": query,
        "queries": [query],
    }


def _fallback_search_trace(query: str) -> list[dict]:
    query_rewrite = _fallback_query_rewrite(query)
    return [
        {
            "node": "query_rewrite",
            "status": "completed",
            "strategy": query_rewrite["strategy"],
            "original_query": query,
            "queries": [query],
            "query_count": 1,
        }
    ]


def _direct_url_search_trace(query_rewrite: dict, direct_url: str) -> list[dict]:
    return [
        {
            "node": "query_rewrite",
            "status": "completed",
            "strategy": query_rewrite["strategy"],
            "original_query": query_rewrite["original_query"],
            "queries": query_rewrite["queries"],
            "query_count": 1,
        },
        {
            "node": "direct_url_open",
            "status": "completed",
            "url": direct_url,
        },
    ]
