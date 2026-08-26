from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Iterable

from agent.llm.base import ToolDefinition


DEFAULT_MAX_DYNAMIC_TOOLS = 3
DEFAULT_MIN_DYNAMIC_SCORE = 60
CORE_ALWAYS_ON_TOOL_NAMES = {
    "open_url",
    "search",
    "tool_search",
}

_DOMAIN_TRIGGERS: dict[str, tuple[str, ...]] = {
    "drive": (
        "网盘", "drive", "知识库", "文件夹", "文件", "文档", "保存", "归档",
        "上传", "复制文件", "移动文件", "分享文件", "pdf", "docx", "pptx", "xlsx",
    ),
    "todo": (
        "待办", "todo", "提醒我", "记一下", "任务", "截止", "完成任务",
        "安排", "日程", "明天做", "今天做",
    ),
    "pulse": (
        "pulse", "值得关注", "今日推荐", "资讯推荐", "关注方向", "订阅主题",
        "热点推荐", "今天看什么", "信息簇", "优化订阅", "优化 topic",
    ),
    "image": (
        "生图", "生成图片", "生成一个图", "画图", "做图", "图给我", "对比图",
        "信息图", "图表", "可视化", "海报", "封面", "配图", "视觉设计",
        "image generation", "poster", "cover image", "infographic", "chart",
    ),
    "weight_loss": (
        "减肥", "减脂", "热量", "卡路里", "体重", "饮食记录", "运动记录",
        "热量缺口", "营养", "bmi", "calorie", "weight loss",
    ),
}


@dataclass(frozen=True)
class ToolRoute:
    tools: list[ToolDefinition]
    activated_domains: list[str]
    scored_tools: list[dict[str, Any]]
    deferred_tools: list[dict[str, Any]]


