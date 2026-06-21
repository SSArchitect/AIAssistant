from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import json
import logging
import os
import shutil
import shlex
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urlparse
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field

from agent.config import runtime_config

logger = logging.getLogger(__name__)

SEARCH_SNIPPET_MAX_CHARS = 900


class SearchResult(BaseModel):
    title: str
    snippet: str = ""
    url: str = ""
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        ...


class StaticSearchProvider:
    def __init__(self, *, name: str = "local", documents: list[dict[str, Any]]):
        self.name = name
        self._documents = documents

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        terms = [term.lower() for term in query.split() if term.strip()]
        if not terms:
            return []

        scored: list[tuple[int, dict[str, Any]]] = []
        for doc in self._documents:
            text = " ".join(
                str(doc.get(key, ""))
                for key in ("title", "snippet", "content", "url")
            ).lower()
            score = sum(text.count(term) for term in terms)
            if score > 0:
                scored.append((score, doc))

        scored.sort(key=lambda item: item[0], reverse=True)
        return [
            SearchResult(
                title=str(doc.get("title") or doc.get("url") or "Untitled"),
                snippet=str(doc.get("snippet") or doc.get("content") or "")[:SEARCH_SNIPPET_MAX_CHARS],
                url=str(doc.get("url") or ""),
                source=str(doc.get("source") or self.name),
                metadata=_coerce_metadata(
                    doc,
                    excluded_keys={"title", "snippet", "content", "url", "source"},
                ),
            )
            for _, doc in scored[:limit]
        ]


