from __future__ import annotations

from typing import Any, Callable

from agent.llm.base import ToolDefinition
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult
from agent.skills.router import ToolRouter


class ToolSearchSkill(Skill):
    """Discover tools omitted from the current compact tool set."""

    auto_discover = False

    def __init__(
        self,
        catalog_provider: Callable[[], list[ToolDefinition]],
        *,
        router: ToolRouter | None = None,
    ):
        self._catalog_provider = catalog_provider
        self._router = router or ToolRouter()

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="tool_search",
            description=(
                "搜索当前 Agent 可用但尚未暴露的工具。仅当现有工具无法完成用户请求时使用；"
                "不要把它当作网页搜索。搜索成功后，匹配工具会在下一轮真实加入可调用 schema。"
            ),
            parameters=[
                SkillParameter(
                    name="query",
                    type="string",
                    description="用一句话描述缺少的能力和目标动作，例如“读取历史会话”或“分享网盘文件”。",
                    required=True,
                    min_length=2,
                    max_length=240,
                ),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="最多返回的候选工具数，默认 5，最多 10。",
                    required=False,
                    default=5,
                    minimum=1,
                    maximum=10,
                ),
            ],
            tags=["tooling", "discovery", "router"],
            source="system",
            domains=["system"],
            routing_keywords=["工具", "能力", "tool"],
            always_on=True,
            discoverable=False,
            parallel_safe=False,
            idempotent=True,
            max_calls_per_run=4,
            output_schema={
                "type": "object",
                "properties": {
                    "matches": {"type": "array", "items": {"type": "object"}},
                    "total": {"type": "integer"},
                },
                "required": ["matches", "total"],
                "additionalProperties": False,
            },
        )

    async def execute(self, **kwargs) -> SkillResult:
        query = str(kwargs.get("query") or "").strip()
        if len(query) < 2:
            return SkillResult(
                success=False,
                error="query must contain at least 2 characters",
                error_code="invalid_arguments",
            )
        try:
            limit = max(1, min(int(kwargs.get("limit") or 5), 10))
        except (TypeError, ValueError):
            limit = 5

        allowed_names = {
            str(name).strip()
            for name in kwargs.get("_allowed_tool_names") or []
            if str(name).strip()
        }
        exposed_names = {
            str(name).strip()
            for name in kwargs.get("_exposed_tool_names") or []
            if str(name).strip()
        }
        catalog = [
            tool
            for tool in self._catalog_provider()
            if not allowed_names or tool.name in allowed_names
        ]
        matches = self._router.search(
            catalog,
            query=query,
            exclude_names=exposed_names,
            limit=limit,
        )
        return SkillResult(
            success=True,
            data={"query": query, "matches": matches, "total": len(matches)},
            display_text=(
                "\n".join(
                    f"- {item['name']}: {item['description']}"
                    for item in matches
                )
                if matches
                else "No additional matching tools were found."
            ),
        )
