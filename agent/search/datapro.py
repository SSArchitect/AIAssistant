"""Volcengine professional datasets through the official Streamable HTTP MCP API."""
from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx

from agent.config import runtime_config


DATAPRO_URL = "https://datapro.hqd.cn-beijing.volces.com/mcp"
MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class DataProError(ValueError):
    """Safe, user-facing error; never include upstream text or credentials."""


def datapro_api_key() -> str:
    return runtime_config.get("search.datapro.api_key").strip() or runtime_config.doubao_api_key.strip()


def datapro_enabled() -> bool:
    return runtime_config.get("search.datapro.enabled", "true").strip().lower() not in {
        "0", "false", "no", "off",
    } and bool(datapro_api_key())


class DataProClient:
    def __init__(self, *, api_key: str, timeout: float = 60, transport: Any = None):
        self._api_key = api_key.strip()
        self._timeout = timeout
        self._transport = transport

    @classmethod
    def from_runtime_config(cls) -> "DataProClient":
        try:
            timeout = float(runtime_config.get("search.datapro.timeout", "60"))
        except (ValueError, TypeError):
            timeout = 60
        timeout = timeout if 0 < timeout <= 120 else 60
        return cls(api_key=datapro_api_key(), timeout=timeout)

    async def search(self, query: str, *, limit: int = 20) -> dict[str, Any]:
        if not isinstance(query, str) or not query.strip():
            raise DataProError("query is required")
        if not self._api_key:
            raise DataProError("Configure search.datapro.api_key or the Volcengine API key")
        try:
            # Bound the whole initialization + call, including a continuously active SSE stream.
            result = await asyncio.wait_for(self._search(query.strip()), timeout=self._timeout)
        except (asyncio.TimeoutError, httpx.TimeoutException):
            raise DataProError("Professional search timed out") from None
        except httpx.HTTPStatusError as exc:
            status = exc.response.status_code
            if status in {401, 403}:
                raise DataProError(
                    "Professional search authentication failed; configure the dedicated Agent Plan key "
                    "and enable professional datasets in the Volcengine console"
                ) from None
            raise DataProError(f"Professional search HTTP error ({status})") from None
        except httpx.HTTPError:
            raise DataProError("Professional search connection failed") from None
        except (ValueError, TypeError) as exc:
            if isinstance(exc, DataProError):
                raise
            raise DataProError("Invalid professional search response") from None

        payload = self._payload(result)
        items = payload["items"]
        limit = max(1, min(limit, 49))
        return {
            **payload,
            "source": "volcengine-datapro",
            "query": query.strip(),
            "items": items[:limit],
            "returned_count": min(len(items), limit),
            "truncated": len(items) > limit,
        }

    async def _search(self, query: str) -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=self._timeout, transport=self._transport,
            headers={"X-Agent-Plan-Key": self._api_key, "Accept": "application/json, text/event-stream"},
        ) as client:
            try:
                initialized = await self._rpc(client, "initialize", {
                    "protocolVersion": "2025-03-26", "capabilities": {},
                    "clientInfo": {"name": "agent-assistant", "version": "1.0.0"},
                }, 1)
                version = initialized.get("protocolVersion")
                if version not in {"2025-03-26", "2025-06-18", "2025-11-25"}:
                    raise DataProError("Unsupported professional search MCP protocol version")
                client.headers["MCP-Protocol-Version"] = version
                await self._rpc(client, "notifications/initialized", {}, None)
                # Verify the documented tool and query contract before issuing a paid call.
                catalog = await self._rpc(client, "tools/list", {}, 2)
                tools = catalog.get("tools")
                tool = next((t for t in tools if isinstance(t, dict) and t.get("name") == "dataPro_search"), None) if isinstance(tools, list) else None
                schema = tool.get("inputSchema", {}) if tool else {}
                properties = schema.get("properties", {}) if isinstance(schema, dict) else {}
                query_schema = properties.get("query", {}) if isinstance(properties, dict) else {}
                required = schema.get("required", []) if isinstance(schema, dict) else []
                if not isinstance(query_schema, dict) or query_schema.get("type") != "string" or not isinstance(required, list) or set(required) - {"query"}:
                    raise DataProError("Professional search tool or query schema is unavailable")
                return await self._rpc(client, "tools/call", {
                    "name": "dataPro_search", "arguments": {"query": query},
                }, 3)
            finally:
                if client.headers.get("Mcp-Session-Id"):
                    try:
                        await client.delete(DATAPRO_URL, timeout=2)
                    except httpx.HTTPError:
                        pass

    async def _rpc(self, client: httpx.AsyncClient, method: str, params: dict, request_id: int | None) -> dict:
        body: dict[str, Any] = {"jsonrpc": "2.0", "method": method, "params": params}
        if request_id is not None:
            body["id"] = request_id
        async with client.stream("POST", DATAPRO_URL, json=body) as response:
            response.raise_for_status()
            if method == "initialize" and response.headers.get("Mcp-Session-Id"):
                client.headers["Mcp-Session-Id"] = response.headers["Mcp-Session-Id"]
            if request_id is None:
                return {}
            if "text/event-stream" in response.headers.get("content-type", ""):
                data: list[str] = []
                size = 0
                async for line in response.aiter_lines():
                    size += len(line.encode("utf-8")) + 1
                    if size > MAX_RESPONSE_BYTES:
                        raise DataProError("Professional search response exceeds size limit")
                    if line.startswith("data:"):
                        data.append(line[5:].lstrip(" "))
                    elif not line and data:
                        message = json.loads("\n".join(data))
                        data = []
                        result = self._rpc_result(message, request_id)
                        if result is not None:
                            return result
            else:
                data_bytes = bytearray()
                async for chunk in response.aiter_bytes():
                    data_bytes.extend(chunk)
                    if len(data_bytes) > MAX_RESPONSE_BYTES:
                        raise DataProError("Professional search response exceeds size limit")
                result = self._rpc_result(json.loads(data_bytes), request_id)
                if result is not None:
                    return result
        raise DataProError("Professional search MCP response is missing")

    @staticmethod
    def _rpc_result(message: Any, request_id: int) -> dict | None:
        if not isinstance(message, dict) or message.get("jsonrpc") != "2.0":
            raise DataProError("Invalid professional search MCP response")
        if message.get("id") != request_id:
            return None
        if "error" in message:
            raise DataProError("Professional search MCP request failed")
        if not isinstance(message.get("result"), dict):
            raise DataProError("Invalid professional search MCP result")
        return message["result"]

    @staticmethod
    def _payload(result: dict) -> dict:
        if result.get("isError"):
            raise DataProError("Professional search tool failed; check dataset access and query")
        payload = result.get("structuredContent")
        if payload is None:
            content = result.get("content")
            texts = [c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"] if isinstance(content, list) else []
            try:
                payload = json.loads("\n".join(texts))
            except (ValueError, TypeError):
                raise DataProError("Invalid professional search dataset payload") from None
        if not isinstance(payload, dict) or payload.get("code") not in (0, "0"):
            raise DataProError("Professional search dataset request failed; check dataset access and query")
        if not isinstance(payload.get("items"), list) or any(not isinstance(item, dict) for item in payload["items"]):
            raise DataProError("Invalid professional search dataset items")
        return payload
