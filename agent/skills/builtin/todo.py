from __future__ import annotations

import os
from typing import Any, Callable
from urllib.parse import quote

import httpx

from agent.config import runtime_config
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


TODO_TOOL_NAMES = {"create_todo", "get_todo", "list_todos", "update_todo", "delete_todo"}
_DEFAULT_GATEWAY_BASE_URL = "http://localhost:8080"


class TodoGatewayError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class TodoGatewayClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = _normalize_gateway_base_url(base_url or _todo_gateway_base_url())
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_runtime_config(cls) -> "TodoGatewayClient":
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
            raise TodoGatewayError(_extract_error_message(response), status_code=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise TodoGatewayError("todo gateway returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise TodoGatewayError("todo gateway returned an unexpected payload")
        return payload

    async def create(self, user_id: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = await self._request("POST", "/todos", user_id=user_id, json_body=body)
        todo = payload.get("todo")
        if not isinstance(todo, dict):
            raise TodoGatewayError("created todo was not returned")
        return todo

    async def list(
        self,
        user_id: str,
        *,
        scope: str,
        date: str = "",
        start: str = "",
        end: str = "",
        include_completed: bool = False,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {
            "scope": scope,
            "include_completed": "true" if include_completed else "false",
        }
        if date:
            params["date"] = date
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return await self._request("GET", "/todos", user_id=user_id, params=params)

    async def get(self, user_id: str, todo_id: str) -> dict[str, Any]:
        payload = await self._request(
            "GET",
            f"/todos/{quote(todo_id, safe='')}",
            user_id=user_id,
        )
        todo = payload.get("todo")
        if not isinstance(todo, dict):
            raise TodoGatewayError("todo was not returned")
        return todo

    async def update(self, user_id: str, todo_id: str, body: dict[str, Any]) -> dict[str, Any]:
        payload = await self._request(
            "PUT",
            f"/todos/{quote(todo_id, safe='')}",
            user_id=user_id,
            json_body=body,
        )
        todo = payload.get("todo")
        if not isinstance(todo, dict):
            raise TodoGatewayError("updated todo was not returned")
        return todo

    async def delete(self, user_id: str, todo_id: str) -> None:
        await self._request(
            "DELETE",
            f"/todos/{quote(todo_id, safe='')}",
            user_id=user_id,
        )


class _TodoTool(Skill):
    auto_discover = False

    def __init__(self, client_factory: Callable[[], TodoGatewayClient] | None = None):
        self._client_factory = client_factory or TodoGatewayClient.from_runtime_config

    def _client(self) -> TodoGatewayClient:
        return self._client_factory()

    def _user_id(self, kwargs: dict[str, Any]) -> str:
        user_id = _normalize_user_id(kwargs.get("_user_id"))
        if not user_id:
            raise ValueError("user context is required")
        return user_id


class TodoCreateSkill(_TodoTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="create_todo",
            description=(
                "为当前用户创建待办事项。用户说“记一下/提醒我/加入待办/安排/明天做”等明确记录任务时使用；"
                "相对日期要先根据系统时间上下文换成 YYYY-MM-DD。"
            ),
            parameters=[
                SkillParameter(name="title", type="string", description="待办标题，简短明确。", required=True),
                SkillParameter(name="notes", type="string", description="可选备注、上下文或执行细节。", required=False),
                SkillParameter(
                    name="start_date",
                    type="string",
                    description="生命周期开始日期，格式 YYYY-MM-DD；无开始日期可省略。",
                    required=False,
                ),
                SkillParameter(
                    name="due_date",
                    type="string",
                    description="截止/结束日期，格式 YYYY-MM-DD；今天/明天等要换成绝对日期；暂不排期可省略。",
                    required=False,
                ),
                SkillParameter(name="due_time", type="string", description="可选时间，格式 HH:MM。", required=False),
                SkillParameter(
                    name="repeat_rule",
                    type="string",
                    description="重复规则：once、daily 或 workdays。默认 once。",
                    required=False,
                    default="once",
                ),
                SkillParameter(
                    name="priority",
                    type="string",
                    description="优先级：low、normal 或 high。默认 normal。",
                    required=False,
                    default="normal",
                ),
                SkillParameter(name="tags", type="string", description="可选标签，逗号分隔。", required=False),
                SkillParameter(
                    name="timezone",
                    type="string",
                    description="时区，默认 Asia/Shanghai。",
                    required=False,
                    default="Asia/Shanghai",
                ),
            ],
            tags=["todo", "task", "write"],
            source="builtin",
            risk_level="medium",
            access="write",
            max_calls_per_run=8,
            sensitive_arguments=["notes"],
        )

    async def execute(self, **kwargs) -> SkillResult:
        title = str(kwargs.get("title") or "").strip()
        if not title:
            return SkillResult(success=False, error="title is required")
        try:
            user_id = self._user_id(kwargs)
            body = {
                "title": title,
                "notes": str(kwargs.get("notes") or "").strip(),
                "start_date": str(kwargs.get("start_date") or "").strip(),
                "due_date": str(kwargs.get("due_date") or kwargs.get("end_date") or "").strip(),
                "due_time": str(kwargs.get("due_time") or "").strip(),
                "repeat_rule": _normalize_repeat_rule(kwargs.get("repeat_rule")),
                "priority": _normalize_priority(kwargs.get("priority")),
                "tags": _coerce_tags(kwargs.get("tags")),
                "timezone": str(kwargs.get("timezone") or "Asia/Shanghai").strip() or "Asia/Shanghai",
                "source": "manual",
            }
            conversation_id = str(kwargs.get("_conversation_id") or "").strip()
            run_id = str(kwargs.get("_run_id") or "").strip()
            if conversation_id:
                body["origin_conversation_id"] = conversation_id
            if run_id:
                body["origin_run_id"] = run_id
            todo = await self._client().create(user_id, body)
            return SkillResult(
                success=True,
                data={"todo": _todo_summary(todo)},
                display_text=f"Created todo: {_format_todo_line(todo)}",
            )
        except (TodoGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class TodoGetSkill(_TodoTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="get_todo",
            description="按 todo_id 读取当前用户的一条待办详情。适合 list_todos 已给出候选 ID 后进一步查看。",
            parameters=[
                SkillParameter(name="todo_id", type="string", description="待办 ID。", required=True),
            ],
            tags=["todo", "task", "read"],
            source="builtin",
            max_calls_per_run=12,
        )

    async def execute(self, **kwargs) -> SkillResult:
        todo_id = str(kwargs.get("todo_id") or kwargs.get("id") or "").strip()
        if not todo_id:
            return SkillResult(success=False, error="todo_id is required")
        try:
            todo = await self._client().get(self._user_id(kwargs), todo_id)
            return SkillResult(
                success=True,
                data={"todo": _todo_summary(todo)},
                display_text=_format_todo_line(todo),
            )
        except (TodoGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class TodoListSkill(_TodoTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="list_todos",
            description=(
                "查询当前用户待办。用户问今天有什么、待排期有哪些、某月计划、或更新待办但没给 todo_id 时，"
                "先用这个工具查出候选 ID。"
            ),
            parameters=[
                SkillParameter(
                    name="scope",
                    type="string",
                    description="范围：today、overdue、inbox、month、upcoming、done。默认 today。",
                    required=False,
                    default="today",
                ),
                SkillParameter(name="date", type="string", description="参考日期 YYYY-MM-DD，默认今天。", required=False),
                SkillParameter(
                    name="start_date",
                    type="string",
                    description="month 范围开始日期 YYYY-MM-DD；查询月视图时建议提供。",
                    required=False,
                ),
                SkillParameter(
                    name="end_date",
                    type="string",
                    description="month 范围结束日期 YYYY-MM-DD；查询月视图时建议提供。",
                    required=False,
                ),
                SkillParameter(
                    name="include_completed",
                    type="boolean",
                    description="是否包含已完成待办，默认 false。",
                    required=False,
                    default=False,
                ),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="返回条数上限，默认 20，最多 100。",
                    required=False,
                    default=20,
                ),
            ],
            tags=["todo", "task", "read"],
            source="builtin",
            max_calls_per_run=12,
        )

    async def execute(self, **kwargs) -> SkillResult:
        try:
            user_id = self._user_id(kwargs)
            scope = _normalize_scope(kwargs.get("scope"))
            limit = _coerce_int(kwargs.get("limit"), default=20, minimum=1, maximum=100)
            payload = await self._client().list(
                user_id,
                scope=scope,
                date=str(kwargs.get("date") or "").strip(),
                start=str(kwargs.get("start_date") or kwargs.get("start") or "").strip(),
                end=str(kwargs.get("end_date") or kwargs.get("end") or "").strip(),
                include_completed=_coerce_bool(kwargs.get("include_completed")),
            )
            items = _dict_list(payload.get("items"))
            visible_items = items[:limit]
            data = {
                "scope": str(payload.get("scope") or scope),
                "date": str(payload.get("date") or ""),
                "start": str(payload.get("start") or ""),
                "end": str(payload.get("end") or ""),
                "counts": payload.get("counts") if isinstance(payload.get("counts"), dict) else {},
                "items": [_todo_summary(item) for item in visible_items],
                "total": len(items),
                "truncated": len(items) > len(visible_items),
            }
            return SkillResult(
                success=True,
                data=data,
                display_text=_format_todo_listing(data),
            )
        except (TodoGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class TodoUpdateSkill(_TodoTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="update_todo",
            description=(
                "更新当前用户已有待办，可修改标题、日期、备注、优先级，或把待办标为完成/未完成。"
                "如果用户没有提供 todo_id，应先调用 list_todos 找到候选项。"
            ),
            parameters=[
                SkillParameter(name="todo_id", type="string", description="待办 ID，通常来自 list_todos。", required=True),
                SkillParameter(name="title", type="string", description="新标题；不修改则省略。", required=False),
                SkillParameter(name="notes", type="string", description="新备注；不修改则省略。", required=False),
                SkillParameter(name="start_date", type="string", description="新开始日期 YYYY-MM-DD；清空可传空字符串。", required=False),
                SkillParameter(name="due_date", type="string", description="新结束/截止日期 YYYY-MM-DD；清空可传空字符串。", required=False),
                SkillParameter(name="due_time", type="string", description="新时间 HH:MM；清空可传空字符串。", required=False),
                SkillParameter(name="repeat_rule", type="string", description="once、daily 或 workdays。", required=False),
                SkillParameter(name="priority", type="string", description="low、normal 或 high。", required=False),
                SkillParameter(name="status", type="string", description="open 或 done。完成待办传 done，取消完成传 open。", required=False),
            ],
            tags=["todo", "task", "write"],
            source="builtin",
            risk_level="medium",
            access="write",
            max_calls_per_run=8,
            sensitive_arguments=["notes"],
        )

    async def execute(self, **kwargs) -> SkillResult:
        todo_id = str(kwargs.get("todo_id") or kwargs.get("id") or "").strip()
        if not todo_id:
            return SkillResult(success=False, error="todo_id is required")
        try:
            user_id = self._user_id(kwargs)
            body: dict[str, Any] = {}
            _copy_present_string(kwargs, body, "title")
            _copy_present_string(kwargs, body, "notes")
            _copy_present_string(kwargs, body, "start_date")
            if "due_date" in kwargs:
                body["due_date"] = str(kwargs.get("due_date") or "").strip()
            elif "end_date" in kwargs:
                body["end_date"] = str(kwargs.get("end_date") or "").strip()
            _copy_present_string(kwargs, body, "due_time")
            if "repeat_rule" in kwargs:
                body["repeat_rule"] = _normalize_repeat_rule(kwargs.get("repeat_rule"))
            if "priority" in kwargs:
                body["priority"] = _normalize_priority(kwargs.get("priority"))
            if "status" in kwargs:
                body["status"] = _normalize_status(kwargs.get("status"))
            if not body:
                return SkillResult(success=False, error="at least one field to update is required")
            todo = await self._client().update(user_id, todo_id, body)
            return SkillResult(
                success=True,
                data={"todo": _todo_summary(todo)},
                display_text=f"Updated todo: {_format_todo_line(todo)}",
            )
        except (TodoGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class TodoDeleteSkill(_TodoTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="delete_todo",
            description=(
                "永久删除当前用户的一条待办。仅在用户当前消息明确要求删除待办时使用；"
                "如果没有 todo_id，先调用 list_todos 查找候选项。"
            ),
            parameters=[
                SkillParameter(name="todo_id", type="string", description="要永久删除的待办 ID。", required=True),
            ],
            tags=["todo", "task", "delete"],
            source="builtin",
            risk_level="high",
            access="destructive",
            default_policy="confirm",
            max_calls_per_run=4,
            confirmation_keywords=[
                "删除待办",
                "删掉待办",
                "移除待办",
                "delete todo",
                "remove todo",
            ],
        )

    async def execute(self, **kwargs) -> SkillResult:
        todo_id = str(kwargs.get("todo_id") or kwargs.get("id") or "").strip()
        if not todo_id:
            return SkillResult(success=False, error="todo_id is required")
        try:
            user_id = self._user_id(kwargs)
            todo = await self._client().get(user_id, todo_id)
            await self._client().delete(user_id, todo_id)
            deleted = _todo_summary(todo)
            return SkillResult(
                success=True,
                data={"deleted": deleted},
                display_text=f"Deleted todo permanently: {_format_todo_line(todo)}",
            )
        except (TodoGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


def _todo_gateway_base_url() -> str:
    return (
        runtime_config.get("tool.todo.gateway_base_url")
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
    return response.text or response.reason_phrase or f"todo gateway status {response.status_code}"


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _coerce_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_tags = [str(item).strip() for item in value]
    else:
        raw_tags = [item.strip() for item in str(value or "").split(",")]
    tags: list[str] = []
    for tag in raw_tags:
        if tag and tag not in tags:
            tags.append(tag[:40])
    return tags[:12]


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {"1", "true", "yes", "y", "on"}


def _normalize_scope(value: Any) -> str:
    scope = str(value or "today").strip().lower()
    return scope if scope in {"today", "overdue", "inbox", "month", "upcoming", "done", "completed"} else "today"


def _normalize_repeat_rule(value: Any) -> str:
    rule = str(value or "once").strip().lower()
    if rule in {"daily", "workdays", "once"}:
        return rule
    if rule in {"weekday", "weekdays"}:
        return "workdays"
    return "once"


def _normalize_priority(value: Any) -> str:
    priority = str(value or "normal").strip().lower()
    return priority if priority in {"low", "normal", "high"} else "normal"


def _normalize_status(value: Any) -> str:
    status = str(value or "").strip().lower()
    if status in {"done", "completed", "complete"}:
        return "done"
    if status in {"open", "todo", "pending", "reopen"}:
        return "open"
    return status or "open"


def _copy_present_string(source: dict[str, Any], target: dict[str, Any], key: str) -> None:
    if key in source:
        target[key] = str(source.get(key) or "").strip()


def _todo_summary(todo: dict[str, Any]) -> dict[str, Any]:
    due_date = str(todo.get("due_date") or todo.get("end_date") or "")
    return {
        "id": str(todo.get("id") or ""),
        "title": str(todo.get("title") or ""),
        "notes": str(todo.get("notes") or ""),
        "status": str(todo.get("status") or "open"),
        "start_date": str(todo.get("start_date") or ""),
        "due_date": due_date,
        "end_date": str(todo.get("end_date") or due_date),
        "due_time": str(todo.get("due_time") or ""),
        "repeat_rule": str(todo.get("repeat_rule") or "once"),
        "priority": str(todo.get("priority") or "normal"),
        "tags": todo.get("tags") if isinstance(todo.get("tags"), list) else [],
        "source": str(todo.get("source") or ""),
        "created_at": str(todo.get("created_at") or ""),
        "updated_at": str(todo.get("updated_at") or ""),
        "completed_at": str(todo.get("completed_at") or ""),
    }


def _format_todo_line(todo: dict[str, Any]) -> str:
    summary = _todo_summary(todo)
    dates = _format_schedule(summary)
    parts = [
        summary["title"] or "(untitled)",
        f"id={summary['id']}" if summary["id"] else "",
        dates,
        summary["priority"] if summary["priority"] != "normal" else "",
        summary["status"] if summary["status"] != "open" else "",
    ]
    return " · ".join(part for part in parts if part)


def _format_schedule(todo: dict[str, Any]) -> str:
    start = str(todo.get("start_date") or "")
    due = str(todo.get("due_date") or todo.get("end_date") or "")
    due_time = str(todo.get("due_time") or "")
    repeat = str(todo.get("repeat_rule") or "once")
    if start and due and start != due:
        date_text = f"{start} to {due}"
    else:
        date_text = due or start or "unscheduled"
    if due_time:
        date_text = f"{date_text} {due_time}"
    if repeat and repeat != "once":
        return f"{repeat}, {date_text}"
    return date_text


def _format_todo_listing(data: dict[str, Any]) -> str:
    items = data.get("items") if isinstance(data.get("items"), list) else []
    scope = str(data.get("scope") or "today")
    if not items:
        return f"No todos found for {scope}."
    lines = [f"Todos for {scope} ({len(items)}/{data.get('total', len(items))}):"]
    for index, item in enumerate(items, start=1):
        if isinstance(item, dict):
            lines.append(f"{index}. {_format_todo_line(item)}")
    if data.get("truncated"):
        lines.append("Results truncated.")
    return "\n".join(lines)
