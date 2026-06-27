from __future__ import annotations

from agent.search import SearchService
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


class SearchSkill(Skill):
    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="search",
            description=(
                "按关键词搜索已配置的数据源。当用户需要来自索引文档、外部 API 或后端搜索服务的信息时使用。"
                "搜索结果只是需要归因的片段；回答时引用结果 URL，不要把薄弱来源包装成已验证事实。"
                "如果仅有标题和摘要不足以回答，可设置 open_results=true 打开前几条网页读取正文。"
            ),
            parameters=[
                SkillParameter(
                    name="query",
                    type="string",
                    description="搜索关键词或自然语言查询。",
                    required=True,
                ),
                SkillParameter(
                    name="sources",
                    type="string",
                    description=(
                        "可选的来源名称，用英文逗号分隔。留空使用默认搜索；web 表示通用网络搜索。"
                        "也可以指定 local、http、bing-rss 或 minimax-mcp。"
                    ),
                    required=False,
                ),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="返回结果数量上限。默认 5；研究流程最多可请求 20。",
                    required=False,
                    default=5,
                ),
                SkillParameter(
                    name="open_results",
                    type="boolean",
                    description="是否打开前几条搜索结果读取网页正文。默认 false；需要核验网页详情时设为 true。",
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

        service = SearchService.from_runtime_config()
        if not service.provider_names:
            return SkillResult(
                success=False,
                error=(
                    "No search providers configured. Set search.local.documents, "
                    "search.http.base_url, search.minimax.enabled, or search.web.enabled."
                ),
            )

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
                    "sources": service.provider_names,
                    "provider_errors": service.last_provider_errors,
                },
            )

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
                    "results": [],
                    "sources": service.provider_names,
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
                "results": data,
                "sources": service.provider_names,
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
