from __future__ import annotations

import os
import posixpath
from collections import defaultdict
from typing import Any, Callable
from urllib.parse import quote

import httpx

from agent.config import runtime_config
from agent.skills.base import Skill, SkillMetadata, SkillParameter, SkillResult


DRIVE_TOOL_NAMES = {"ls_drive", "search_drive", "read_drive", "save_drive", "mkdir_drive"}
_DEFAULT_GATEWAY_BASE_URL = "http://localhost:8080"


class DriveGatewayError(RuntimeError):
    def __init__(self, message: str, *, status_code: int | None = None):
        super().__init__(message)
        self.status_code = status_code


class DriveGatewayClient:
    def __init__(
        self,
        base_url: str | None = None,
        *,
        timeout: float = 20.0,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.base_url = _normalize_gateway_base_url(base_url or _drive_gateway_base_url())
        self.timeout = timeout
        self.transport = transport

    @classmethod
    def from_runtime_config(cls) -> "DriveGatewayClient":
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
        headers = {"X-User-ID": _normalize_user_id(user_id)}
        if json_body is not None:
            json_body = {"user_id": _normalize_user_id(user_id), **json_body}
        async with httpx.AsyncClient(timeout=self.timeout, transport=self.transport) as client:
            response = await client.request(
                method,
                self._endpoint(path),
                headers=headers,
                params=params,
                json=json_body,
            )
        if response.status_code >= 400:
            message = _extract_error_message(response)
            raise DriveGatewayError(message, status_code=response.status_code)
        try:
            payload = response.json()
        except ValueError as exc:
            raise DriveGatewayError("drive gateway returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise DriveGatewayError("drive gateway returned an unexpected payload")
        return payload

    async def tree(self, user_id: str) -> dict[str, Any]:
        return await self._request("GET", "/drive/tree", user_id=user_id)

    async def list_items(self, user_id: str, parent_id: str = "") -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/drive/items",
            user_id=user_id,
            params={"parent_id": parent_id} if parent_id else None,
        )
        return _dict_list(payload.get("items"))

    async def get_item(self, user_id: str, item_id: str) -> dict[str, Any]:
        payload = await self._request("GET", f"/drive/items/{quote(item_id, safe='')}", user_id=user_id)
        item = payload.get("item")
        if not isinstance(item, dict):
            raise DriveGatewayError("drive item was not returned")
        return item

    async def search(self, user_id: str, query: str) -> list[dict[str, Any]]:
        payload = await self._request(
            "GET",
            "/drive/search",
            user_id=user_id,
            params={"q": query},
        )
        return _dict_list(payload.get("results"))

    async def create_folder(self, user_id: str, parent_id: str, name: str) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            "/drive/folders",
            user_id=user_id,
            json_body={"parent_id": parent_id, "name": name},
        )
        item = payload.get("item")
        if not isinstance(item, dict):
            raise DriveGatewayError("created folder was not returned")
        return item

    async def create_file(
        self,
        user_id: str,
        *,
        parent_id: str,
        name: str,
        content: str,
        mime_type: str = "",
        encoding: str = "",
        summary: str = "",
        tags: list[str] | None = None,
    ) -> dict[str, Any]:
        payload = await self._request(
            "POST",
            "/drive/files",
            user_id=user_id,
            json_body={
                "parent_id": parent_id,
                "name": name,
                "mime_type": mime_type,
                "encoding": encoding,
                "content": content,
                "summary": summary,
                "tags": tags or [],
            },
        )
        item = payload.get("item")
        if not isinstance(item, dict):
            raise DriveGatewayError("created file was not returned")
        return item