class ToolRouter:
    """Select a compact initial tool set and search the remaining catalog."""

    def __init__(
        self,
        *,
        max_dynamic_tools: int = DEFAULT_MAX_DYNAMIC_TOOLS,
        min_dynamic_score: int = DEFAULT_MIN_DYNAMIC_SCORE,
    ):
        self.max_dynamic_tools = max(0, max_dynamic_tools)
        self.min_dynamic_score = max(1, min_dynamic_score)

    def route(
        self,
        catalog: Iterable[ToolDefinition],
        *,
        query: str,
    ) -> ToolRoute:
        tools = list(catalog)
        always_on = [
            tool
            for tool in tools
            if bool(tool.metadata.get("always_on"))
            or tool.name in CORE_ALWAYS_ON_TOOL_NAMES
        ]
        always_names = {tool.name for tool in always_on}
        activated_domains = self._activated_domains(query)

        scored: list[tuple[int, ToolDefinition, list[str]]] = []
        for tool in tools:
            if tool.name in always_names or not bool(tool.metadata.get("discoverable", True)):
                continue
            score, reasons = self._score(tool, query, activated_domains)
            if score > 0:
                scored.append((score, tool, reasons))

        scored.sort(key=lambda item: (-item[0], item[1].name))
        high_priority = [
            item
            for item in scored
            if self._is_high_priority_match(item[0], item[2])
        ]
        initial_dynamic = high_priority[: self.max_dynamic_tools]
        initial_dynamic_names = {tool.name for _, tool, _ in initial_dynamic}
        deferred = [
            item
            for item in scored
            if item[1].name not in initial_dynamic_names
        ]
        dynamic = [tool for _, tool, _ in initial_dynamic]
        selected_names = always_names | {tool.name for tool in dynamic}
        selected = [tool for tool in tools if tool.name in selected_names]
        return ToolRoute(
            tools=selected,
            activated_domains=activated_domains,
            scored_tools=[
                {"name": tool.name, "score": score, "reasons": reasons}
                for score, tool, reasons in initial_dynamic
            ],
            deferred_tools=[
                {"name": tool.name, "score": score, "reasons": reasons}
                for score, tool, reasons in deferred
            ],
        )

    def search(
        self,
        catalog: Iterable[ToolDefinition],
        *,
        query: str,
        exclude_names: set[str] | None = None,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        excluded = exclude_names or set()
        activated_domains = self._activated_domains(query)
        scored: list[tuple[int, ToolDefinition, list[str]]] = []
        for tool in catalog:
            if tool.name in excluded or tool.name == "tool_search":
                continue
            if not bool(tool.metadata.get("discoverable", True)):
                continue
            score, reasons = self._score(tool, query, activated_domains)
            if score <= 0:
                continue
            scored.append((score, tool, reasons))
        scored.sort(key=lambda item: (-item[0], item[1].name))
        return [
            {
                "name": tool.name,
                "description": tool.description,
                "domains": list(tool.metadata.get("domains") or []),
                "risk_level": str(tool.metadata.get("risk_level") or "low"),
                "access": str(tool.metadata.get("access") or "read"),
                "score": score,
                "match_reasons": reasons,
            }
            for score, tool, reasons in scored[: max(1, min(limit, 10))]
        ]

    def _score(
        self,
        tool: ToolDefinition,
        query: str,
        activated_domains: list[str],
    ) -> tuple[int, list[str]]:
        normalized_query = self._normalize(query)
        query_terms = self._terms(normalized_query)
        name = self._normalize(tool.name.replace("_", " "))
        description = self._normalize(tool.description)
        tags = [self._normalize(value) for value in tool.metadata.get("tags") or []]
        domains = [
            self._normalize(value)
            for value in (
                list(tool.metadata.get("domains") or [])
                + self._inferred_domains(tool.name)
            )
        ]
        keywords = [
            self._normalize(value)
            for value in tool.metadata.get("routing_keywords") or []
        ]

        score = 0
        reasons: list[str] = []
        compact_name = name.replace(" ", "")
        compact_query = normalized_query.replace(" ", "")
        if compact_name and compact_name in compact_query:
            score += 120
            reasons.append("name")

        domain_hits = sorted(set(domains) & set(activated_domains))
        domain_mismatch = bool(activated_domains and domains and not domain_hits)
        if domain_hits:
            score += 36 * len(domain_hits)
            reasons.extend(f"domain:{domain}" for domain in domain_hits)

        for keyword in keywords:
            if keyword and keyword in normalized_query:
                score += 28
                reasons.append(f"keyword:{keyword}")

        for term in query_terms:
            if len(term) < 2:
                continue
            if term in name:
                score += 18
            if term in tags:
                score += 14
            if term in domains:
                score += 14
            if term in description and not domain_mismatch:
                score += 4

        if not domains and not keywords:
            score += 1
            reasons.append("legacy_unclassified")
        if not normalized_query and tool.metadata.get("always_on"):
            score += 1
        return score, list(dict.fromkeys(reasons))

    def _is_high_priority_match(self, score: int, reasons: list[str]) -> bool:
        return (
            score >= self.min_dynamic_score
            or "name" in reasons
            or any(reason.startswith("keyword:") for reason in reasons)
        )

    def _activated_domains(self, query: str) -> list[str]:
        normalized = self._normalize(query)
        activated = []
        for domain, triggers in _DOMAIN_TRIGGERS.items():
            if any(self._normalize(trigger) in normalized for trigger in triggers):
                activated.append(domain)
        return activated

    @staticmethod
    def _inferred_domains(tool_name: str) -> list[str]:
        normalized = str(tool_name or "").casefold()
        inferred = []
        for domain in ("drive", "todo", "pulse", "image"):
            if domain in normalized:
                inferred.append(domain)
        if "weight" in normalized or "calorie" in normalized:
            inferred.append("weight_loss")
        return inferred

    @staticmethod
    def _normalize(value: Any) -> str:
        return " ".join(str(value or "").casefold().split())

    @staticmethod
    def _terms(value: str) -> list[str]:
        terms = re.findall(r"[a-z0-9_]+|[\u3400-\u9fff]{2,}", value)
        expanded: list[str] = []
        for term in terms:
            expanded.append(term)
            if any("\u3400" <= char <= "\u9fff" for char in term) and len(term) > 4:
                expanded.extend(term[index:index + 2] for index in range(len(term) - 1))
        return list(dict.fromkeys(expanded))