class HTTPSearchProvider:
    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str = "",
        query_param: str = "q",
    ):
        self.name = name
        self._base_url = base_url
        self._api_key = api_key
        self._query_param = query_param

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                self._base_url,
                params={self._query_param: query, "limit": limit},
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()

        raw_results = self._extract_results(payload)
        return [
            self._coerce_result(item)
            for item in raw_results[:limit]
        ]

    def _extract_results(self, payload: Any) -> list[dict[str, Any]]:
        if isinstance(payload, list):
            return [item for item in payload if isinstance(item, dict)]
        if not isinstance(payload, dict):
            return []
        for key in ("results", "items", "data"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return []

    def _coerce_result(self, item: dict[str, Any]) -> SearchResult:
        title = item.get("title") or item.get("name") or item.get("url") or "Untitled"
        snippet = item.get("snippet") or item.get("summary") or item.get("content") or ""
        url = item.get("url") or item.get("link") or ""
        source = item.get("source") or self.name
        return SearchResult(
            title=str(title),
            snippet=str(snippet)[:SEARCH_SNIPPET_MAX_CHARS],
            url=str(url),
            source=str(source),
            metadata=_coerce_metadata(
                item,
                excluded_keys={"title", "name", "snippet", "summary", "content", "url", "link", "source"},
            ),
        )


class MiniMaxMCPSearchProvider:
    """MiniMax Token Plan MCP web search provider.

    The MCP server is launched per query over stdio. This keeps the integration
    small and avoids a long-lived process manager until generic MCP tool
    discovery exists in the workbench.
    """

    name = "minimax-mcp"

    def __init__(
        self,
        *,
        api_key: str,
        api_host: str = "https://api.minimaxi.com",
        command: str = "uvx",
        args: list[str] | None = None,
        timeout: float = 60,
    ):
        self._api_key = api_key
        self._api_host = api_host
        self._command = command
        self._args = args or ["minimax-coding-plan-mcp", "-y"]
        self._timeout = timeout

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        if not self._api_key:
            raise ValueError("MiniMax API key not configured")
        payload = await self._call_web_search(query)
        return self._coerce_payload(payload, limit=limit)

    async def _call_web_search(self, query: str) -> dict[str, Any]:
        env = dict(os.environ)
        env.update(
            {
                "MINIMAX_API_KEY": self._api_key,
                "MINIMAX_API_HOST": self._api_host,
            }
        )

        proc = await asyncio.create_subprocess_exec(
            self._resolve_command(),
            *self._args,
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            env=env,
        )
        try:
            await self._mcp_request(
                proc,
                request_id=1,
                method="initialize",
                params={
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {
                        "name": "agent-assistant",
                        "version": "0.1.0",
                    },
                },
            )
            await self._mcp_notification(proc, "notifications/initialized")
            response = await self._mcp_request(
                proc,
                request_id=2,
                method="tools/call",
                params={
                    "name": "web_search",
                    "arguments": {"query": query},
                },
            )
            result = response.get("result") or {}
            if result.get("isError"):
                raise ValueError(self._extract_mcp_text(result) or "MiniMax MCP search failed")
            text = self._extract_mcp_text(result)
            if not text:
                structured = result.get("structuredContent")
                if isinstance(structured, dict):
                    text = str(structured.get("text") or "")
            if not text:
                return {}
            payload = self._decode_payload_text(text)
            return payload if isinstance(payload, dict) else {}
        finally:
            await self._stop_process(proc)

    async def _mcp_notification(
        self,
        proc: asyncio.subprocess.Process,
        method: str,
        params: dict[str, Any] | None = None,
    ) -> None:
        message: dict[str, Any] = {
            "jsonrpc": "2.0",
            "method": method,
        }
        if params is not None:
            message["params"] = params
        assert proc.stdin is not None
        proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()

    async def _mcp_request(
        self,
        proc: asyncio.subprocess.Process,
        *,
        request_id: int,
        method: str,
        params: dict[str, Any],
    ) -> dict[str, Any]:
        message = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params,
        }
        assert proc.stdin is not None
        assert proc.stdout is not None
        proc.stdin.write((json.dumps(message) + "\n").encode())
        await proc.stdin.drain()

        while True:
            line = await asyncio.wait_for(proc.stdout.readline(), timeout=self._timeout)
            if not line:
                stderr = await self._read_stderr(proc)
                raise RuntimeError(f"MiniMax MCP process closed{': ' + stderr if stderr else ''}")
            try:
                response = json.loads(line)
            except json.JSONDecodeError:
                continue
            if response.get("id") != request_id:
                continue
            if "error" in response:
                error = response.get("error") or {}
                message = error.get("message") if isinstance(error, dict) else str(error)
                raise RuntimeError(message or "MiniMax MCP request failed")
            return response

    async def _stop_process(self, proc: asyncio.subprocess.Process) -> None:
        if proc.returncode is not None:
            return
        proc.terminate()
        try:
            await asyncio.wait_for(proc.wait(), timeout=5)
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()

    async def _read_stderr(self, proc: asyncio.subprocess.Process) -> str:
        if proc.stderr is None:
            return ""
        try:
            data = await asyncio.wait_for(proc.stderr.read(), timeout=1)
        except asyncio.TimeoutError:
            return ""
        text = data.decode(errors="replace").strip()
        if self._api_key:
            text = text.replace(self._api_key, "***")
        return text[-1000:]

    def _resolve_command(self) -> str:
        if os.path.isabs(self._command):
            return self._command
        found = shutil.which(self._command)
        if found:
            return found
        for candidate in (
            f"/opt/homebrew/bin/{self._command}",
            f"/usr/local/bin/{self._command}",
        ):
            if os.path.exists(candidate):
                return candidate
        return self._command

    def _extract_mcp_text(self, result: dict[str, Any]) -> str:
        content = result.get("content") or []
        if not isinstance(content, list):
            return ""
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text":
                text = block.get("text")
                if isinstance(text, str) and text.strip():
                    return text
        return ""

    def _decode_payload_text(self, text: str) -> dict[str, Any]:
        try:
            payload = json.loads(text)
        except json.JSONDecodeError:
            start = text.find("{")
            end = text.rfind("}")
            if start >= 0 and end > start:
                payload = json.loads(text[start:end + 1])
            else:
                preview = " ".join(text.split())[:200]
                raise ValueError(f"MiniMax MCP returned non-JSON search payload: {preview}")
        return payload if isinstance(payload, dict) else {}

    def _coerce_payload(self, payload: dict[str, Any], *, limit: int) -> list[SearchResult]:
        base_resp = payload.get("base_resp")
        if isinstance(base_resp, dict) and base_resp.get("status_code", 0) != 0:
            raise ValueError(str(base_resp.get("status_msg") or "MiniMax MCP search failed"))

        raw_results = payload.get("organic") or payload.get("results") or payload.get("items") or []
        if not isinstance(raw_results, list):
            return []

        results: list[SearchResult] = []
        for item in raw_results:
            if not isinstance(item, dict):
                continue
            title = item.get("title") or item.get("name") or item.get("link") or item.get("url") or "Untitled"
            url = item.get("link") or item.get("url") or ""
            snippet = item.get("snippet") or item.get("summary") or item.get("content") or ""
            metadata = _coerce_metadata(
                item,
                excluded_keys={"title", "name", "snippet", "summary", "content", "link", "url"},
            )
            results.append(
                SearchResult(
                    title=str(title),
                    snippet=str(snippet)[:SEARCH_SNIPPET_MAX_CHARS],
                    url=str(url),
                    source=self.name,
                    metadata=metadata,
                )
            )
            if len(results) >= limit:
                break
        return results