class _DriveIndex:
    def __init__(self, flat_items: list[dict[str, Any]]):
        self.flat_items = flat_items
        self.by_id = {str(item.get("id") or ""): item for item in flat_items if str(item.get("id") or "")}
        self.children_by_parent: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item in flat_items:
            self.children_by_parent[str(item.get("parent_id") or "")].append(item)
        self.root = self._find_root()

    def _find_root(self) -> dict[str, Any] | None:
        roots = [
            item
            for item in self.flat_items
            if str(item.get("type") or "") == "folder" and not str(item.get("parent_id") or "").strip()
        ]
        return roots[0] if roots else None

    def path_for(self, item: dict[str, Any]) -> str:
        root_id = str((self.root or {}).get("id") or "")
        parts: list[str] = []
        current = item
        seen: set[str] = set()
        while current:
            item_id = str(current.get("id") or "")
            if not item_id or item_id in seen:
                break
            seen.add(item_id)
            if item_id != root_id:
                name = str(current.get("name") or "").strip()
                if name:
                    parts.append(name)
            parent_id = str(current.get("parent_id") or "")
            if not parent_id:
                break
            current = self.by_id.get(parent_id)
        return "/" + "/".join(reversed(parts))

    def resolve(self, path: str, *, folder_only: bool = False) -> dict[str, Any]:
        if self.root is None:
            raise ValueError("drive root was not found")
        normalized = _normalize_drive_path(path)
        if normalized == "/":
            if folder_only:
                return self.root
            return self.root
        segments = [part for part in normalized.strip("/").split("/") if part]
        root_name = str(self.root.get("name") or "").strip()
        if segments and root_name and _name_equals(segments[0], root_name):
            segments = segments[1:]
        current = self.root
        for index, segment in enumerate(segments):
            parent_id = str(current.get("id") or "")
            is_last = index == len(segments) - 1
            matches = [
                child
                for child in self.children_by_parent.get(parent_id, [])
                if _name_equals(str(child.get("name") or ""), segment)
                and (not folder_only or is_last or str(child.get("type") or "") == "folder")
            ]
            if folder_only or not is_last:
                matches = [item for item in matches if str(item.get("type") or "") == "folder"]
            if not matches:
                raise ValueError(f"path not found: {normalized}")
            if len(matches) > 1:
                ids = ", ".join(str(item.get("id") or "") for item in matches[:5])
                raise ValueError(f"path is ambiguous: {normalized}; use item_id/folder_id instead ({ids})")
            current = matches[0]
        return current


class _DriveTool(Skill):
    auto_discover = False

    def __init__(self, client_factory: Callable[[], DriveGatewayClient] | None = None):
        self._client_factory = client_factory or DriveGatewayClient.from_runtime_config

    def _client(self) -> DriveGatewayClient:
        return self._client_factory()

    def _user_id(self, kwargs: dict[str, Any]) -> str:
        user_id = _normalize_user_id(kwargs.get("_user_id"))
        if not user_id:
            raise ValueError("user context is required")
        return user_id

    async def _index(self, client: DriveGatewayClient, user_id: str) -> _DriveIndex:
        payload = await client.tree(user_id)
        return _DriveIndex(_dict_list(payload.get("flat_items")))


