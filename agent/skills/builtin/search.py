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
                    description="可选的来源名称，用英文逗号分隔，例如 local、http、minimax-mcp 或 web。",
                    required=False,
                ),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="返回结果数量上限。默认 5；研究流程最多可请求 20。",
                    required=False,
                    default=5,
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

        raw_sources = str(kwargs.get("sources") or "").strip()
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
            results = await service.search(query, sources=sources, limit=limit)
        except Exception as e:
            return SkillResult(
                success=False,
                error=f"Search failed: {e}",
                data={"query": query, "sources": service.provider_names},
            )

        data = [result.model_dump(mode="json") for result in results]
        if not results:
            return SkillResult(
                success=True,
                data={"query": query, "results": [], "sources": service.provider_names},
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
            },
            display_text="\n".join(display_lines),
        )