class DuckDuckGoSearchProvider:
    """Keyless web search fallback for local development.

    Production deployments should prefer `search.http.base_url` so search can
    be routed through the user's own aggregation service, API keys, ranking,
    and source allow-listing.
    """

    name = "web"

    def __init__(self, *, base_url: str = "https://duckduckgo.com/html/"):
        self._base_url = base_url

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        ) as client:
            response = await client.get(
                self._base_url,
                params={"q": query},
            )
            response.raise_for_status()

        parser = _DuckDuckGoHTMLParser(limit=limit)
        parser.feed(response.text)
        parser.close()
        return parser.results


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self, *, limit: int):
        super().__init__(convert_charrefs=True)
        self._limit = limit
        self._current: dict[str, str] | None = None
        self._capture_title = False
        self._capture_snippet = False
        self._title_parts: list[str] = []
        self._snippet_parts: list[str] = []
        self.results: list[SearchResult] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.results) >= self._limit:
            return

        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())
        if tag == "a" and "result__a" in classes:
            self._finish_current()
            self._current = {"url": self._clean_url(attr.get("href", ""))}
            self._title_parts = []
            self._snippet_parts = []
            self._capture_title = True
        elif self._current is not None and "result__snippet" in classes:
            self._capture_snippet = True

    def handle_endtag(self, tag: str) -> None:
        if tag == "a" and self._capture_title:
            self._capture_title = False
        if self._capture_snippet and tag in {"a", "td", "div"}:
            self._capture_snippet = False

    def handle_data(self, data: str) -> None:
        if self._capture_title:
            self._title_parts.append(data)
        elif self._capture_snippet:
            self._snippet_parts.append(data)

    def close(self) -> None:
        self._finish_current()
        super().close()

    def _finish_current(self) -> None:
        if self._current is None or len(self.results) >= self._limit:
            self._current = None
            return

        title = " ".join("".join(self._title_parts).split())
        snippet = " ".join("".join(self._snippet_parts).split())
        url = self._current.get("url", "")
        if title and url and not self._is_ad_url(url):
            self.results.append(
                SearchResult(
                    title=title,
                    snippet=snippet[:SEARCH_SNIPPET_MAX_CHARS],
                    url=url,
                    source=self.name,
                )
            )
        self._current = None

    @property
    def name(self) -> str:
        return "web"

    def _clean_url(self, url: str) -> str:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if "uddg" in query and query["uddg"]:
            return unquote(query["uddg"][0])
        return url

    def _is_ad_url(self, url: str) -> bool:
        parsed = urlparse(url)
        query = parse_qs(parsed.query)
        if parsed.netloc.endswith("duckduckgo.com") and parsed.path.endswith("/y.js"):
            return True
        return any(key in query for key in ("ad_domain", "ad_provider", "ad_type"))


class BingRSSSearchProvider:
    """Keyless Bing RSS search provider.

    This is a pragmatic fallback for local Pulse generation: RSS is much more
    stable to parse than search-result HTML and usually includes pubDate.
    """

    name = "bing-rss"

    def __init__(self, *, base_url: str = "https://www.bing.com/search"):
        self._base_url = base_url

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/124.0 Safari/537.36"
                )
            },
        ) as client:
            response = await client.get(
                self._base_url,
                params={"q": query, "format": "rss"},
            )
            response.raise_for_status()

        root = ET.fromstring(response.text)
        results: list[SearchResult] = []
        for item in root.findall("./channel/item"):
            title = _xml_text(item, "title")
            url = _xml_text(item, "link")
            snippet = _xml_text(item, "description")
            pub_date = _xml_text(item, "pubDate")
            if not title or not url:
                continue
            results.append(
                SearchResult(
                    title=title,
                    snippet=snippet[:SEARCH_SNIPPET_MAX_CHARS],
                    url=url,
                    source=self.name,
                    metadata={"pub_date": pub_date} if pub_date else {},
                )
            )
            if len(results) >= limit:
                break
        return results