class DriveListSkill(_DriveTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="ls_drive",
            description=(
                "列出当前用户网盘目录下的文件和文件夹。它不是服务器文件系统命令；"
                "用户要查看网盘路径、目录内容或保存位置时使用。"
            ),
            parameters=[
                SkillParameter(
                    name="path",
                    type="string",
                    description="网盘目录路径，默认 /。例如 /、/研究资料。也可以使用 folder_id 精确定位。",
                    required=False,
                    default="/",
                ),
                SkillParameter(
                    name="folder_id",
                    type="string",
                    description="可选目录 ID；如果提供，会优先于 path。",
                    required=False,
                ),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="返回条数上限，默认 50，最多 200。",
                    required=False,
                    default=50,
                ),
            ],
            tags=["drive", "files"],
            source="builtin",
        )

    async def execute(self, **kwargs) -> SkillResult:
        try:
            user_id = self._user_id(kwargs)
            folder_id = str(kwargs.get("folder_id") or "").strip()
            path = str(kwargs.get("path") or "/").strip() or "/"
            limit = _coerce_int(kwargs.get("limit"), default=50, minimum=1, maximum=200)
            client = self._client()
            folder = await _resolve_folder(client, user_id, folder_id=folder_id, path=path)
            items = await client.list_items(user_id, str(folder.get("id") or ""))
            visible_items = items[:limit]
            data = {
                "folder": _item_summary(folder, path=await _item_path(client, user_id, folder)),
                "items": [_item_summary(item) for item in visible_items],
                "total": len(items),
                "truncated": len(items) > len(visible_items),
            }
            return SkillResult(
                success=True,
                data=data,
                display_text=_format_listing(data["folder"], visible_items, len(items)),
            )
        except (DriveGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class DriveSearchSkill(_DriveTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="search_drive",
            description="在当前用户网盘文件名、摘要、标签和文本内容中搜索文件。",
            parameters=[
                SkillParameter(name="query", type="string", description="搜索关键词或自然语言查询。", required=True),
                SkillParameter(
                    name="limit",
                    type="integer",
                    description="返回结果上限，默认 10，最多 50。",
                    required=False,
                    default=10,
                ),
            ],
            tags=["drive", "search", "files"],
            source="builtin",
        )

    async def execute(self, **kwargs) -> SkillResult:
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return SkillResult(success=False, error="query is required")
        try:
            user_id = self._user_id(kwargs)
            limit = _coerce_int(kwargs.get("limit"), default=10, minimum=1, maximum=50)
            results = (await self._client().search(user_id, query))[:limit]
            data_results = []
            for result in results:
                item = result.get("item") if isinstance(result.get("item"), dict) else {}
                data_results.append(
                    {
                        "item": _item_summary(item),
                        "score": result.get("score"),
                        "snippet": str(result.get("snippet") or ""),
                    }
                )
            return SkillResult(
                success=True,
                data={"query": query, "results": data_results, "total": len(results)},
                display_text=_format_search_results(query, data_results),
            )
        except (DriveGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class DriveReadSkill(_DriveTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="read_drive",
            description="读取当前用户网盘中的文本文件内容。读取目录请先用 ls_drive。",
            parameters=[
                SkillParameter(name="item_id", type="string", description="文件 ID；如果提供，会优先于 path。", required=False),
                SkillParameter(name="path", type="string", description="网盘文件路径，例如 /研究/notes.md。", required=False),
                SkillParameter(
                    name="max_chars",
                    type="integer",
                    description="最多返回字符数，默认 12000，最多 50000。",
                    required=False,
                    default=12000,
                ),
            ],
            tags=["drive", "files"],
            source="builtin",
        )

    async def execute(self, **kwargs) -> SkillResult:
        try:
            user_id = self._user_id(kwargs)
            item_id = str(kwargs.get("item_id") or "").strip()
            path = str(kwargs.get("path") or "").strip()
            max_chars = _coerce_int(kwargs.get("max_chars"), default=12000, minimum=100, maximum=50000)
            client = self._client()
            if item_id:
                item = await client.get_item(user_id, item_id)
            else:
                if not path:
                    return SkillResult(success=False, error="item_id or path is required")
                index = await self._index(client, user_id)
                item = index.resolve(path)
                item = await client.get_item(user_id, str(item.get("id") or ""))
            if str(item.get("type") or "") != "file":
                return SkillResult(success=False, error="folders cannot be read; use ls_drive to inspect a folder")
            item_path = await _item_path(client, user_id, item)
            content = str(item.get("content") or "")
            truncated = len(content) > max_chars
            if truncated:
                content = content[:max_chars]
            data = {
                "item": _item_summary(item, path=item_path),
                "content": content,
                "truncated": truncated,
                "encoding": str(item.get("encoding") or ""),
            }
            return SkillResult(
                success=True,
                data=data,
                display_text=_format_read_result(data),
            )
        except (DriveGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class DriveSaveSkill(_DriveTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="save_drive",
            description=(
                "把文本内容保存到当前用户网盘。模型只需要提供文件名/路径和内容；"
                "用户身份由系统注入。当前不覆盖已有同名文件。"
            ),
            parameters=[
                SkillParameter(name="content", type="string", description="要保存的文本内容。", required=True),
                SkillParameter(name="name", type="string", description="文件名，例如 notes.md。path 已包含文件名时可省略。", required=False),
                SkillParameter(name="path", type="string", description="完整网盘文件路径，例如 /研究/notes.md。", required=False),
                SkillParameter(name="folder_path", type="string", description="保存目录路径，默认 /。", required=False),
                SkillParameter(name="folder_id", type="string", description="保存目录 ID；如果提供，会优先于 folder_path。", required=False),
                SkillParameter(
                    name="mime_type",
                    type="string",
                    description="MIME 类型，默认 text/plain; charset=utf-8。",
                    required=False,
                    default="text/plain; charset=utf-8",
                ),
                SkillParameter(name="summary", type="string", description="可选摘要；留空则由网关自动生成。", required=False),
                SkillParameter(name="tags", type="string", description="可选标签，逗号分隔。", required=False),
            ],
            tags=["drive", "files", "write"],
            source="builtin",
        )

    async def execute(self, **kwargs) -> SkillResult:
        content = str(kwargs.get("content") or "")
        if not content.strip():
            return SkillResult(success=False, error="content is required")
        try:
            user_id = self._user_id(kwargs)
            name, folder_path = _save_target(
                path=kwargs.get("path"),
                name=kwargs.get("name"),
                folder_path=kwargs.get("folder_path"),
            )
            folder_id = str(kwargs.get("folder_id") or kwargs.get("parent_id") or "").strip()
            client = self._client()
            folder = await _resolve_folder(client, user_id, folder_id=folder_id, path=folder_path)
            siblings = await client.list_items(user_id, str(folder.get("id") or ""))
            existing = [
                item
                for item in siblings
                if _name_equals(str(item.get("name") or ""), name)
            ]
            if existing:
                existing_id = str(existing[0].get("id") or "")
                return SkillResult(
                    success=False,
                    error=f"drive item already exists in target folder: {name} ({existing_id})",
                    data={"existing": _item_summary(existing[0])},
                )
            item = await client.create_file(
                user_id,
                parent_id=str(folder.get("id") or ""),
                name=name,
                content=content,
                mime_type=str(kwargs.get("mime_type") or "text/plain; charset=utf-8").strip(),
                summary=str(kwargs.get("summary") or "").strip(),
                tags=_coerce_tags(kwargs.get("tags")),
            )
            data = {"item": _item_summary(item), "folder": _item_summary(folder)}
            return SkillResult(
                success=True,
                data=data,
                display_text=f"Saved {item.get('name')} to drive folder {folder.get('name')} ({item.get('id')}).",
            )
        except (DriveGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


class DriveMkdirSkill(_DriveTool):
    auto_discover = True

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name="mkdir_drive",
            description="在当前用户网盘中新建文件夹。当前只创建最后一级目录，不递归创建缺失父目录。",
            parameters=[
                SkillParameter(name="name", type="string", description="新文件夹名。path 已包含最终目录名时可省略。", required=False),
                SkillParameter(name="path", type="string", description="完整目录路径，例如 /研究/素材。", required=False),
                SkillParameter(name="parent_path", type="string", description="父目录路径，默认 /。", required=False),
                SkillParameter(name="parent_id", type="string", description="父目录 ID；如果提供，会优先于 parent_path。", required=False),
            ],
            tags=["drive", "files", "write"],
            source="builtin",
        )

    async def execute(self, **kwargs) -> SkillResult:
        try:
            user_id = self._user_id(kwargs)
            name, parent_path = _mkdir_target(
                path=kwargs.get("path"),
                name=kwargs.get("name"),
                parent_path=kwargs.get("parent_path"),
            )
            parent_id = str(kwargs.get("parent_id") or kwargs.get("folder_id") or "").strip()
            client = self._client()
            parent = await _resolve_folder(client, user_id, folder_id=parent_id, path=parent_path)
            siblings = await client.list_items(user_id, str(parent.get("id") or ""))
            for item in siblings:
                if _name_equals(str(item.get("name") or ""), name) and str(item.get("type") or "") == "folder":
                    data = {"item": _item_summary(item), "parent": _item_summary(parent), "already_exists": True}
                    return SkillResult(
                        success=True,
                        data=data,
                        display_text=f"Folder already exists: {name} ({item.get('id')}).",
                    )
            item = await client.create_folder(user_id, str(parent.get("id") or ""), name)
            data = {"item": _item_summary(item), "parent": _item_summary(parent), "already_exists": False}
            return SkillResult(
                success=True,
                data=data,
                display_text=f"Created folder {item.get('name')} ({item.get('id')}).",
            )
        except (DriveGatewayError, ValueError) as exc:
            return SkillResult(success=False, error=str(exc))


async def _resolve_folder(
    client: DriveGatewayClient,
    user_id: str,
    *,
    folder_id: str = "",
    path: str = "/",
) -> dict[str, Any]:
    if folder_id:
        item = await client.get_item(user_id, folder_id)
        if str(item.get("type") or "") != "folder":
            raise ValueError(f"item is not a folder: {folder_id}")
        return item
    index = _DriveIndex(_dict_list((await client.tree(user_id)).get("flat_items")))
    item = index.resolve(path or "/", folder_only=True)
    if str(item.get("type") or "") != "folder":
        raise ValueError(f"path is not a folder: {path}")
    return item


async def _item_path(client: DriveGatewayClient, user_id: str, item: dict[str, Any]) -> str:
    try:
        index = _DriveIndex(_dict_list((await client.tree(user_id)).get("flat_items")))
        return index.path_for(item)
    except Exception:
        return ""


def _drive_gateway_base_url() -> str:
    return (
        runtime_config.get("tool.drive.gateway_base_url")
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
    return response.text or response.reason_phrase or f"drive gateway status {response.status_code}"


def _dict_list(value: Any) -> list[dict[str, Any]]:
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _normalize_drive_path(value: Any) -> str:
    raw = str(value or "/").strip().strip("`'\"")
    if not raw or raw == ".":
        return "/"
    normalized = posixpath.normpath("/" + raw.lstrip("/"))
    if normalized == "/.":
        return "/"
    segments = [segment.strip() for segment in normalized.split("/") if segment.strip()]
    return "/" + "/".join(segments) if segments else "/"


def _name_equals(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def _coerce_int(value: Any, *, default: int, minimum: int, maximum: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        parsed = default
    return max(minimum, min(parsed, maximum))


def _coerce_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw_tags = [str(item).strip() for item in value]
    else:
        raw_tags = [item.strip() for item in str(value or "").split(",")]
    return [tag for tag in raw_tags if tag]


def _save_target(*, path: Any, name: Any, folder_path: Any) -> tuple[str, str]:
    target_name = str(name or "").strip()
    target_folder_path = str(folder_path or "").strip() or "/"
    raw_path = str(path or "").strip()
    if raw_path:
        normalized = _normalize_drive_path(raw_path)
        if normalized == "/":
            raise ValueError("path must include a file name")
        inferred_folder, inferred_name = posixpath.split(normalized)
        target_name = target_name or inferred_name
        if not str(folder_path or "").strip():
            target_folder_path = inferred_folder or "/"
    target_name = _clean_drive_name(target_name)
    if not target_name:
        raise ValueError("name or path with a file name is required")
    return target_name, _normalize_drive_path(target_folder_path)


def _mkdir_target(*, path: Any, name: Any, parent_path: Any) -> tuple[str, str]:
    target_name = str(name or "").strip()
    target_parent_path = str(parent_path or "").strip() or "/"
    raw_path = str(path or "").strip()
    if raw_path:
        normalized = _normalize_drive_path(raw_path)
        if normalized == "/":
            raise ValueError("path must include a folder name")
        inferred_parent, inferred_name = posixpath.split(normalized)
        target_name = target_name or inferred_name
        if not str(parent_path or "").strip():
            target_parent_path = inferred_parent or "/"
    target_name = _clean_drive_name(target_name)
    if not target_name:
        raise ValueError("name or path with a folder name is required")
    return target_name, _normalize_drive_path(target_parent_path)


def _clean_drive_name(value: str) -> str:
    value = str(value or "").replace("/", " ").replace("\\", " ").strip()
    return " ".join(value.split())


def _item_summary(item: dict[str, Any], *, path: str = "") -> dict[str, Any]:
    return {
        "id": str(item.get("id") or ""),
        "parent_id": str(item.get("parent_id") or ""),
        "type": str(item.get("type") or ""),
        "name": str(item.get("name") or ""),
        "path": path,
        "mime_type": str(item.get("mime_type") or ""),
        "size": item.get("size") or 0,
        "summary": str(item.get("summary") or ""),
        "tags": item.get("tags") if isinstance(item.get("tags"), list) else [],
        "updated_at": str(item.get("updated_at") or ""),
    }


def _format_listing(folder: dict[str, Any], items: list[dict[str, Any]], total: int) -> str:
    folder_name = folder.get("path") or folder.get("name") or "/"
    if not items:
        return f"{folder_name} is empty."
    lines = [f"{folder_name} ({total} item{'s' if total != 1 else ''}):"]
    for item in items:
        marker = "dir " if str(item.get("type") or "") == "folder" else "file"
        size = item.get("size") or 0
        lines.append(f"- [{marker}] {item.get('name')} ({item.get('id')}, {size} bytes)")
    return "\n".join(lines)


def _format_search_results(query: str, results: list[dict[str, Any]]) -> str:
    if not results:
        return f"No drive files matched: {query}"
    lines = [f"Drive search results for {query}:"]
    for result in results:
        item = result.get("item") or {}
        snippet = str(result.get("snippet") or "").strip()
        suffix = f" - {snippet}" if snippet else ""
        lines.append(f"- {item.get('name')} ({item.get('id')}){suffix}")
    return "\n".join(lines)


def _format_read_result(data: dict[str, Any]) -> str:
    item = data.get("item") or {}
    content = str(data.get("content") or "")
    truncated = " [truncated]" if data.get("truncated") else ""
    return f"{item.get('name')} ({item.get('id')}){truncated}\n\n{content}"
