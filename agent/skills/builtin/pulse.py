from __future__ import annotations

import os
import re
from typing import Any, Callable
from urllib.parse import quote

import httpx

from agent.config import runtime_config
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


PULSE_TOOL_NAMES = {
    "get_pulse",
    "refresh_pulse",
    "list_pulse_topics",
    "optimize_pulse_topics",
    "upsert_pulse_topic",
    "delete_pulse_topic",
}
_DEFAULT_GATEWAY_BASE_URL = "http://localhost:8080"


class PulseGatewayError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class PulseGatewayClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 300.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = _normalize_gateway_base_url(base_url or _pulse_gateway_base_url())
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_runtime_config(cls) -> "PulseGatewayClient":
        return cls()

    def _endpoint(self, path: str) -> str:
        api_base = self.base_url if self.base_url.endswith("/api") else f"{self.base_url}/api"
        return f"{api_base}{path}"

    async def _request(
        self,
        method: str,
        path: str,
        *,
        user_id: str,
        params: dict[str, Any] | None = None,
        json_body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        normalized_user = _normalize_user_id(user_id)
        headers = {"X-User-ID": normalized_user}
        if json_body is not None:
            json_body = {"user_id": normalized_user, **json_body}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.request(
                method,
                self._endpoint(path),
                headers=headers,
                params=params,
                json=json_body,
            )
        if response.status_code >= 400:
            raise PulseGatewayError(_extract_error_message(response), status_code=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise PulseGatewayError("pulse gateway returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise PulseGatewayError("pulse gateway returned an unexpected payload")
        return payload

    async def get(self, user_id: str, *, date: str = "") -> dict[str, Any]:
        return await self._request(
            "GET",
            "/pulse",
            user_id=user_id,
            params={"date": date} if date else None,
        )

    async def refresh(
        self,
        user_id: str,
        *,
        date: str = "",
        wait: bool = True,
    ) -> dict[str, Any]:
        body: dict[str, Any] = {"wait": wait}
        if date:
            body["date"] = date
        return await self._request(
            "POST",
            "/pulse/refresh",
            user_id=user_id,
            json_body=body,
        )

    async def list_topics(self, user_id: str) -> list[dict[str, Any]]:
        payload = await self._request("GET", "/pulse/topics", user_id=user_id)
        return _dict_list(payload.get("topics"))

    async def topic_optimization_context(
        self,
        user_id: str,
        *,
        lookback_days: int = 30,
    ) -> dict[str, Any]:
        return await self._request(
            "GET",
            "/pulse/topic-optimization",
            user_id=user_id,
            params={"lookback_days": lookback_days},
        )

    async def create_topic(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            "/pulse/topics",
            user_id=user_id,
            json_body=body,
        )
        topic = payload.get("topic")
        if not isinstance(topic, dict):
            raise PulseGatewayError("created pulse topic was not returned")
        return topic

    async def update_topic(
        self,
        user_id: str,
        topic_id: str,
        body: dict[str, Any],
    ) -> dict[str, Any]:
        payload = await self._request(
            "PUT",
            f"/pulse/topics/{quote(topic_id, safe='')}",
            user_id=user_id,
            json_body=body,
        )
        topic = payload.get("topic")
        if not isinstance(topic, dict):
            raise PulseGatewayError("updated pulse topic was not returned")
        return topic

    async def delete_topic(self, user_id: str, topic_id: str) -> dict[str, Any]:
        return await self._request(
            "DELETE",
            f"/pulse/topics/{quote(topic_id, safe='')}",
            user_id=user_id,
        )


class _PulseTool(Skill):
    auto_discover = False

    def __init__(self, client_factory: Callable[[], PulseGatewayClient] | None = None):
        self._client_factory = client_factory or PulseGatewayClient.from_runtime_config

    def _client(self) -> PulseGatewayClient:
        return self._client_factory()

    def _user_id(self, kwargs: dict[str, Any]) -> str:
        return _normalize_user_id(kwargs.get("_user_id"))


class PulseGetSkill(_PulseTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="get_pulse",
            description=(
                "读取当前用户某一天的 Pulse 推荐。用户问“今天有什么值得关注、最近该看什么、"
                "我的 Pulse 有什么”等个性化资讯问题时优先使用。若当天尚未生成，接口会启动后台生成。"
            ),
            parameters=[
                SkillParameter(
                    name="date",
                    type="string",
                    description="日期 YYYY-MM-DD；留空表示今天。",
                    required=False,
                ),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="返回推荐条数，默认 8，最多 24。",
                    required=False,
                    default=8,
                ),
            ],
            tags=["pulse", "recommendation", "read"],
            source="builtin",
            domains=["pulse"],
            routing_keywords=["今天有什么值得关注", "今日推荐", "我的 pulse"],
            allowed_agents=["super_chat"],
            parallel_safe=True,
            idempotent=True,
            risk_level="low",
            access="read",
            max_calls_per_run=6,
            timeout_seconds=30,
        )

    async def execute(self, **kwargs) -> SkillResult:
        try:
            limit = _coerce_int(kwargs.get("limit"), default=8, minimum=1, maximum=24)
            payload = await self._client().get(
                self._user_id(kwargs),
                date=str(kwargs.get("date") or "").strip(),
            )
            data = _pulse_summary(payload, limit=limit)
            return SkillResult(
                success=True,
                data=data,
                display_text=_format_pulse(data),
            )
        except (PulseGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class PulseRefreshSkill(_PulseTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="refresh_pulse",
            description=(
                "强制重新生成当前用户某一天的 Pulse。仅在用户明确要求刷新、更新或重新生成 Pulse 时使用；"
                "普通“今天有什么值得关注”先调用 get_pulse。默认等待生成完成并返回新推荐。"
            ),
            parameters=[
                SkillParameter(
                    name="date",
                    type="string",
                    description="日期 YYYY-MM-DD；留空表示今天。",
                    required=False,
                ),
                SkillParameter(
                    name="wait",
                    type="boolean",
                    description="是否等待生成完成，默认 true；false 时只启动后台刷新。",
                    required=False,
                    default=True,
                ),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="返回推荐条数，默认 8，最多 24。",
                    required=False,
                    default=8,
                ),
            ],
            tags=["pulse", "recommendation", "refresh"],
            source="builtin",
            domains=["pulse"],
            routing_keywords=["刷新 pulse", "重新生成推荐", "更新 pulse"],
            allowed_agents=["super_chat"],
            risk_level="medium",
            access="external",
            default_policy="auto",
            max_calls_per_run=2,
            timeout_seconds=360,
        )

    async def execute(self, **kwargs) -> SkillResult:
        try:
            wait = _coerce_bool(kwargs.get("wait"), default=True)
            limit = _coerce_int(kwargs.get("limit"), default=8, minimum=1, maximum=24)
            payload = await self._client().refresh(
                self._user_id(kwargs),
                date=str(kwargs.get("date") or "").strip(),
                wait=wait,
            )
            data = _pulse_summary(payload, limit=limit)
            data["waited"] = wait
            return SkillResult(
                success=True,
                data=data,
                display_text=_format_pulse(data, refreshed=True),
            )
        except (PulseGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class PulseListTopicsSkill(_PulseTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="list_pulse_topics",
            description=(
                "列出当前用户实际存在的 Pulse Topic 和关键词。"
                "更新 Topic 但用户没有提供 topic_id 时，先调用本工具查找。"
            ),
            parameters=[],
            tags=["pulse", "topic", "read"],
            source="builtin",
            domains=["pulse"],
            routing_keywords=["关注主题", "订阅方向", "pulse topics"],
            allowed_agents=["super_chat"],
            parallel_safe=True,
            idempotent=True,
            risk_level="low",
            access="read",
            max_calls_per_run=8,
        )

    async def execute(self, **kwargs) -> SkillResult:
        try:
            topics = await self._client().list_topics(self._user_id(kwargs))
            normalized = [_topic_summary(topic) for topic in topics]
            return SkillResult(
                success=True,
                data={"topics": normalized, "total": len(normalized)},
                display_text=_format_topics(normalized),
            )
        except (PulseGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class PulseOptimizeTopicsSkill(_PulseTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="optimize_pulse_topics",
            description=(
                "读取当前用户的 Pulse Topic 优化证据。current_topics 是当前实际存在的订阅；"
                "candidate_interest_signals、近期对话与历史信息簇仅是分析证据，绝不是现有 Topic。"
                "用户要求优化信息簇、整理订阅或改善 Pulse 召回时调用。工具只提供分析上下文，"
                "不会修改 Topic；Super Chat 必须先总结保留、合并、改名、删除和关键词方案并请用户确认。"
            ),
            parameters=[
                SkillParameter(
                    name="lookback_days",
                    type="integer",
                    description="历史分析天数，默认 30；范围 7-90。",
                    required=False,
                    default=30,
                    minimum=7,
                    maximum=90,
                ),
            ],
            tags=["pulse", "topic", "optimization", "read"],
            source="builtin",
            domains=["pulse"],
            routing_keywords=[
                "优化信息簇",
                "优化订阅",
                "整理 pulse topic",
                "改善 pulse 关键词",
            ],
            allowed_agents=["super_chat"],
            parallel_safe=True,
            idempotent=True,
            risk_level="low",
            access="read",
            max_calls_per_run=3,
            timeout_seconds=30,
        )

    async def execute(self, **kwargs) -> SkillResult:
        try:
            lookback_days = _coerce_int(
                kwargs.get("lookback_days"),
                default=30,
                minimum=7,
                maximum=90,
            )
            payload = await self._client().topic_optimization_context(
                self._user_id(kwargs),
                lookback_days=lookback_days,
            )
            current_topics = payload.pop("topics", payload.get("current_topics", []))
            candidate_signals = payload.pop(
                "memory_signals",
                payload.get("candidate_interest_signals", []),
            )
            payload["current_topics"] = _dict_list(current_topics)
            payload["candidate_interest_signals"] = _dict_list(candidate_signals)
            payload["topic_semantics"] = {
                "existing_topics_source": "current_topics_only",
                "candidate_interest_signals_are_existing_topics": False,
                "historical_clusters_are_existing_topics": False,
                "lifecycle": "A Topic either exists or is deleted; there is no disabled state.",
            }
            return SkillResult(
                success=True,
                data=payload,
                display_text=_format_topic_optimization_context(payload),
            )
        except (PulseGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class PulseUpsertTopicSkill(_PulseTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="upsert_pulse_topic",
            description=(
                "新增或更新当前用户的 Pulse Topic。没有 topic_id 时按名称新增或覆盖同名 Topic；"
                "提供 topic_id 时更新指定 Topic。适合订阅关注方向、修改名称或关键词。"
                "批量优化前应先调用 optimize_pulse_topics，并先向用户展示方案；只有用户当前消息明确确认后才能执行。"
            ),
            parameters=[
                SkillParameter(
                    name="topic_id",
                    type="string",
                    description=(
                        "可选 Topic ID；更新指定 Topic 时提供，必须使用 list_pulse_topics 返回的完整 ID。"
                        "若上下文中只有至少 8 位的唯一 ID 前缀，系统会在授权前解析为完整 ID。"
                    ),
                    required=False,
                ),
                SkillParameter(
                    name="name",
                    type="string",
                    description="Topic 名称；新增时必填，更新时可省略。",
                    required=False,
                ),
                SkillParameter(
                    name="keywords",
                    type="string",
                    description="关键词，使用逗号分隔；新增时可省略并由系统扩展。",
                    required=False,
                ),
            ],
            tags=["pulse", "topic", "write"],
            source="builtin",
            domains=["pulse"],
            routing_keywords=["订阅主题", "修改关注方向", "更新 topic"],
            allowed_agents=["super_chat"],
            risk_level="medium",
            access="write",
            default_policy="confirm",
            max_calls_per_run=12,
            confirmation_keywords=[
                "订阅主题",
                "新增 topic",
                "修改 topic",
                "优化订阅",
                "应用优化方案",
                "应用这个方案",
                "按这个方案",
                "确认修改订阅",
            ],
        )

    async def prepare_arguments(self, **kwargs) -> dict[str, Any]:
        prepared = dict(kwargs)
        topic_id = str(prepared.get("topic_id") or "").strip()
        if not topic_id:
            return prepared
        match = _resolve_topic(
            await self._client().list_topics(self._user_id(prepared)),
            topic_id=topic_id,
        )
        prepared["topic_id"] = str(match.get("id") or "").strip()
        if not str(prepared.get("name") or "").strip():
            topic_name = str(match.get("name") or "").strip()
            if topic_name:
                prepared["name"] = topic_name
        return prepared

    async def execute(self, **kwargs) -> SkillResult:
        topic_id = str(kwargs.get("topic_id") or "").strip()
        name = str(kwargs.get("name") or "").strip()
        if not topic_id and not name:
            return SkillResult(success=False, error="name is required when topic_id is not provided")

        body: dict[str, Any] = {}
        if name:
            body["name"] = name
        if "keywords" in kwargs and kwargs.get("keywords") is not None:
            body["keywords"] = _coerce_keywords(kwargs.get("keywords"))
        if topic_id and not body:
            return SkillResult(success=False, error="at least one topic field is required")

        try:
            client = self._client()
            user_id = self._user_id(kwargs)
            if topic_id:
                topic = await client.update_topic(user_id, topic_id, body)
                action = "Updated"
            else:
                topic = await client.create_topic(user_id, body)
                action = "Upserted"
            normalized = _topic_summary(topic)
            return SkillResult(
                success=True,
                data={"topic": normalized},
                display_text=f"{action} Pulse topic: {_format_topic_line(normalized)}",
            )
        except (PulseGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class PulseDeleteTopicSkill(_PulseTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="delete_pulse_topic",
            description=(
                "永久删除当前用户的一个 Pulse Topic。Topic 只有存在或删除两种状态，不支持停用。"
                "仅在用户当前消息明确要求删除，或明确确认包含删除动作的优化方案后使用。"
                "可以按 list_pulse_topics 返回的名称或内部 topic_id 精确定位。"
            ),
            parameters=[
                SkillParameter(
                    name="name",
                    type="string",
                    description="要删除的 Topic 名称；面向用户优先使用名称。",
                    required=False,
                ),
                SkillParameter(
                    name="topic_id",
                    type="string",
                    description=(
                        "可选内部 Topic ID。可以使用至少 8 位的唯一前缀；"
                        "系统会在授权前解析为完整 ID，且不会向用户展示。"
                    ),
                    required=False,
                ),
            ],
            tags=["pulse", "topic", "delete"],
            source="builtin",
            domains=["pulse"],
            routing_keywords=["删除 topic", "删掉订阅", "移除关注主题"],
            allowed_agents=["super_chat"],
            risk_level="high",
            access="destructive",
            default_policy="confirm",
            max_calls_per_run=12,
            confirmation_keywords=[
                "删除 topic",
                "删掉 topic",
                "移除 topic",
                "删除订阅",
                "删掉订阅",
                "delete topic",
                "remove topic",
                "应用优化方案",
                "按这个方案",
            ],
        )

    async def prepare_arguments(self, **kwargs) -> dict[str, Any]:
        prepared = dict(kwargs)
        topic_id = str(prepared.get("topic_id") or "").strip()
        name = str(prepared.get("name") or "").strip()
        if not topic_id and not name:
            raise ValueError("name or topic_id is required")
        match = _resolve_topic(
            await self._client().list_topics(self._user_id(prepared)),
            topic_id=topic_id,
            name=name,
        )
        prepared["topic_id"] = str(match.get("id") or "").strip()
        prepared["name"] = str(match.get("name") or "").strip()
        return prepared

    async def execute(self, **kwargs) -> SkillResult:
        topic_id = str(kwargs.get("topic_id") or "").strip()
        name = str(kwargs.get("name") or "").strip()
        if not topic_id:
            return SkillResult(success=False, error="topic_id is required after topic resolution")
        try:
            await self._client().delete_topic(self._user_id(kwargs), topic_id)
            deleted = {"id": topic_id, "name": name}
            return SkillResult(
                success=True,
                data={"deleted": deleted},
                display_text=f"Deleted Pulse topic permanently: {name or 'Topic'}",
            )
        except (PulseGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


def _pulse_gateway_base_url() -> str:
    return (
        runtime_config.get("tool.pulse.gateway_base_url")
        or runtime_config.get("tool.gateway_base_url")
        or os.environ.get("AGENT_ASSISTANT_GATEWAY_URL")
        or os.environ.get("GATEWAY_BASE_URL")
        or _DEFAULT_GATEWAY_BASE_URL
    )


def _normalize_gateway_base_url(value: str) -> str:
    value = str(value or "").strip() or _DEFAULT_GATEWAY_BASE_URL
    return value.rstrip("/")


def _normalize_user_id(value: Any) -> str:
    user_id = str(value or "0").strip()
    return user_id or "0"


def _extract_error_message(response: httpx.Response) -> str:
    try:
        payload = response.json()
        if isinstance(payload, dict):
            return str(payload.get("error") or payload.get("detail") or response.text or response.reason_phrase)
    except ValueError:
        pass
    return response.text or response.reason_phrase or f"pulse gateway status {response.status_code}"


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _coerce_bool(value: Any, *, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    normalized = str(value).strip().lower()
    if normalized in {"1", "true", "yes", "on"}:
        return True
    if normalized in {"0", "false", "no", "off"}:
        return False
    return default


def _coerce_keywords(value: Any) -> list[str]:
    if isinstance(value, list):
        candidates = [str(item).strip() for item in value]
    else:
        candidates = [
            item.strip()
            for item in re.split(r"[,，;；\n]+", str(value or ""))
        ]
    keywords: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in keywords:
            keywords.append(candidate[:60])
    return keywords[:20]


def _resolve_topic(
    topics: list[dict[str, Any]],
    *,
    topic_id: str = "",
    name: str = "",
) -> dict[str, Any]:
    normalized_id = str(topic_id or "").strip().lower()
    normalized_name = str(name or "").strip().casefold()
    if normalized_id:
        exact_matches = [
            topic
            for topic in topics
            if str(topic.get("id") or "").strip().lower() == normalized_id
        ]
        if exact_matches:
            match = exact_matches[0]
        else:
            if len(normalized_id) < 8:
                raise ValueError("topic_id prefix must contain at least 8 characters")
            prefix_matches = [
                topic
                for topic in topics
                if str(topic.get("id") or "").strip().lower().startswith(normalized_id)
            ]
            if not prefix_matches:
                raise ValueError("topic not found")
            if len(prefix_matches) > 1:
                raise ValueError("topic_id prefix is ambiguous")
            match = prefix_matches[0]
    else:
        name_matches = [
            topic
            for topic in topics
            if str(topic.get("name") or "").strip().casefold() == normalized_name
        ]
        if not name_matches:
            raise ValueError("topic not found")
        if len(name_matches) > 1:
            raise ValueError("topic name is ambiguous")
        match = name_matches[0]

    if not str(match.get("id") or "").strip():
        raise ValueError("matched topic has no ID")
    return match


def _topic_summary(topic: dict[str, Any]) -> dict[str, Any]:
    return {
        "id": str(topic.get("id") or ""),
        "name": str(topic.get("name") or ""),
        "keywords": [
            str(keyword)
            for keyword in (topic.get("keywords") if isinstance(topic.get("keywords"), list) else [])
        ],
        "created_at": str(topic.get("created_at") or ""),
        "updated_at": str(topic.get("updated_at") or ""),
    }


def _pulse_summary(payload: dict[str, Any], *, limit: int) -> dict[str, Any]:
    items = _dict_list(payload.get("items"))
    visible_items = items[:limit]
    return {
        "date": str(payload.get("date") or ""),
        "generated_at": str(payload.get("generated_at") or ""),
        "refreshing": bool(payload.get("refreshing")),
        "candidate_count": int(payload.get("candidate_count") or 0),
        "recommended_count": int(payload.get("recommended_count") or len(items)),
        "filtered_count": int(payload.get("filtered_count") or 0),
        "topics": [_topic_summary(topic) for topic in _dict_list(payload.get("topics"))],
        "suggested_topics": [
            {
                "name": str(topic.get("name") or ""),
                "keywords": topic.get("keywords") if isinstance(topic.get("keywords"), list) else [],
                "reason": str(topic.get("reason") or ""),
                "heat_score": int(topic.get("heat_score") or 0),
            }
            for topic in _dict_list(payload.get("suggested_topics"))[:8]
        ],
        "modules": [
            {
                "key": str(module.get("key") or ""),
                "title": str(module.get("title") or ""),
                "summary": str(module.get("summary") or ""),
                "item_count": len(_dict_list(module.get("items"))),
            }
            for module in _dict_list(payload.get("modules"))
        ],
        "items": [_pulse_item_summary(item) for item in visible_items],
        "total": len(items),
        "truncated": len(items) > len(visible_items),
    }


def _pulse_item_summary(item: dict[str, Any]) -> dict[str, Any]:
    detail = item.get("detail") if isinstance(item.get("detail"), dict) else {}
    sources = _dict_list(detail.get("news_sources"))
    return {
        "id": str(item.get("id") or ""),
        "date": str(item.get("date") or ""),
        "topic_id": str(item.get("topic_id") or ""),
        "topic_name": str(item.get("topic_name") or ""),
        "source": str(item.get("source") or ""),
        "category": str(item.get("category") or ""),
        "title": str(item.get("title") or ""),
        "summary": str(item.get("summary") or ""),
        "heat_score": int(item.get("heat_score") or 0),
        "recommendation_reason": str(detail.get("recommendation_reason") or ""),
        "quick_context": str(detail.get("quick_context") or ""),
        "key_points": _string_list(detail.get("key_points"), limit=8),
        "suggested_questions": _string_list(detail.get("suggested_questions"), limit=5),
        "news_sources": [
            {
                "title": str(source.get("title") or ""),
                "url": str(source.get("url") or ""),
                "source": str(source.get("source") or ""),
                "published_at": str(source.get("published_at") or ""),
            }
            for source in sources[:5]
        ],
        "explore_prompt": str(item.get("explore_prompt") or ""),
    }


def _format_pulse(data: dict[str, Any], *, refreshed: bool = False) -> str:
    date = str(data.get("date") or "today")
    items = data.get("items") if isinstance(data.get("items"), list) else []
    if not items:
        if data.get("refreshing"):
            return f"Pulse for {date} is being generated."
        return f"No Pulse recommendations are available for {date}."
    prefix = "Refreshed Pulse" if refreshed and not data.get("refreshing") else "Pulse"
    lines = [f"{prefix} for {date} ({len(items)}/{data.get('total', len(items))}):"]
    for index, item in enumerate(items, start=1):
        if not isinstance(item, dict):
            continue
        heat = int(item.get("heat_score") or 0)
        summary = str(item.get("summary") or "").strip()
        lines.append(f"{index}. [{heat}] {item.get('title')}" + (f" — {summary}" if summary else ""))
        sources = item.get("news_sources") if isinstance(item.get("news_sources"), list) else []
        if sources and isinstance(sources[0], dict) and sources[0].get("url"):
            lines.append(f"   Source: {sources[0].get('url')}")
    if data.get("refreshing"):
        lines.append("A background refresh is still running.")
    if data.get("truncated"):
        lines.append("Results truncated.")
    return "\n".join(lines)


def _string_list(value: Any, *, limit: int) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value[:limit] if str(item).strip()]


def _format_topic_line(topic: dict[str, Any]) -> str:
    keywords = ", ".join(topic.get("keywords") or [])
    suffix = f" · {keywords}" if keywords else ""
    return f"{topic.get('name')}{suffix}"


def _format_topics(topics: list[dict[str, Any]]) -> str:
    if not topics:
        return "No Pulse topics configured."
    lines = [f"Pulse topics ({len(topics)}):"]
    for index, topic in enumerate(topics, start=1):
        lines.append(f"{index}. {_format_topic_line(topic)}")
    return "\n".join(lines)


def _format_topic_optimization_context(payload: dict[str, Any]) -> str:
    topics = _dict_list(payload.get("current_topics"))
    history = payload.get("history") if isinstance(payload.get("history"), dict) else {}
    summary = history.get("summary") if isinstance(history.get("summary"), dict) else {}
    overlaps = _dict_list(history.get("overlap_candidates"))
    runs = _dict_list(history.get("retrieval_runs"))
    return (
        "Pulse topic optimization context loaded: "
        f"{len(topics)} topics, "
        f"{int(summary.get('sampled_cluster_count') or 0)} historical clusters, "
        f"{len(overlaps)} overlap candidates, "
        f"{len(runs)} retrieval runs. "
        "Only current_topics are existing subscriptions; candidate interest signals and historical "
        "clusters are evidence, not Topics. Use the evidence to propose a plan, and do not modify "
        "or delete topics until the user explicitly confirms it."
    )