class SearchService:
    def __init__(
        self,
        providers: list[SearchProvider] | None = None,
        *,
        retry_attempts: int = 3,
        retry_delay: float = 0.5,
    ):
        self._providers = providers or []
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay = max(0.0, retry_delay)
        self._last_provider_errors: list[str] = []

    @classmethod
    def from_runtime_config(cls) -> "SearchService":
        providers: list[SearchProvider] = []

        local_docs = runtime_config.get("search.local.documents")
        if local_docs:
            try:
                documents = json.loads(local_docs)
                if isinstance(documents, list):
                    providers.append(
                        StaticSearchProvider(name="local", documents=documents)
                    )
            except json.JSONDecodeError:
                pass

        http_base_url = runtime_config.get("search.http.base_url")
        if http_base_url:
            providers.append(
                HTTPSearchProvider(
                    name=runtime_config.get("search.http.name", "http"),
                    base_url=http_base_url,
                    api_key=runtime_config.get("search.http.api_key"),
                    query_param=runtime_config.get("search.http.query_param", "q"),
                )
            )

        minimax_enabled = runtime_config.get("search.minimax.enabled", "true").lower()
        minimax_api_key = runtime_config.get("search.minimax.api_key") or runtime_config.minimax_api_key
        if minimax_enabled not in {"0", "false", "no", "off"} and minimax_api_key:
            providers.append(
                MiniMaxMCPSearchProvider(
                    api_key=minimax_api_key,
                    api_host=runtime_config.get(
                        "search.minimax.api_host",
                        "https://api.minimaxi.com",
                    ),
                    command=runtime_config.get("search.minimax.command", "uvx"),
                    args=_parse_command_args(
                        runtime_config.get(
                            "search.minimax.args",
                            '["minimax-coding-plan-mcp", "-y"]',
                        )
                    ),
                    timeout=_parse_float(
                        runtime_config.get("search.minimax.timeout", "60"),
                        default=60,
                    ),
                )
            )

        bing_enabled = runtime_config.get("search.bing.enabled", "true").lower()
        if bing_enabled not in {"0", "false", "no", "off"}:
            providers.append(
                BingRSSSearchProvider(
                    base_url=runtime_config.get(
                        "search.bing.base_url",
                        "https://www.bing.com/search",
                    )
                )
            )

        web_enabled = runtime_config.get("search.web.enabled", "true").lower()
        if web_enabled not in {"0", "false", "no", "off"}:
            providers.append(
                DuckDuckGoSearchProvider(
                    base_url=runtime_config.get(
                        "search.web.base_url",
                        "https://duckduckgo.com/html/",
                    )
                )
            )

        return cls(
            providers,
            retry_attempts=_parse_int(
                runtime_config.get("search.retry.attempts", "3"),
                default=3,
            ),
            retry_delay=_parse_float(
                runtime_config.get("search.retry.delay_seconds", "0.5"),
                default=0.5,
            ),
        )

    @property
    def provider_names(self) -> list[str]:
        return [provider.name for provider in self._providers]

    @property
    def last_provider_errors(self) -> list[str]:
        return list(self._last_provider_errors)

    async def search(
        self,
        query: str,
        *,
        sources: list[str] | None = None,
        limit: int = 5,
    ) -> list[SearchResult]:
        selected = set(sources or [])
        providers = [
            provider
            for provider in self._providers
            if not selected or provider.name in selected
        ]
        results: list[SearchResult] = []
        seen: set[str] = set()
        provider_errors: list[str] = []
        provider_limit = limit
        if not selected and len(providers) > 1:
            provider_limit = max(1, (limit + len(providers) - 1) // len(providers))
        for provider in providers:
            try:
                provider_results = await self._search_provider_with_retries(
                    provider,
                    query,
                    limit=provider_limit,
                )
            except Exception as e:
                error_text = f"{provider.name}: {e}"
                provider_errors.append(error_text)
                logger.warning(
                    "Search provider failed; trying next provider",
                    extra={"provider": provider.name, "error": str(e)},
                )
                continue

            for result in provider_results:
                key = result.url or f"{result.source}:{result.title}"
                if key in seen:
                    continue
                seen.add(key)
                results.append(result)
                if len(results) >= limit and selected:
                    break
            if len(results) >= limit and selected:
                break
        self._last_provider_errors = provider_errors
        if not results and provider_errors and len(provider_errors) == len(providers):
            raise RuntimeError("; ".join(provider_errors))
        return results[:limit]

    async def _search_provider_with_retries(
        self,
        provider: SearchProvider,
        query: str,
        *,
        limit: int,
    ) -> list[SearchResult]:
        last_error: Exception | None = None
        for attempt in range(1, self._retry_attempts + 1):
            try:
                return await provider.search(query, limit=limit)
            except Exception as e:
                last_error = e
                if attempt >= self._retry_attempts:
                    break
                await asyncio.sleep(self._retry_delay * attempt)
        assert last_error is not None
        raise last_error


def _parse_command_args(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return ["minimax-coding-plan-mcp", "-y"]
    try:
        parsed = json.loads(raw)
        if isinstance(parsed, list):
            return [str(item) for item in parsed]
    except json.JSONDecodeError:
        pass
    return shlex.split(raw)


def _parse_float(raw: str, *, default: float) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _parse_int(raw: str, *, default: int) -> int:
    try:
        return int(raw)
    except (TypeError, ValueError):
        return default


def _xml_text(item: ET.Element, tag: str) -> str:
    child = item.find(tag)
    if child is None or child.text is None:
        return ""
    return " ".join(child.text.split())


def _coerce_metadata(
    item: dict[str, Any],
    *,
    excluded_keys: set[str],
) -> dict[str, Any]:
    metadata = dict(item.get("metadata") if isinstance(item.get("metadata"), dict) else {})
    for key, value in item.items():
        if key in excluded_keys or key == "metadata":
            continue
        metadata[key] = value
    for key, value in _extract_media_metadata(item).items():
        if value and not metadata.get(key):
            metadata[key] = value
    return metadata


def _extract_media_metadata(item: dict[str, Any]) -> dict[str, str]:
    thumbnail_url = _first_media_field(
        item,
        (
            "thumbnail_url",
            "thumbnailUrl",
            "thumbnail",
            "thumb",
            "poster",
            "cover",
        ),
    )
    image_url = _first_media_field(
        item,
        (
            "image_url",
            "imageUrl",
            "image",
            "images",
            "image_urls",
            "imageUrls",
            "og_image",
            "og:image",
            "image_src",
        ),
    )
    video_url = _first_media_field(
        item,
        (
            "video_url",
            "videoUrl",
            "video",
            "videos",
            "video_urls",
            "media_url",
            "mediaUrl",
            "embed_url",
            "embedUrl",
            "contentUrl",
            "player",
            "player_url",
        ),
    )

    nested_metadata = item.get("metadata")
    if isinstance(nested_metadata, dict):
        thumbnail_url = thumbnail_url or _first_media_field(
            nested_metadata,
            ("thumbnail_url", "thumbnailUrl", "thumbnail", "thumb", "poster", "cover"),
        )
        image_url = image_url or _first_media_field(
            nested_metadata,
            ("image_url", "imageUrl", "image", "images", "image_urls", "og_image", "og:image"),
        )
        video_url = video_url or _first_media_field(
            nested_metadata,
            ("video_url", "videoUrl", "video", "videos", "video_urls", "media_url", "embed_url"),
        )

    pagemap = item.get("pagemap")
    if isinstance(pagemap, dict):
        thumbnail_url = thumbnail_url or _first_media_url(pagemap.get("cse_thumbnail"))
        image_url = image_url or _first_media_url(pagemap.get("cse_image"))
        video_url = video_url or _first_media_url(pagemap.get("videoobject"))

    rich_snippet = item.get("rich_snippet")
    if isinstance(rich_snippet, dict):
        image_url = image_url or _first_media_url(rich_snippet.get("top"))

    media_url = video_url or image_url or thumbnail_url
    media_type = ""
    if video_url:
        media_type = "video"
    elif image_url or thumbnail_url:
        media_type = "image"

    return {
        "thumbnail_url": thumbnail_url,
        "image_url": image_url or thumbnail_url,
        "video_url": video_url,
        "media_url": media_url,
        "media_type": media_type,
    }


def _first_media_field(item: dict[str, Any], keys: tuple[str, ...]) -> str:
    for key in keys:
        value = _first_media_url(item.get(key))
        if value:
            return value
    return ""


def _first_media_url(value: Any) -> str:
    if isinstance(value, str):
        return value.strip()
    if isinstance(value, dict):
        for key in (
            "url",
            "src",
            "link",
            "contentUrl",
            "content_url",
            "image_url",
            "imageUrl",
            "thumbnail_url",
            "thumbnailUrl",
            "video_url",
            "videoUrl",
            "embed_url",
            "embedUrl",
            "poster",
        ):
            nested = _first_media_url(value.get(key))
            if nested:
                return nested
        return ""
    if isinstance(value, list):
        for item in value:
            nested = _first_media_url(item)
            if nested:
                return nested
    return ""
