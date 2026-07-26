from __future__ import annotations

import asyncio
from html.parser import HTMLParser
import ipaddress
import json
import logging
import os
import re
import shutil
import shlex
from time import perf_counter
import xml.etree.ElementTree as ET
from urllib.parse import parse_qs, unquote, urljoin, urlparse
from typing import Any, Protocol

import httpx
from pydantic import BaseModel, Field, model_validator

from agent.config import runtime_config
from agent.search.recall import DEFAULT_RECALL_MAX_QUERIES, build_query_rewrite_plan
from agent.search.ranking import (
    DEFAULT_MIN_RANK_SCORE,
    diversify_ranked_results,
    rank_search_results,
    search_query_terms,
    search_result_relevance_score,
)

logger = logging.getLogger(__name__)

SEARCH_SNIPPET_MAX_CHARS = 900
WEB_PAGE_DEFAULT_CHARS = 6000
WEB_PAGE_HARD_MAX_CHARS = 12000
WEB_PAGE_OPEN_RESULT_LIMIT = 3
SEARCH_IMAGE_ENRICH_DEFAULT_LIMIT = 3
SEARCH_IMAGE_ENRICH_MAX_LIMIT = 5
SEARCH_IMAGE_ENRICH_TIMEOUT_SECONDS = 8.0
SEARCH_IMAGE_ENRICH_MAX_REDIRECTS = 5
SEARCH_IMAGE_ENRICH_MAX_PROBES = 10
SEARCH_IMAGE_ENRICH_PROBE_MULTIPLIER = 3
SEARCH_IMAGE_ENRICH_CONCURRENCY = 3
SEARCH_IMAGE_CANDIDATE_MAX_PER_RESULT = 4
SEARCH_IMAGE_VALIDATE_MAX_BYTES = 64_000
SEARCH_IMAGE_TEXT_SCAN_MAX_CHARS = 100_000
SEARCH_IMAGE_TEXT_CANDIDATE_MAX = 16
WEB_PAGE_PARSE_MAX_CHARS = 1_000_000
WEB_PAGE_MEDIA_PARSE_MAX_BYTES = 512_000
SEARCH_PROVIDER_LIMIT_MULTIPLIER = 2
SEARCH_PROVIDER_LIMIT_MAX = 20
SEARCH_MIN_PROVIDER_COVERAGE = 2
SEARCH_RANK_MIN_SCORE = DEFAULT_MIN_RANK_SCORE
SEARCH_RECALL_MAX_QUERIES = DEFAULT_RECALL_MAX_QUERIES
SEARCH_RECALL_QUERY_TIMEOUT_SECONDS = 10.0
SEARCH_LLM_REWRITE_ENABLED = True
SEARCH_LLM_REWRITE_MAX_QUERIES = 4
SEARCH_LLM_REWRITE_TIMEOUT_SECONDS = 12.0
SEARCH_LLM_REWRITE_MAX_QUERY_CHARS = 180
SEARCH_LLM_RERANK_ENABLED = True
SEARCH_LLM_RERANK_MAX_CANDIDATES = 10
SEARCH_LLM_RERANK_TIMEOUT_SECONDS = 20.0
SEARCH_LLM_RERANK_MIN_SCORE = 0.5
WEB_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0 Safari/537.36"
)
PUBLIC_HTTP_URL_RE = re.compile(r"https?://[^\s<>\[\]{}\"'`，。！？；、【】]+", re.IGNORECASE)
MARKDOWN_IMAGE_URL_RE = re.compile(
    r"!\[[^\]\r\n]{0,500}\]\(\s*(?:<([^>\r\n]+)>|([^\s)\r\n]+))",
    re.IGNORECASE,
)
HTML_IMAGE_SRC_RE = re.compile(
    r"""<img\b[^>]{0,2000}?\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))""",
    re.IGNORECASE,
)
URL_SURROUNDING_CHARS = " \t\r\n【】[]()（）<>\"'`.,，。!?！？;；:：、"


class SearchResult(BaseModel):
    title: str
    snippet: str = ""
    url: str = ""
    source: str = ""
    thumbnail_url: str = ""
    image_url: str = ""
    media_url: str = ""
    media_type: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def populate_media_fields(self) -> "SearchResult":
        media = _extract_media_metadata(
            {
                "thumbnail_url": self.thumbnail_url,
                "image_url": self.image_url,
                "media_url": self.media_url,
                "media_type": self.media_type,
                "metadata": self.metadata,
            }
        )
        self.thumbnail_url = media["thumbnail_url"]
        self.image_url = media["image_url"]
        self.media_url = media["media_url"]
        self.media_type = media["media_type"]

        metadata = dict(self.metadata)
        for key, value in media.items():
            if value and not metadata.get(key):
                metadata[key] = value
        self.metadata = metadata
        return self


class WebPageContent(BaseModel):
    url: str
    final_url: str = ""
    title: str = ""
    description: str = ""
    content: str = ""
    content_type: str = ""
    status_code: int = 0
    metadata: dict[str, Any] = Field(default_factory=dict)


def extract_public_http_urls(text: str) -> list[str]:
    urls: list[str] = []
    seen: set[str] = set()
    for match in PUBLIC_HTTP_URL_RE.finditer(str(text or "")):
        url = match.group(0).rstrip(URL_SURROUNDING_CHARS)
        if not url or url in seen:
            continue
        parsed = urlparse(url)
        if parsed.scheme in {"http", "https"} and parsed.netloc:
            urls.append(url)
            seen.add(url)
    return urls


def single_public_http_url(text: str) -> str | None:
    value = str(text or "").strip()
    urls = extract_public_http_urls(value)
    if len(urls) != 1:
        return None
    remainder = value.replace(urls[0], "", 1).strip(URL_SURROUNDING_CHARS)
    return urls[0] if not remainder else None


def search_result_from_page(
    page: WebPageContent,
    *,
    source: str = "direct-url",
    snippet_chars: int = SEARCH_SNIPPET_MAX_CHARS,
) -> SearchResult:
    title = page.title or page.final_url or page.url
    snippet = page.description or page.content
    media = _extract_media_metadata(page.metadata)
    metadata = {
        "direct_url_open": True,
        "page": page.model_dump(mode="json"),
    }
    metadata.update({key: value for key, value in media.items() if value})
    return SearchResult(
        title=title,
        snippet=snippet[:snippet_chars],
        url=page.final_url or page.url,
        source=source,
        thumbnail_url=media["thumbnail_url"],
        image_url=media["image_url"],
        media_url=media["media_url"],
        media_type=media["media_type"],
        metadata=metadata,
    )


class SearchProvider(Protocol):
    name: str

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        ...


class SearchQueryRewriter(Protocol):
    name: str
    max_queries: int

    async def rewrite(
        self,
        query: str,
        *,
        max_queries: int,
        lexical_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        ...


class SearchReranker(Protocol):
    name: str
    max_candidates: int

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        *,
        limit: int,
        query_context: dict[str, Any] | None = None,
    ) -> tuple[list[SearchResult], dict[str, Any]]:
        ...


class LLMSearchQueryRewriter:
    """Use an LLM to produce recall-oriented query variants with lexical fallback."""

    def __init__(
        self,
        provider: Any,
        *,
        name: str,
        max_queries: int = SEARCH_LLM_REWRITE_MAX_QUERIES,
        timeout_seconds: float = SEARCH_LLM_REWRITE_TIMEOUT_SECONDS,
    ):
        self._provider = provider
        self.name = name
        self.max_queries = max(1, min(max_queries, SEARCH_PROVIDER_LIMIT_MAX))
        self._timeout_seconds = max(0.1, timeout_seconds)

    async def rewrite(
        self,
        query: str,
        *,
        max_queries: int,
        lexical_plan: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        from agent.llm.base import LLMMessage

        max_queries = max(1, min(max_queries, self.max_queries, SEARCH_PROVIDER_LIMIT_MAX))
        lexical_plan = lexical_plan or build_query_rewrite_plan(
            query,
            max_queries=max_queries,
        )
        original_query = str(lexical_plan.get("original_query") or query or "").strip()
        lexical_queries = _sanitize_rewrite_queries(
            lexical_plan.get("queries"),
            max_queries=SEARCH_PROVIDER_LIMIT_MAX,
        )
        query_context_payload = {
            "original_query": original_query,
            "lexical_strategy": lexical_plan.get("strategy") or "",
            "lexical_queries": lexical_queries,
            "max_queries": max_queries,
            "language_policy": {
                "target": "尽量同时覆盖原始语言、简体中文和英文",
                "reason": "搜索 provider 可能偏中文或偏英文，双语 query 可降低单语召回漏失",
                "original_language": _query_language_bucket(original_query),
            },
        }
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是搜索召回 query rewrite 节点。目标是提高候选召回覆盖，不回答问题，"
                    "不做最终相关性判断。可以使用模型的通用知识生成多种搜索 query："
                    "同义词、常见中英文名、缩写/全称、产品型号拆分、专有名词规范写法、"
                    "跨语言翻译，以及用户已表达的任务或文档形态词。必须忠于原始查询，保留关键实体、"
                    "数字、版本、型号、品牌、标题、时间和限定条件；不要把未被用户表达支持的"
                    "结论、类别、用途或唯一解释写进 query。需要做双语覆盖：当原始查询主要是英文时，"
                    "至少给出一条忠实的简体中文 query；当原始查询主要是中文时，至少给出一条英文或"
                    "中英混合 query；当原始查询已中英混合时，尽量保留专有名词并给出中文侧和英文侧"
                    "不同召回角度。输出 query 要彼此有召回角度差异，适合直接交给通用搜索引擎。"
                    "只返回严格 JSON。"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    "原始查询与词法兜底 JSON：\n"
                    f"{json.dumps(query_context_payload, ensure_ascii=False)}\n\n"
                    "请返回这个精确结构：\n"
                    '{"queries":["query 1","query 2"],"reason":"short reason"}\n'
                    "要求：queries 最多使用 max_queries 条；优先给出能互补召回的短 query；"
                    "可以包含原始查询或词法 query，但不要只机械重复；如果可以安全翻译，"
                    "结果里要同时出现中文 query 和英文 query。"
                ),
            ),
        ]

        response = await asyncio.wait_for(
            self._provider.chat(messages, temperature=0),
            timeout=self._timeout_seconds,
        )
        payload = _json_object_from_text(response.content)
        llm_queries = _sanitize_rewrite_queries(
            payload.get("queries"),
            max_queries=max_queries,
        )
        if not llm_queries:
            raise ValueError("LLM rewrite response missing queries")

        queries = _merge_rewrite_queries(
            original_query=original_query,
            lexical_queries=lexical_queries,
            llm_queries=llm_queries,
            max_queries=max_queries,
        )
        return {
            "node": "query_rewrite",
            "status": "completed",
            "policy_id": "llm_recall_rewrite_with_lexical_fallback_v1",
            "policy": (
                "LLM query_rewrite 是召回阶段的多 query 扩召节点；允许使用模型通用知识做"
                "同义词、别名、缩写/全称、跨语言和型号拆分，但必须保留原始意图和显式约束，"
                "不得生成未被用户查询支持的事实判断或单一路径解释。"
            ),
            "strategy": "llm_semantic_rewrite",
            "original_query": original_query,
            "queries": queries,
            "lexical_strategy": lexical_plan.get("strategy") or "",
            "lexical_queries": lexical_queries,
            "language_policy": query_context_payload["language_policy"],
            "provider": self.name,
            "model": response.model,
            "usage": response.usage,
            "reason": _truncate_text(payload.get("reason"), 240),
        }


class LLMSearchReranker:
    """Use the configured LLM as a generic relevance judge for recalled results."""

    def __init__(
        self,
        provider: Any,
        *,
        name: str,
        max_candidates: int = SEARCH_LLM_RERANK_MAX_CANDIDATES,
        timeout_seconds: float = SEARCH_LLM_RERANK_TIMEOUT_SECONDS,
        min_score: float = SEARCH_LLM_RERANK_MIN_SCORE,
    ):
        self._provider = provider
        self.name = name
        self.max_candidates = max(1, min(max_candidates, SEARCH_PROVIDER_LIMIT_MAX))
        self._timeout_seconds = max(0.1, timeout_seconds)
        self._min_score = max(0.0, min(min_score, 1.0))

    async def rerank(
        self,
        query: str,
        results: list[SearchResult],
        *,
        limit: int,
        query_context: dict[str, Any] | None = None,
    ) -> tuple[list[SearchResult], dict[str, Any]]:
        from agent.llm.base import LLMMessage

        candidates = results[: self.max_candidates]
        if not candidates:
            return [], {
                "status": "skipped",
                "reason": "no_candidates",
                "threshold": self._min_score,
                "candidate_count": 0,
                "judged_count": 0,
                "kept_count": 0,
            }

        candidate_payload = [
            {
                "index": index,
                "title": _truncate_text(result.title, 220),
                "snippet": _truncate_text(result.snippet, 700),
                "url": _truncate_text(result.url, 500),
                "source": result.source,
                "retrieval_query": _truncate_text(
                    _search_result_metadata_value(result, "retrieval_query"),
                    300,
                ),
                "retrieval_query_index": _search_result_metadata_value(
                    result,
                    "retrieval_query_index",
                ),
            }
            for index, result in enumerate(candidates, start=1)
        ]
        query_context = query_context or {}
        rewrite_queries = query_context.get("queries")
        if not isinstance(rewrite_queries, list):
            rewrite_queries = []
        query_context_payload = {
            "original_query": query,
            "rewrite_strategy": query_context.get("strategy") or "",
            "recall_queries": [
                _truncate_text(item, 300)
                for item in rewrite_queries
                if str(item or "").strip()
            ],
        }
        messages = [
            LLMMessage(
                role="system",
                content=(
                    "你是搜索结果相关性评审节点。只根据候选结果对原始用户查询的回答价值排序，"
                    "不要只看它是否匹配某条改写后的召回 query。先在内部拆出原始查询的显式约束："
                    "核心实体、专有名词、数字/版本/型号、限定词、时间、任务意图和文档形态；"
                    "再判断候选能否满足这些约束。需要惩罚词面巧合、同词异义、泛泛页面、"
                    "邻近类别、格式不匹配、垃圾结果，以及不能回答查询的页面。权威页面如果确实覆盖了"
                    "核心实体和部分关键约束，即使只回答部分问题，也可以有价值。只返回严格 JSON。"
                ),
            ),
            LLMMessage(
                role="user",
                content=(
                    "搜索查询上下文 JSON：\n"
                    f"{json.dumps(query_context_payload, ensure_ascii=False)}\n\n"
                    "候选结果 JSON：\n"
                    f"{json.dumps(candidate_payload, ensure_ascii=False)}\n\n"
                    "请按这个精确结构返回 JSON：\n"
                    '{"results":[{"index":1,"score":0.0,"reason":"short reason"}]}\n'
                    "分数范围是 0.0 到 1.0。尽量评审每个候选。"
                    "0.80 以上表示能直接回答原始查询，且命中核心实体和多数显式约束；"
                    "0.50-0.79 表示有用的部分答案，或关于核心实体的权威来源但覆盖约束不完整；"
                    "0.20-0.49 表示较弱、邻近但不充分的匹配；"
                    "0.20 以下表示同词异义、主题漂移或无关。"
                    "如果候选只匹配某条 rewrite query，却和原始查询冲突，或把原始查询收窄到"
                    "未被用户表达支持的方向，分数应低于 0.50。"
                    "如果候选只共享品牌、单个英文词、泛类别、下载/购物/资讯等外壳，但缺少原始查询的"
                    "任务意图或文档形态，通常应低于 0.40；如果明显是同词异义，通常应低于 0.20。"
                ),
            ),
        ]

        response = await asyncio.wait_for(
            self._provider.chat(messages, temperature=0),
            timeout=self._timeout_seconds,
        )
        payload = _json_object_from_text(response.content)
        raw_items = payload.get("results")
        if not isinstance(raw_items, list):
            raise ValueError("LLM rerank response missing results list")

        decisions: list[dict[str, Any]] = []
        seen_indexes: set[int] = set()
        for item in raw_items:
            if not isinstance(item, dict):
                continue
            try:
                index = int(item.get("index"))
                score = float(item.get("score"))
            except (TypeError, ValueError):
                continue
            if index < 1 or index > len(candidates) or index in seen_indexes:
                continue
            score = max(0.0, min(score, 1.0))
            result = candidates[index - 1]
            decisions.append(
                {
                    "index": index,
                    "score": score,
                    "reason": _truncate_text(str(item.get("reason") or ""), 220),
                    "title": result.title,
                    "url": result.url,
                }
            )
            seen_indexes.add(index)

        if not decisions:
            raise ValueError("LLM rerank response did not contain valid decisions")

        decisions.sort(key=lambda item: (-float(item["score"]), int(item["index"])))
        selected = [
            candidates[int(item["index"]) - 1]
            for item in decisions
            if float(item["score"]) >= self._min_score
        ][:limit]
        return selected, {
            "status": "completed",
            "model": response.model,
            "usage": response.usage,
            "threshold": self._min_score,
            "candidate_count": len(candidates),
            "judged_count": len(decisions),
            "kept_count": len(selected),
            "decisions": decisions[:10],
            "query_context": query_context_payload,
        }


class WebPageReader:
    """Fetch and extract readable text from public HTTP(S) pages."""

    def __init__(self, *, timeout: float = 15, transport: Any | None = None):
        self._timeout = timeout
        self._transport = transport

    async def open(self, url: str, *, max_chars: int = WEB_PAGE_DEFAULT_CHARS) -> WebPageContent:
        normalized_url, response = await self._fetch(url)
        max_chars = _bounded_int(
            max_chars,
            default=WEB_PAGE_DEFAULT_CHARS,
            minimum=500,
            maximum=WEB_PAGE_HARD_MAX_CHARS,
        )

        raw_content_type = response.headers.get("content-type", "")
        content_type = raw_content_type.split(";", 1)[0].strip().lower()
        page_metadata = {
            "content_length": response.headers.get("content-length", ""),
        }
        if _is_html_content_type(content_type):
            parser = _ReadableHTMLParser()
            parser.feed(response.text[:WEB_PAGE_PARSE_MAX_CHARS])
            parser.close()
            title = parser.title
            description = parser.description
            content = parser.content(max_chars=max_chars)
            page_metadata.update(
                _html_page_media_metadata(parser, page_url=str(response.url))
            )
            if parser.published_at:
                page_metadata["published_at"] = parser.published_at
        elif _is_text_content_type(content_type):
            title = ""
            description = ""
            content = _normalize_page_text(response.text, max_chars=max_chars)
        else:
            raise ValueError(f"Unsupported content type: {content_type or 'unknown'}")

        return WebPageContent(
            url=normalized_url,
            final_url=str(response.url),
            title=title,
            description=description,
            content=content,
            content_type=content_type,
            status_code=response.status_code,
            metadata=page_metadata,
        )

    async def open_media(self, url: str) -> dict[str, Any]:
        """Fetch only enough page structure to discover preview media."""
        normalized_url = _validate_public_http_url(url)
        document = bytearray()
        final_url = normalized_url
        encoding = "utf-8"
        async with httpx.AsyncClient(
            timeout=min(self._timeout, SEARCH_IMAGE_ENRICH_TIMEOUT_SECONDS),
            follow_redirects=False,
            transport=self._transport,
            headers={"User-Agent": WEB_USER_AGENT},
        ) as client:
            current_url = normalized_url
            for redirect_count in range(SEARCH_IMAGE_ENRICH_MAX_REDIRECTS + 1):
                async with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "").strip()
                        if not location:
                            response.raise_for_status()
                        if redirect_count >= SEARCH_IMAGE_ENRICH_MAX_REDIRECTS:
                            raise ValueError("Too many redirects while discovering page media")
                        current_url = _validate_public_http_url(
                            urljoin(str(response.url), location)
                        )
                        continue

                    response.raise_for_status()
                    raw_content_type = response.headers.get("content-type", "")
                    content_type = raw_content_type.split(";", 1)[0].strip().lower()
                    if not _is_html_content_type(content_type):
                        return {}
                    final_url = str(response.url)
                    encoding = response.encoding or "utf-8"
                    tail = b""
                    async for chunk in response.aiter_bytes():
                        remaining = WEB_PAGE_MEDIA_PARSE_MAX_BYTES - len(document)
                        if remaining <= 0:
                            break
                        chunk = chunk[:remaining]
                        document.extend(chunk)
                        probe = (tail + chunk).lower()
                        if b"</head" in probe:
                            break
                        tail = probe[-16:]
                    break

        parser = _ReadableHTMLParser(capture_content=False)
        try:
            html = bytes(document).decode(encoding, errors="replace")
        except LookupError:
            html = bytes(document).decode("utf-8", errors="replace")
        parser.feed(html)
        parser.close()
        return _html_page_media_metadata(parser, page_url=final_url)

    async def validate_image(self, url: str) -> str:
        """Return the final public URL only when the response is a real image."""
        return await asyncio.wait_for(
            self._validate_image(url),
            timeout=min(self._timeout, SEARCH_IMAGE_ENRICH_TIMEOUT_SECONDS),
        )

    async def _validate_image(self, url: str) -> str:
        normalized_url = _validate_public_http_url(url)
        async with httpx.AsyncClient(
            timeout=min(self._timeout, SEARCH_IMAGE_ENRICH_TIMEOUT_SECONDS),
            follow_redirects=False,
            transport=self._transport,
            headers={
                "User-Agent": WEB_USER_AGENT,
                "Accept": "image/avif,image/webp,image/*,*/*;q=0.5",
                "Range": f"bytes=0-{SEARCH_IMAGE_VALIDATE_MAX_BYTES - 1}",
            },
        ) as client:
            current_url = normalized_url
            for redirect_count in range(SEARCH_IMAGE_ENRICH_MAX_REDIRECTS + 1):
                prefix = bytearray()
                async with client.stream("GET", current_url) as response:
                    if response.is_redirect:
                        location = response.headers.get("location", "").strip()
                        if not location:
                            response.raise_for_status()
                        if redirect_count >= SEARCH_IMAGE_ENRICH_MAX_REDIRECTS:
                            raise ValueError("Too many redirects while validating image")
                        current_url = _validate_public_http_url(
                            urljoin(str(response.url), location)
                        )
                        continue

                    response.raise_for_status()
                    final_url = _validate_public_http_url(str(response.url))
                    raw_content_type = response.headers.get("content-type", "")
                    content_type = raw_content_type.split(";", 1)[0].strip().lower()
                    if not (
                        content_type.startswith("image/")
                        or content_type == "application/octet-stream"
                    ):
                        raise ValueError(
                            f"Unsupported image content type: {content_type or 'unknown'}"
                        )

                    async for chunk in response.aiter_bytes():
                        remaining = SEARCH_IMAGE_VALIDATE_MAX_BYTES - len(prefix)
                        if remaining <= 0:
                            break
                        prefix.extend(chunk[:remaining])
                        if len(prefix) >= SEARCH_IMAGE_VALIDATE_MAX_BYTES:
                            break

                    image_bytes = bytes(prefix)
                    if not image_bytes:
                        raise ValueError("Image response was empty")
                    if content_type == "application/octet-stream":
                        if not _sniff_common_image_type(image_bytes):
                            raise ValueError(
                                "application/octet-stream response was not a recognized image"
                            )
                    elif content_type == "image/svg+xml":
                        if not _looks_like_svg_image(image_bytes):
                            raise ValueError("SVG image response did not contain an SVG document")
                    elif not _sniff_common_image_type(image_bytes):
                        if _looks_like_html_or_xml(image_bytes):
                            raise ValueError("Image response contained HTML or XML")
                        raise ValueError(
                            "Image response did not contain a recognized raster image"
                        )
                    return final_url

            raise ValueError("Too many redirects while validating image")

    async def _fetch(self, url: str) -> tuple[str, httpx.Response]:
        normalized_url = _validate_public_http_url(url)
        async with httpx.AsyncClient(
            timeout=self._timeout,
            follow_redirects=True,
            transport=self._transport,
            headers={"User-Agent": WEB_USER_AGENT},
        ) as client:
            response = await client.get(normalized_url)
            response.raise_for_status()
        return normalized_url, response


class StaticSearchProvider:
    recall_query_limit = 1

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
    recall_query_limit = 1

    def __init__(
        self,
        *,
        name: str,
        base_url: str,
        api_key: str = "",
        query_param: str = "q",
        transport: Any | None = None,
    ):
        self.name = name
        self._base_url = base_url
        self._api_key = api_key
        self._query_param = query_param
        self._transport = transport

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        headers = {}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"

        async with httpx.AsyncClient(timeout=15, transport=self._transport) as client:
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
    recall_query_limit = 1

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
    recall_query_limit = 2

    def __init__(
        self,
        *,
        base_url: str = "https://duckduckgo.com/html/",
        transport: Any | None = None,
    ):
        self._base_url = base_url
        self._transport = transport

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            transport=self._transport,
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
    recall_query_limit = 2

    def __init__(
        self,
        *,
        base_url: str = "https://www.bing.com/search",
        transport: Any | None = None,
    ):
        self._base_url = base_url
        self._transport = transport

    async def search(self, query: str, *, limit: int = 5) -> list[SearchResult]:
        async with httpx.AsyncClient(
            timeout=15,
            follow_redirects=True,
            transport=self._transport,
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


class _ReadableHTMLParser(HTMLParser):
    _IMAGE_META_KEYS = (
        "og:image:secure_url",
        "og:image:url",
        "og:image",
        "twitter:image",
        "twitter:image:src",
        "image_src",
        "image",
        "thumbnailurl",
        "thumbnail",
    )
    _PUBLISHED_META_KEYS = {
        "article:published_time",
        "og:published_time",
        "datepublished",
        "date",
        "publishdate",
        "publish_date",
        "published_at",
    }
    _BLOCK_TAGS = {
        "address",
        "article",
        "blockquote",
        "br",
        "dd",
        "div",
        "dl",
        "dt",
        "figcaption",
        "figure",
        "h1",
        "h2",
        "h3",
        "h4",
        "h5",
        "h6",
        "li",
        "main",
        "ol",
        "p",
        "pre",
        "section",
        "table",
        "td",
        "th",
        "tr",
        "ul",
    }
    _SKIP_TAGS = {
        "canvas",
        "form",
        "iframe",
        "noscript",
        "option",
        "script",
        "select",
        "style",
        "svg",
        "template",
    }

    def __init__(self, *, capture_content: bool = True):
        super().__init__(convert_charrefs=True)
        self._capture_content = capture_content
        self._body_depth = 0
        self._capture_title = False
        self._skip_depth = 0
        self._title_parts: list[str] = []
        self._description = ""
        self._published_at = ""
        self._capture_json_ld = False
        self._json_ld_parts: list[str] = []
        self._json_ld_chars = 0
        self._base_href = ""
        self._image_candidates: dict[str, list[str]] = {}
        self._text_parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        tag = tag.lower()
        attr = {key.lower(): value or "" for key, value in attrs}
        if tag == "script" and (
            attr.get("type", "").split(";", 1)[0].strip().lower()
            == "application/ld+json"
        ):
            self._capture_json_ld = True
            self._json_ld_parts = []
            self._json_ld_chars = 0
            self._skip_depth += 1
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
            return

        if tag == "body":
            self._body_depth += 1
        elif tag == "title":
            self._capture_title = True
        elif tag == "meta":
            self._handle_meta(attr)
        elif tag == "time" and not self._published_at:
            self._published_at = attr.get("datetime", "").strip()
        elif tag == "base" and not self._base_href:
            self._base_href = attr.get("href", "").strip()
        elif tag == "link":
            self._handle_link(attr)

        if self._capture_content and self._body_depth > 0 and tag in self._BLOCK_TAGS:
            self._append_separator()

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        if tag == "script" and self._capture_json_ld:
            self._capture_json_ld = False
            self._skip_depth = max(0, self._skip_depth - 1)
            self._handle_json_ld("".join(self._json_ld_parts))
            self._json_ld_parts = []
            self._json_ld_chars = 0
            return
        if tag in self._SKIP_TAGS:
            self._skip_depth = max(0, self._skip_depth - 1)
            return
        if tag == "title":
            self._capture_title = False
        elif tag == "body":
            self._body_depth = max(0, self._body_depth - 1)

        if self._capture_content and self._body_depth > 0 and tag in self._BLOCK_TAGS:
            self._append_separator()

    def handle_data(self, data: str) -> None:
        if self._capture_json_ld:
            remaining = 64_000 - self._json_ld_chars
            if remaining > 0:
                part = data[:remaining]
                self._json_ld_parts.append(part)
                self._json_ld_chars += len(part)
            return
        if self._skip_depth > 0:
            return
        text = " ".join(data.split())
        if not text:
            return
        if self._capture_title:
            self._title_parts.append(text)
            return
        if self._capture_content and self._body_depth > 0:
            self._text_parts.append(text)

    @property
    def title(self) -> str:
        return " ".join(" ".join(self._title_parts).split())

    @property
    def description(self) -> str:
        return " ".join(self._description.split())

    @property
    def base_href(self) -> str:
        return self._base_href

    @property
    def published_at(self) -> str:
        return self._published_at

    @property
    def image_url(self) -> str:
        urls = self.image_urls
        return urls[0] if urls else ""

    @property
    def image_urls(self) -> list[str]:
        urls: list[str] = []
        for key in self._IMAGE_META_KEYS:
            urls.extend(
                value
                for value in self._image_candidates.get(key, [])
                if value
            )
        return urls

    def content(self, *, max_chars: int) -> str:
        return _normalize_page_text(self._joined_text(), max_chars=max_chars)

    def _handle_meta(self, attr: dict[str, str]) -> None:
        content = attr.get("content", "").strip()
        if not content:
            return
        keys = {
            value.strip().lower()
            for value in (
                attr.get("property", ""),
                attr.get("name", ""),
                attr.get("itemprop", ""),
            )
            if value.strip()
        }
        if not self._description and keys.intersection(
            {"description", "og:description", "twitter:description"}
        ):
            self._description = content
        if not self._published_at and keys.intersection(self._PUBLISHED_META_KEYS):
            self._published_at = content
        for key in self._IMAGE_META_KEYS:
            if key not in keys:
                continue
            candidates = self._image_candidates.setdefault(key, [])
            if content not in candidates:
                candidates.append(content)

    def _handle_link(self, attr: dict[str, str]) -> None:
        rel = {
            value.strip().lower()
            for value in attr.get("rel", "").split()
            if value.strip()
        }
        href = attr.get("href", "").strip()
        if href and "image_src" in rel:
            candidates = self._image_candidates.setdefault("image_src", [])
            if href not in candidates:
                candidates.append(href)

    def _handle_json_ld(self, value: str) -> None:
        if self._published_at or not value.strip():
            return
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return

        pending = [payload]
        visited = 0
        while pending and visited < 2_000:
            node = pending.pop()
            visited += 1
            if isinstance(node, dict):
                for key in ("datePublished", "datepublished"):
                    candidate = node.get(key)
                    if isinstance(candidate, str) and candidate.strip():
                        self._published_at = candidate.strip()
                        return
                pending.extend(node.values())
            elif isinstance(node, list):
                pending.extend(node)

    def _append_separator(self) -> None:
        if self._text_parts and self._text_parts[-1] != "\n":
            self._text_parts.append("\n")

    def _joined_text(self) -> str:
        parts: list[str] = []
        for part in self._text_parts:
            if part == "\n":
                if parts and parts[-1] != "\n":
                    parts.append("\n")
                continue
            if parts and parts[-1] not in {" ", "\n"}:
                parts.append(" ")
            parts.append(part)
        return "".join(parts)


class SearchService:
    WEB_SOURCE_ALIASES = {"web", "internet", "online"}
    WEB_PROVIDER_PRIORITY = {
        "local": 0,
        "http": 1,
        "web": 2,
        "minimax-mcp": 3,
        "bing-rss": 4,
    }

    def __init__(
        self,
        providers: list[SearchProvider] | None = None,
        *,
        page_reader: WebPageReader | None = None,
        query_rewriter: SearchQueryRewriter | None = None,
        reranker: SearchReranker | None = None,
        retry_attempts: int = 3,
        retry_delay: float = 0.5,
        min_provider_coverage: int = SEARCH_MIN_PROVIDER_COVERAGE,
        provider_limit_multiplier: int = SEARCH_PROVIDER_LIMIT_MULTIPLIER,
        recall_max_queries: int = SEARCH_RECALL_MAX_QUERIES,
        recall_timeout_seconds: float = SEARCH_RECALL_QUERY_TIMEOUT_SECONDS,
    ):
        self._providers = providers or []
        self._page_reader = page_reader or WebPageReader()
        self._query_rewriter = query_rewriter
        self._reranker = reranker
        self._retry_attempts = max(1, retry_attempts)
        self._retry_delay = max(0.0, retry_delay)
        self._min_provider_coverage = max(1, min_provider_coverage)
        self._provider_limit_multiplier = max(1, provider_limit_multiplier)
        self._recall_max_queries = max(1, recall_max_queries)
        self._recall_timeout_seconds = max(0.1, recall_timeout_seconds)
        self._last_provider_errors: list[str] = []
        self._last_query_variants: list[str] = []
        self._last_query_rewrite: dict[str, Any] = {}
        self._last_trace_nodes: list[dict[str, Any]] = []

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
            query_rewriter=_search_query_rewriter_from_runtime_config(),
            reranker=_search_reranker_from_runtime_config(),
            retry_attempts=_parse_int(
                runtime_config.get("search.retry.attempts", "3"),
                default=3,
            ),
            retry_delay=_parse_float(
                runtime_config.get("search.retry.delay_seconds", "0.5"),
                default=0.5,
            ),
            min_provider_coverage=_parse_int(
                runtime_config.get(
                    "search.min_provider_coverage",
                    str(SEARCH_MIN_PROVIDER_COVERAGE),
                ),
                default=SEARCH_MIN_PROVIDER_COVERAGE,
            ),
            provider_limit_multiplier=_parse_int(
                runtime_config.get(
                    "search.provider_limit_multiplier",
                    str(SEARCH_PROVIDER_LIMIT_MULTIPLIER),
                ),
                default=SEARCH_PROVIDER_LIMIT_MULTIPLIER,
            ),
            recall_max_queries=_parse_int(
                runtime_config.get(
                    "search.recall.max_queries",
                    str(SEARCH_RECALL_MAX_QUERIES),
                ),
                default=SEARCH_RECALL_MAX_QUERIES,
            ),
            recall_timeout_seconds=_parse_float(
                runtime_config.get(
                    "search.recall.timeout_seconds",
                    str(SEARCH_RECALL_QUERY_TIMEOUT_SECONDS),
                ),
                default=SEARCH_RECALL_QUERY_TIMEOUT_SECONDS,
            ),
        )

    @property
    def provider_names(self) -> list[str]:
        return [provider.name for provider in self._providers]

    @property
    def last_provider_errors(self) -> list[str]:
        return list(self._last_provider_errors)

    @property
    def last_query_variants(self) -> list[str]:
        return list(self._last_query_variants)

    @property
    def last_query_rewrite(self) -> dict[str, Any]:
        return dict(self._last_query_rewrite)

    @property
    def last_trace_nodes(self) -> list[dict[str, Any]]:
        return [dict(node) for node in self._last_trace_nodes]

    async def search(
        self,
        query: str,
        *,
        sources: list[str] | None = None,
        limit: int = 5,
        open_results: bool = False,
        open_limit: int = WEB_PAGE_OPEN_RESULT_LIMIT,
        page_chars: int = WEB_PAGE_DEFAULT_CHARS,
        include_images: bool = False,
        image_limit: int = SEARCH_IMAGE_ENRICH_DEFAULT_LIMIT,
    ) -> list[SearchResult]:
        selected, generic_web_requested = self._normalize_sources(sources)
        providers = [
            provider
            for provider in self._providers
            if not selected or provider.name in selected
        ]
        providers.sort(key=self._provider_sort_key)
        provider_limit = min(
            SEARCH_PROVIDER_LIMIT_MAX,
            max(limit, limit * self._provider_limit_multiplier),
        )
        query_rewrite = await self._build_query_rewrite(query)
        query_variants = list(query_rewrite.get("queries") or [])
        self._last_query_variants = query_variants
        self._last_query_rewrite = query_rewrite
        self._last_trace_nodes = [_query_rewrite_trace_node(query_rewrite)]
        stop_when_relevant = generic_web_requested or not selected
        min_provider_coverage = min(len(providers), self._min_provider_coverage)
        if len(providers) > 1:
            results, provider_errors, recall_attempts = await self._search_providers_concurrently(
                providers,
                query_variants,
                limit=limit,
                provider_limit=provider_limit,
                rank_query=query,
                stop_when_relevant=stop_when_relevant,
                min_provider_coverage=min_provider_coverage,
            )
        else:
            results, provider_errors, recall_attempts = await self._search_providers_sequentially(
                providers,
                query_variants,
                limit=limit,
                provider_limit=provider_limit,
                rank_query=query,
            )
        self._last_provider_errors = provider_errors
        self._last_trace_nodes.append(
            _recall_trace_node(
                providers=providers,
                queries=query_variants,
                attempts=recall_attempts,
                results=results,
                provider_errors=provider_errors,
                provider_limit=provider_limit,
                concurrent=len(providers) > 1,
            )
        )
        if (
            not results
            and provider_errors
            and {provider.name for provider in providers}.issubset(
                _provider_error_sources(provider_errors)
            )
        ):
            raise RuntimeError("; ".join(provider_errors))
        rank_started = perf_counter()
        raw_results = results
        ranked_results = _rank_results_by_query_relevance(query, raw_results)
        rerank_candidate_limit = self._rerank_candidate_limit(limit)
        ranking_output_results = ranked_results[:rerank_candidate_limit]
        if self._reranker is None:
            rerank_candidates = ranking_output_results
        else:
            rerank_candidates = _build_rerank_candidates(
                raw_results=raw_results,
                ranked_results=ranked_results,
                limit=rerank_candidate_limit,
            )
        self._last_trace_nodes.append(
            _ranking_trace_node(
                query=query,
                input_results=raw_results,
                ranked_results=ranked_results,
                output_results=ranking_output_results,
                limit=rerank_candidate_limit,
                duration_ms=int((perf_counter() - rank_started) * 1000),
            )
        )
        rerank_started = perf_counter()
        limited_results, rerank_node = await self._rerank_results(
            query,
            rerank_candidates,
            limit=limit,
            query_context=query_rewrite,
        )
        rerank_node["duration_ms"] = int((perf_counter() - rerank_started) * 1000)
        self._last_trace_nodes.append(rerank_node)
        if open_results:
            open_started = perf_counter()
            await self.attach_page_content(
                limited_results,
                open_limit=open_limit,
                max_chars=page_chars,
            )
            self._last_trace_nodes.append(
                _open_results_trace_node(
                    results=limited_results,
                    open_limit=open_limit,
                    page_chars=page_chars,
                    duration_ms=int((perf_counter() - open_started) * 1000),
                )
            )
        if open_results or include_images:
            image_started = perf_counter()
            image_stats = await self.attach_page_media(
                limited_results,
                image_limit=image_limit,
                discover_missing=include_images,
            )
            self._last_trace_nodes.append(
                _image_enrichment_trace_node(
                    stats=image_stats,
                    image_limit=image_limit,
                    duration_ms=int((perf_counter() - image_started) * 1000),
                )
            )
        else:
            self.discard_result_images(limited_results)
        return limited_results

    async def _build_query_rewrite(self, query: str) -> dict[str, Any]:
        lexical_plan = build_query_rewrite_plan(
            query,
            max_queries=self._recall_max_queries,
        )
        if self._query_rewriter is None:
            return lexical_plan
        try:
            return await self._query_rewriter.rewrite(
                query,
                max_queries=self._recall_max_queries,
                lexical_plan=lexical_plan,
            )
        except Exception as e:
            logger.warning(
                "Search LLM rewrite failed; falling back to lexical query variants",
                extra={"provider": self._query_rewriter.name, "error": str(e)},
            )
            fallback = dict(lexical_plan)
            fallback["status"] = "partial"
            fallback["provider"] = self._query_rewriter.name
            fallback["error"] = str(e)[:500]
            fallback["fallback"] = "lexical"
            return fallback

    def _rerank_candidate_limit(self, limit: int) -> int:
        if self._reranker is None:
            return limit
        return max(limit, min(getattr(self._reranker, "max_candidates", limit), SEARCH_PROVIDER_LIMIT_MAX))

    async def _rerank_results(
        self,
        query: str,
        results: list[SearchResult],
        *,
        limit: int,
        query_context: dict[str, Any] | None = None,
    ) -> tuple[list[SearchResult], dict[str, Any]]:
        if self._reranker is None:
            return results[:limit], _llm_rerank_trace_node(
                status="skipped",
                provider="",
                input_count=len(results),
                output_results=results[:limit],
                limit=limit,
                reason="disabled",
            )
        if not results:
            return [], _llm_rerank_trace_node(
                status="skipped",
                provider=self._reranker.name,
                input_count=0,
                output_results=[],
                limit=limit,
                reason="no_candidates",
            )
        try:
            reranked, metadata = await self._reranker.rerank(
                query,
                results,
                limit=limit,
                query_context=query_context,
            )
        except Exception as e:
            logger.warning(
                "Search LLM rerank failed; falling back to ranked results",
                extra={"provider": self._reranker.name, "error": str(e)},
            )
            fallback = results[:limit]
            return fallback, _llm_rerank_trace_node(
                status="partial",
                provider=self._reranker.name,
                input_count=len(results),
                output_results=fallback,
                limit=limit,
                error=str(e)[:500],
            )
        return reranked[:limit], _llm_rerank_trace_node(
            status=str(metadata.get("status") or "completed"),
            provider=self._reranker.name,
            input_count=len(results),
            output_results=reranked[:limit],
            limit=limit,
            metadata=metadata,
        )

    async def _search_providers_sequentially(
        self,
        providers: list[SearchProvider],
        queries: list[str],
        *,
        limit: int,
        provider_limit: int,
        rank_query: str,
    ) -> tuple[list[SearchResult], list[str], list[dict[str, Any]]]:
        provider_outputs: list[tuple[int, int, list[SearchResult]]] = []
        provider_errors: list[tuple[int, str]] = []
        recall_attempts: list[dict[str, Any]] = []
        for index, provider in enumerate(providers):
            provider_queries = self._queries_for_provider(provider, queries)
            for query_index, query in enumerate(provider_queries):
                provider_results, attempt, error = await self._search_provider_with_recall_timeout(
                    provider,
                    query,
                    limit=provider_limit,
                )
                attempt["query_index"] = query_index
                recall_attempts.append(attempt)
                if error is not None:
                    provider_errors.append((index, self._provider_error_text(provider, error)))
                    continue
                provider_outputs.append(
                    (
                        index,
                        query_index,
                        _tag_retrieval_query(
                            provider_results,
                            query=query,
                            query_index=query_index,
                        ),
                    )
                )
                if len(provider_queries) == 1 and len(_merge_provider_outputs(provider_outputs)) >= limit:
                    break
            if len(_rank_results_by_query_relevance(rank_query, _merge_provider_outputs(provider_outputs))) >= limit:
                break
        return (
            _merge_provider_outputs(provider_outputs),
            [error for _, error in sorted(provider_errors)],
            recall_attempts,
        )

    async def _search_providers_concurrently(
        self,
        providers: list[SearchProvider],
        queries: list[str],
        *,
        limit: int,
        provider_limit: int,
        rank_query: str,
        stop_when_relevant: bool,
        min_provider_coverage: int,
    ) -> tuple[list[SearchResult], list[str], list[dict[str, Any]]]:
        tasks = {
            asyncio.create_task(
                self._search_provider_with_recall_timeout(
                    provider,
                    query,
                    limit=provider_limit,
                )
            ): (index, query_index, provider, query)
            for index, provider in enumerate(providers)
            for query_index, query in enumerate(self._queries_for_provider(provider, queries))
        }
        pending = set(tasks)
        provider_outputs: list[tuple[int, int, list[SearchResult]]] = []
        provider_errors: list[tuple[int, str]] = []
        recall_attempts: list[dict[str, Any]] = []

        try:
            while pending:
                done, pending = await asyncio.wait(
                    pending,
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in done:
                    index, query_index, provider, query = tasks[task]
                    provider_results, attempt, error = task.result()
                    attempt["query_index"] = query_index
                    recall_attempts.append(attempt)
                    if error is not None:
                        provider_errors.append((index, self._provider_error_text(provider, error)))
                        continue
                    provider_outputs.append(
                        (
                            index,
                            query_index,
                            _tag_retrieval_query(
                                provider_results,
                                query=query,
                                query_index=query_index,
                            ),
                        )
                    )

                merged_results = _merge_provider_outputs(provider_outputs)
                settled_provider_count = len(provider_outputs) + len(provider_errors)
                all_provider_queries_single = all(
                    len(self._queries_for_provider(provider, queries)) == 1
                    for provider in providers
                )
                if (
                    all_provider_queries_single
                    and stop_when_relevant
                    and settled_provider_count >= min_provider_coverage
                    and len(merged_results) >= limit
                    and _results_have_query_relevance(rank_query, merged_results)
                ):
                    break
        finally:
            if pending:
                for task in pending:
                    task.cancel()
                await asyncio.gather(*pending, return_exceptions=True)

        return (
            _merge_provider_outputs(provider_outputs),
            [error for _, error in sorted(provider_errors)],
            recall_attempts,
        )

    def _queries_for_provider(
        self,
        provider: SearchProvider,
        queries: list[str],
    ) -> list[str]:
        query_limit = getattr(provider, "recall_query_limit", 1)
        try:
            query_limit = int(query_limit)
        except (TypeError, ValueError):
            query_limit = 1
        query_limit = max(1, min(query_limit, self._recall_max_queries))
        return (queries or [""])[:query_limit]

    def _provider_error_text(self, provider: SearchProvider, error: Exception) -> str:
        error_text = f"{provider.name}: {error}"
        logger.warning(
            "Search provider failed; trying next provider",
            extra={"provider": provider.name, "error": str(error)},
        )
        return error_text

    async def open_url(
        self,
        url: str,
        *,
        max_chars: int = WEB_PAGE_DEFAULT_CHARS,
    ) -> WebPageContent:
        return await self._page_reader.open(url, max_chars=max_chars)

    async def attach_page_content(
        self,
        results: list[SearchResult],
        *,
        open_limit: int = WEB_PAGE_OPEN_RESULT_LIMIT,
        max_chars: int = WEB_PAGE_DEFAULT_CHARS,
    ) -> list[SearchResult]:
        open_limit = _bounded_int(
            open_limit,
            default=WEB_PAGE_OPEN_RESULT_LIMIT,
            minimum=1,
            maximum=WEB_PAGE_OPEN_RESULT_LIMIT,
        )
        max_chars = _bounded_int(
            max_chars,
            default=WEB_PAGE_DEFAULT_CHARS,
            minimum=500,
            maximum=WEB_PAGE_HARD_MAX_CHARS,
        )
        candidates = [
            result
            for result in results
            if result.url and _is_public_http_url(result.url)
        ][:open_limit]
        if not candidates:
            return results

        pages = await asyncio.gather(
            *[
                self.open_url(result.url, max_chars=max_chars)
                for result in candidates
            ],
            return_exceptions=True,
        )
        for result, page in zip(candidates, pages):
            metadata = dict(result.metadata)
            if isinstance(page, Exception):
                metadata["page"] = {
                    "url": result.url,
                    "error": str(page)[:500],
                }
            else:
                metadata["page"] = page.model_dump(mode="json")
                published_at = str(page.metadata.get("published_at") or "").strip()
                if published_at and not metadata.get("published_at"):
                    metadata["published_at"] = published_at
                if page.title and (not result.title or result.title == result.url):
                    result.title = page.title
                if page.description and not result.snippet:
                    result.snippet = page.description[:SEARCH_SNIPPET_MAX_CHARS]
            result.metadata = metadata
            if not isinstance(page, Exception):
                _merge_search_result_media(
                    result,
                    _extract_media_metadata(page.metadata),
                )
        return results

    async def attach_page_media(
        self,
        results: list[SearchResult],
        *,
        image_limit: int = SEARCH_IMAGE_ENRICH_DEFAULT_LIMIT,
        discover_missing: bool = True,
    ) -> dict[str, int]:
        image_limit = _bounded_int(
            image_limit,
            default=SEARCH_IMAGE_ENRICH_DEFAULT_LIMIT,
            minimum=1,
            maximum=SEARCH_IMAGE_ENRICH_MAX_LIMIT,
        )
        captured_candidates = {
            id(result): _search_result_image_candidates(result)
            for result in results
        }
        for result in results:
            _clear_search_result_image_media(result)

        eligible = [
            result
            for result in results
            if (
                captured_candidates[id(result)]
                or (
                    discover_missing
                    and result.url
                    and _is_public_http_url(result.url)
                )
            )
        ]
        max_probe_count = min(
            SEARCH_IMAGE_ENRICH_MAX_PROBES,
            max(image_limit, image_limit * SEARCH_IMAGE_ENRICH_PROBE_MULTIPLIER),
        )
        candidates = eligible[:max_probe_count]
        if not candidates:
            return {
                "candidate_count": 0,
                "probed_count": 0,
                "enriched_count": 0,
                "validated_count": 0,
                "invalid_count": 0,
                "validation_attempt_count": 0,
                "error_count": 0,
                "image_count": 0,
            }

        probed_count = 0
        validated_count = 0
        invalid_count = 0
        validation_attempt_count = 0
        error_count = 0
        accepted_candidates: dict[int, str] = {}
        cursor = 0
        while cursor < len(candidates) and validated_count < image_limit:
            remaining_target = image_limit - validated_count
            batch_size = min(
                SEARCH_IMAGE_ENRICH_CONCURRENCY,
                remaining_target,
                len(candidates) - cursor,
            )
            batch = candidates[cursor : cursor + batch_size]
            cursor += batch_size
            probe_results = await asyncio.gather(
                *[
                    asyncio.wait_for(
                        self._probe_result_image(
                            result,
                            initial_candidates=captured_candidates[id(result)],
                            discover_missing=discover_missing,
                        ),
                        timeout=SEARCH_IMAGE_ENRICH_TIMEOUT_SECONDS,
                    )
                    for result in batch
                ],
                return_exceptions=True,
            )
            probed_count += len(batch)
            for result, probe in zip(batch, probe_results):
                if isinstance(probe, Exception):
                    error_count += 1
                    continue
                invalid_count += int(probe.get("invalid_count", 0))
                validation_attempt_count += int(
                    probe.get("validation_attempt_count", 0)
                )
                error_count += int(probe.get("error_count", 0))
                validated_url = str(probe.get("validated_url") or "")
                if not validated_url:
                    continue
                _set_validated_search_result_image(result, validated_url)
                accepted_candidates[id(result)] = str(
                    probe.get("accepted_candidate") or validated_url
                )
                validated_count += 1

        for result in results:
            rejected_urls = set(captured_candidates[id(result)])
            accepted_candidate = accepted_candidates.get(id(result), "")
            if accepted_candidate:
                rejected_urls.discard(accepted_candidate)
            _remove_rejected_media_urls(result, rejected_urls)

        return {
            "candidate_count": len(candidates),
            "probed_count": probed_count,
            "enriched_count": validated_count,
            "validated_count": validated_count,
            "invalid_count": invalid_count,
            "validation_attempt_count": validation_attempt_count,
            "error_count": error_count,
            "image_count": _search_result_image_count(results),
        }

    def discard_result_images(self, results: list[SearchResult]) -> None:
        """Remove unvalidated image media and every occurrence of its URLs."""
        for result in results:
            rejected_urls = set(_search_result_image_candidates(result))
            _clear_search_result_image_media(result)
            _remove_rejected_media_urls(result, rejected_urls)

    async def _probe_result_image(
        self,
        result: SearchResult,
        *,
        initial_candidates: list[str],
        discover_missing: bool,
    ) -> dict[str, Any]:
        attempted: set[str] = set()
        invalid_count = 0
        validation_attempt_count = 0
        error_count = 0

        async def validate(candidates: list[str]) -> tuple[str, str]:
            nonlocal invalid_count, validation_attempt_count
            for candidate in candidates:
                if (
                    candidate in attempted
                    or len(attempted) >= SEARCH_IMAGE_CANDIDATE_MAX_PER_RESULT
                ):
                    continue
                attempted.add(candidate)
                validation_attempt_count += 1
                try:
                    validated = await self._page_reader.validate_image(candidate)
                except Exception:
                    invalid_count += 1
                    continue
                validated = str(validated or "").strip()
                if validated and _is_public_http_url(validated):
                    return validated, candidate
                invalid_count += 1
            return "", ""

        validated_url, accepted_candidate = await validate(initial_candidates)
        if (
            not validated_url
            and discover_missing
            and result.url
            and _is_public_http_url(result.url)
            and len(attempted) < SEARCH_IMAGE_CANDIDATE_MAX_PER_RESULT
        ):
            try:
                media = await self._page_reader.open_media(result.url)
            except Exception:
                error_count += 1
            else:
                validated_url, accepted_candidate = await validate(
                    _image_candidates_from_mapping(media)
                )

        return {
            "validated_url": validated_url,
            "accepted_candidate": accepted_candidate,
            "invalid_count": invalid_count,
            "validation_attempt_count": validation_attempt_count,
            "error_count": error_count,
        }

    def _normalize_sources(self, sources: list[str] | None) -> tuple[set[str], bool]:
        selected: set[str] = set()
        available = set(self.provider_names)
        generic_web_requested = False
        for source in sources or []:
            value = str(source or "").strip().lower()
            if not value:
                continue
            if value in self.WEB_SOURCE_ALIASES:
                generic_web_requested = True
                selected.update(
                    name
                    for name in self.WEB_PROVIDER_PRIORITY
                    if name in available and name not in {"local", "http"}
                )
            else:
                selected.add(value)
        return selected, generic_web_requested

    def _provider_sort_key(self, provider: SearchProvider) -> tuple[int, str]:
        return (
            self.WEB_PROVIDER_PRIORITY.get(provider.name, 100),
            provider.name,
        )

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

    async def _search_provider_with_recall_timeout(
        self,
        provider: SearchProvider,
        query: str,
        *,
        limit: int,
    ) -> tuple[list[SearchResult], dict[str, Any], Exception | None]:
        started = perf_counter()
        try:
            results = await asyncio.wait_for(
                self._search_provider_with_retries(provider, query, limit=limit),
                timeout=self._recall_timeout_seconds,
            )
            return (
                results,
                _recall_attempt(
                    provider=provider.name,
                    query=query,
                    limit=limit,
                    status="completed",
                    result_count=len(results),
                    duration_ms=int((perf_counter() - started) * 1000),
                ),
                None,
            )
        except asyncio.TimeoutError:
            logger.info(
                "Search provider recall timed out; treating as empty results",
                extra={
                    "provider": provider.name,
                    "query": query,
                    "timeout_seconds": self._recall_timeout_seconds,
                },
            )
            return (
                [],
                _recall_attempt(
                    provider=provider.name,
                    query=query,
                    limit=limit,
                    status="timed_out",
                    result_count=0,
                    duration_ms=int((perf_counter() - started) * 1000),
                    timeout_seconds=self._recall_timeout_seconds,
                ),
                None,
            )
        except Exception as e:
            return (
                [],
                _recall_attempt(
                    provider=provider.name,
                    query=query,
                    limit=limit,
                    status="error",
                    result_count=0,
                    duration_ms=int((perf_counter() - started) * 1000),
                    error=str(e)[:500],
                ),
                e,
            )


def _query_rewrite_trace_node(query_rewrite: dict[str, Any]) -> dict[str, Any]:
    queries = query_rewrite.get("queries") if isinstance(query_rewrite.get("queries"), list) else []
    node = {
        "node": "query_rewrite",
        "status": query_rewrite.get("status") or "completed",
        "policy_id": query_rewrite.get("policy_id"),
        "policy": query_rewrite.get("policy"),
        "strategy": query_rewrite.get("strategy"),
        "original_query": query_rewrite.get("original_query"),
        "queries": queries,
        "query_count": len(queries),
    }
    for key in (
        "provider",
        "model",
        "usage",
        "reason",
        "lexical_strategy",
        "lexical_queries",
        "language_policy",
        "fallback",
        "error",
    ):
        if key in query_rewrite:
            node[key] = query_rewrite[key]
    return node


def _recall_attempt(
    *,
    provider: str,
    query: str,
    limit: int,
    status: str,
    result_count: int,
    duration_ms: int,
    timeout_seconds: float | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    attempt: dict[str, Any] = {
        "provider": provider,
        "query": query,
        "limit": limit,
        "status": status,
        "result_count": result_count,
        "duration_ms": duration_ms,
    }
    if timeout_seconds is not None:
        attempt["timeout_seconds"] = timeout_seconds
    if error:
        attempt["error"] = error
    return attempt


def _recall_trace_node(
    *,
    providers: list[SearchProvider],
    queries: list[str],
    attempts: list[dict[str, Any]],
    results: list[SearchResult],
    provider_errors: list[str],
    provider_limit: int,
    concurrent: bool,
) -> dict[str, Any]:
    timed_out_count = sum(1 for attempt in attempts if attempt.get("status") == "timed_out")
    error_count = sum(1 for attempt in attempts if attempt.get("status") == "error")
    status = "partial" if timed_out_count or error_count or provider_errors else "completed"
    return {
        "node": "recall",
        "status": status,
        "mode": "concurrent" if concurrent else "sequential",
        "providers": [provider.name for provider in providers],
        "provider_count": len(providers),
        "queries": queries,
        "query_count": len(queries),
        "provider_limit": provider_limit,
        "attempt_count": len(attempts),
        "timed_out_count": timed_out_count,
        "error_count": error_count,
        "result_count": len(results),
        "provider_errors": provider_errors,
        "attempts": attempts[:20],
    }


def _ranking_trace_node(
    *,
    query: str,
    input_results: list[SearchResult],
    ranked_results: list[SearchResult],
    output_results: list[SearchResult],
    limit: int,
    duration_ms: int,
) -> dict[str, Any]:
    return {
        "node": "ranking",
        "status": "completed",
        "query": query,
        "limit": limit,
        "input_count": len(input_results),
        "ranked_count": len(ranked_results),
        "output_count": len(output_results),
        "duration_ms": duration_ms,
        "top_results": [
            _search_result_trace_preview(result, index=index)
            for index, result in enumerate(output_results[:5], start=1)
        ],
    }


def _llm_rerank_trace_node(
    *,
    status: str,
    provider: str,
    input_count: int,
    output_results: list[SearchResult],
    limit: int,
    metadata: dict[str, Any] | None = None,
    reason: str | None = None,
    error: str | None = None,
) -> dict[str, Any]:
    metadata = metadata or {}
    node: dict[str, Any] = {
        "node": "llm_rerank",
        "status": status,
        "provider": provider,
        "limit": limit,
        "input_count": input_count,
        "output_count": len(output_results),
        "top_results": [
            _search_result_trace_preview(result, index=index)
            for index, result in enumerate(output_results[:5], start=1)
        ],
    }
    for key in (
        "model",
        "usage",
        "threshold",
        "candidate_count",
        "judged_count",
        "kept_count",
        "decisions",
        "query_context",
    ):
        if key in metadata:
            node[key] = metadata[key]
    if reason:
        node["reason"] = reason
    if error:
        node["error"] = error
    metadata_reason = metadata.get("reason")
    if metadata_reason and "reason" not in node:
        node["reason"] = metadata_reason
    return node


def _open_results_trace_node(
    *,
    results: list[SearchResult],
    open_limit: int,
    page_chars: int,
    duration_ms: int,
) -> dict[str, Any]:
    opened = 0
    errors = 0
    for result in results:
        page = result.metadata.get("page") if isinstance(result.metadata, dict) else None
        if not isinstance(page, dict):
            continue
        if page.get("error"):
            errors += 1
        else:
            opened += 1
    return {
        "node": "open_results",
        "status": "partial" if errors else "completed",
        "open_limit": open_limit,
        "page_chars": page_chars,
        "candidate_count": min(len(results), open_limit),
        "opened_count": opened,
        "error_count": errors,
        "duration_ms": duration_ms,
    }


def _image_enrichment_trace_node(
    *,
    stats: dict[str, int],
    image_limit: int,
    duration_ms: int,
) -> dict[str, Any]:
    error_count = int(stats.get("error_count", 0))
    invalid_count = int(stats.get("invalid_count", 0))
    return {
        "node": "image_enrichment",
        "status": "partial" if error_count or invalid_count else "completed",
        "image_limit": _bounded_int(
            image_limit,
            default=SEARCH_IMAGE_ENRICH_DEFAULT_LIMIT,
            minimum=1,
            maximum=SEARCH_IMAGE_ENRICH_MAX_LIMIT,
        ),
        "candidate_count": int(stats.get("candidate_count", 0)),
        "probed_count": int(
            stats.get("probed_count", stats.get("candidate_count", 0))
        ),
        "enriched_count": int(stats.get("enriched_count", 0)),
        "validated_count": int(
            stats.get("validated_count", stats.get("enriched_count", 0))
        ),
        "invalid_count": invalid_count,
        "validation_attempt_count": int(stats.get("validation_attempt_count", 0)),
        "image_count": int(stats.get("image_count", 0)),
        "error_count": error_count,
        "duration_ms": duration_ms,
    }


def _search_result_trace_preview(
    result: SearchResult,
    *,
    index: int,
) -> dict[str, Any]:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    return {
        "rank": index,
        "title": result.title,
        "url": result.url,
        "source": result.source,
        "retrieval_query": metadata.get("retrieval_query"),
        "retrieval_query_index": metadata.get("retrieval_query_index"),
    }


def _search_result_metadata_value(result: SearchResult, key: str) -> Any:
    metadata = result.metadata if isinstance(result.metadata, dict) else {}
    value = metadata.get(key)
    return "" if value is None else value


def _search_result_image_count(results: list[SearchResult]) -> int:
    return sum(
        1
        for result in results
        if result.thumbnail_url or result.image_url
    )


def _merge_provider_outputs(
    provider_outputs: list[tuple[int, int, list[SearchResult]]],
) -> list[SearchResult]:
    results: list[SearchResult] = []
    seen: set[str] = set()
    ordered_outputs = sorted(provider_outputs, key=lambda item: (item[1], item[0]))
    max_result_count = max(
        (len(provider_results) for _, _, provider_results in ordered_outputs),
        default=0,
    )
    for result_index in range(max_result_count):
        for _, _, provider_results in ordered_outputs:
            if result_index >= len(provider_results):
                continue
            result = provider_results[result_index]
            key = result.url or f"{result.source}:{result.title}"
            if key in seen:
                continue
            seen.add(key)
            results.append(result)
    return results


def _tag_retrieval_query(
    results: list[SearchResult],
    *,
    query: str,
    query_index: int,
) -> list[SearchResult]:
    tagged: list[SearchResult] = []
    for result in results:
        metadata = dict(result.metadata)
        metadata["retrieval_query"] = query
        metadata["retrieval_query_index"] = query_index
        result.metadata = metadata
        tagged.append(result)
    return tagged


def _provider_error_sources(provider_errors: list[str]) -> set[str]:
    return {
        error.split(":", 1)[0].strip()
        for error in provider_errors
        if error.split(":", 1)[0].strip()
    }


def _rank_results_by_query_relevance(
    query: str,
    results: list[SearchResult],
) -> list[SearchResult]:
    if len(results) < 2:
        ranked = rank_search_results(
            query,
            results,
            min_score=SEARCH_RANK_MIN_SCORE,
        )
        return [item.result for item in ranked]
    ranked = rank_search_results(
        query,
        results,
        min_score=SEARCH_RANK_MIN_SCORE,
    )
    ranked = diversify_ranked_results(ranked)
    return [item.result for item in ranked]


def _build_rerank_candidates(
    *,
    raw_results: list[SearchResult],
    ranked_results: list[SearchResult],
    limit: int,
) -> list[SearchResult]:
    candidates: list[SearchResult] = []
    seen: set[str] = set()

    for result in [*ranked_results, *raw_results]:
        key = _search_result_identity(result)
        if key in seen:
            continue
        seen.add(key)
        candidates.append(result)
        if len(candidates) >= limit:
            break
    return candidates


def _search_result_identity(result: SearchResult) -> str:
    if result.url:
        return result.url.strip().lower()
    return f"{result.source}:{result.title}".strip().lower()


def _results_have_query_relevance(
    query: str,
    results: list[SearchResult],
) -> bool:
    return any(_search_result_relevance_score(query, result) > 0 for result in results)


def _search_result_relevance_score(query: str, result: SearchResult) -> float:
    return search_result_relevance_score(query, result)


def _search_query_terms(query: str) -> list[str]:
    return search_query_terms(query)


def _search_query_rewriter_from_runtime_config() -> SearchQueryRewriter | None:
    enabled = runtime_config.get(
        "search.rewrite.enabled",
        str(SEARCH_LLM_REWRITE_ENABLED).lower(),
    ).lower()
    if enabled in {"0", "false", "no", "off"}:
        return None

    provider_name = runtime_config.get("search.rewrite.provider") or runtime_config.default_provider
    try:
        from agent.llm.factory import create_provider

        provider = create_provider(provider_name)
    except Exception as e:
        logger.warning(
            "Search LLM rewrite disabled because provider creation failed",
            extra={"provider": provider_name, "error": str(e)},
        )
        return None

    max_queries = _bounded_int(
        runtime_config.get(
            "search.rewrite.max_queries",
            str(SEARCH_LLM_REWRITE_MAX_QUERIES),
        ),
        default=SEARCH_LLM_REWRITE_MAX_QUERIES,
        minimum=1,
        maximum=SEARCH_PROVIDER_LIMIT_MAX,
    )
    timeout_seconds = _parse_float(
        runtime_config.get(
            "search.rewrite.timeout_seconds",
            str(SEARCH_LLM_REWRITE_TIMEOUT_SECONDS),
        ),
        default=SEARCH_LLM_REWRITE_TIMEOUT_SECONDS,
    )
    return LLMSearchQueryRewriter(
        provider,
        name=f"llm:{provider_name}",
        max_queries=max_queries,
        timeout_seconds=timeout_seconds,
    )


def _search_reranker_from_runtime_config() -> SearchReranker | None:
    enabled = runtime_config.get(
        "search.rerank.enabled",
        str(SEARCH_LLM_RERANK_ENABLED).lower(),
    ).lower()
    if enabled in {"0", "false", "no", "off"}:
        return None

    provider_name = runtime_config.get("search.rerank.provider") or runtime_config.default_provider
    try:
        from agent.llm.factory import create_provider

        provider = create_provider(provider_name)
    except Exception as e:
        logger.warning(
            "Search LLM rerank disabled because provider creation failed",
            extra={"provider": provider_name, "error": str(e)},
        )
        return None

    max_candidates = _bounded_int(
        runtime_config.get(
            "search.rerank.max_candidates",
            str(SEARCH_LLM_RERANK_MAX_CANDIDATES),
        ),
        default=SEARCH_LLM_RERANK_MAX_CANDIDATES,
        minimum=1,
        maximum=SEARCH_PROVIDER_LIMIT_MAX,
    )
    timeout_seconds = _parse_float(
        runtime_config.get(
            "search.rerank.timeout_seconds",
            str(SEARCH_LLM_RERANK_TIMEOUT_SECONDS),
        ),
        default=SEARCH_LLM_RERANK_TIMEOUT_SECONDS,
    )
    min_score = _parse_float(
        runtime_config.get(
            "search.rerank.min_score",
            str(SEARCH_LLM_RERANK_MIN_SCORE),
        ),
        default=SEARCH_LLM_RERANK_MIN_SCORE,
    )
    return LLMSearchReranker(
        provider,
        name=f"llm:{provider_name}",
        max_candidates=max_candidates,
        timeout_seconds=timeout_seconds,
        min_score=min_score,
    )


def _sanitize_rewrite_queries(
    raw_queries: Any,
    *,
    max_queries: int,
) -> list[str]:
    if isinstance(raw_queries, str):
        raw_items: list[Any] = [raw_queries]
    elif isinstance(raw_queries, list):
        raw_items = raw_queries
    else:
        return []
    queries: list[str] = []
    seen: set[str] = set()
    for item in raw_items:
        query = _truncate_text(item, SEARCH_LLM_REWRITE_MAX_QUERY_CHARS)
        if not query:
            continue
        key = query.lower()
        if key in seen:
            continue
        seen.add(key)
        queries.append(query)
        if len(queries) >= max_queries:
            break
    return queries


def _merge_rewrite_queries(
    *,
    original_query: str,
    lexical_queries: list[str],
    llm_queries: list[str],
    max_queries: int,
) -> list[str]:
    seed_queries = lexical_queries[:1] or [original_query]
    candidates = _language_balanced_rewrite_candidates(
        original_query=original_query,
        candidates=[*llm_queries, *lexical_queries[1:], original_query],
    )
    return _sanitize_rewrite_queries(
        [*seed_queries, *candidates, *lexical_queries, original_query],
        max_queries=max_queries,
    )


def _language_balanced_rewrite_candidates(
    *,
    original_query: str,
    candidates: list[str],
) -> list[str]:
    original_bucket = _query_language_bucket(original_query)
    priority_buckets = {
        "latin": ("zh", "mixed"),
        "zh": ("latin", "mixed"),
        "mixed": ("zh", "latin"),
    }.get(original_bucket, ("zh", "latin", "mixed"))
    return [
        *[
            candidate
            for bucket in priority_buckets
            for candidate in candidates
            if _query_language_bucket(candidate) == bucket
        ],
        *[
            candidate
            for candidate in candidates
            if _query_language_bucket(candidate) not in priority_buckets
        ],
    ]


def _query_language_bucket(text: str) -> str:
    has_cjk = any("\u4e00" <= char <= "\u9fff" for char in str(text or ""))
    has_latin = bool(re.search(r"[A-Za-z]", str(text or "")))
    if has_cjk and has_latin:
        return "mixed"
    if has_cjk:
        return "zh"
    if has_latin:
        return "latin"
    return "other"


def _json_object_from_text(text: str) -> dict[str, Any]:
    raw = str(text or "").strip()
    if raw.startswith("```"):
        raw = re.sub(r"^```(?:json)?\s*", "", raw, flags=re.IGNORECASE)
        raw = re.sub(r"\s*```$", "", raw).strip()
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        start = raw.find("{")
        end = raw.rfind("}")
        if start < 0 or end <= start:
            raise
        payload = json.loads(raw[start : end + 1])
    if not isinstance(payload, dict):
        raise ValueError("Expected a JSON object")
    return payload


def _truncate_text(text: Any, max_chars: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= max_chars:
        return value
    return value[: max(0, max_chars - 3)].rstrip() + "..."


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


def _bounded_int(
    raw: Any,
    *,
    default: int,
    minimum: int,
    maximum: int,
) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = default
    return max(minimum, min(value, maximum))


def _validate_public_http_url(raw_url: str) -> str:
    url = str(raw_url or "").strip()
    parsed = urlparse(url)
    if parsed.scheme.lower() not in {"http", "https"}:
        raise ValueError("Only http and https URLs can be opened")
    if not parsed.netloc or not parsed.hostname:
        raise ValueError("URL must include a host")

    hostname = parsed.hostname.strip().lower()
    if hostname in {"localhost", "0.0.0.0"} or hostname.endswith(".local"):
        raise ValueError("Local URLs cannot be opened by the web reader")

    try:
        ip = ipaddress.ip_address(hostname.strip("[]"))
    except ValueError:
        if "." not in hostname:
            raise ValueError("Host must be a public domain or IP address")
        return url

    if (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    ):
        raise ValueError("Private or local IP addresses cannot be opened")
    return url


def _is_public_http_url(url: str) -> bool:
    try:
        _validate_public_http_url(url)
    except ValueError:
        return False
    return True


def _is_html_content_type(content_type: str) -> bool:
    return content_type in {"", "text/html", "application/xhtml+xml"}


def _is_text_content_type(content_type: str) -> bool:
    return (
        content_type.startswith("text/")
        or content_type in {
            "application/json",
            "application/ld+json",
            "application/xml",
            "application/rss+xml",
            "application/atom+xml",
        }
    )


def _sniff_common_image_type(data: bytes) -> str:
    prefix = bytes(data[:64])
    if prefix.startswith(b"\xff\xd8\xff"):
        return "jpeg"
    if prefix.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if prefix.startswith((b"GIF87a", b"GIF89a")):
        return "gif"
    if len(prefix) >= 12 and prefix.startswith(b"RIFF") and prefix[8:12] == b"WEBP":
        return "webp"
    if prefix.startswith(b"BM"):
        return "bmp"
    if prefix.startswith((b"II*\x00", b"MM\x00*")):
        return "tiff"
    if prefix.startswith((b"\x00\x00\x01\x00", b"\x00\x00\x02\x00")):
        return "ico"
    if len(prefix) >= 12 and prefix[4:8] == b"ftyp":
        brand = prefix[8:12]
        if brand in {
            b"avif",
            b"avis",
            b"heic",
            b"heix",
            b"hevc",
            b"hevx",
            b"mif1",
            b"msf1",
        }:
            return "avif" if brand in {b"avif", b"avis"} else "heif"
    return ""


def _looks_like_html_or_xml(data: bytes) -> bool:
    prefix = bytes(data[:4096]).lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    return prefix.startswith(
        (
            b"<!doctype html",
            b"<html",
            b"<?xml",
            b"<error",
            b"<errors",
        )
    )


def _looks_like_svg_image(data: bytes) -> bool:
    prefix = bytes(data[:16_384]).lstrip(b"\xef\xbb\xbf \t\r\n").lower()
    if prefix.startswith(b"<svg"):
        return True
    if prefix.startswith(b"<?xml"):
        return b"<svg" in prefix
    return False


def _normalize_page_text(text: str, *, max_chars: int) -> str:
    lines: list[str] = []
    for raw_line in str(text or "").splitlines():
        line = " ".join(raw_line.split())
        if not line:
            continue
        if lines and lines[-1] == line:
            continue
        lines.append(line)
    normalized = "\n".join(lines)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[:max_chars].rstrip()


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
            "embed_url",
            "embedUrl",
            "contentUrl",
            "player",
            "player_url",
        ),
    )

    generic_media_url = _first_media_field(item, ("media_url", "mediaUrl"))
    media_type_hint = _normalize_media_type(item.get("media_type") or item.get("mediaType"))

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
            ("video_url", "videoUrl", "video", "videos", "video_urls", "embed_url"),
        )
        generic_media_url = generic_media_url or _first_media_field(
            nested_metadata,
            ("media_url", "mediaUrl"),
        )
        media_type_hint = media_type_hint or _normalize_media_type(
            nested_metadata.get("media_type") or nested_metadata.get("mediaType")
        )

    pagemap = item.get("pagemap")
    if isinstance(pagemap, dict):
        thumbnail_url = thumbnail_url or _first_media_url(pagemap.get("cse_thumbnail"))
        image_url = image_url or _first_media_url(pagemap.get("cse_image"))
        video_url = video_url or _first_media_url(pagemap.get("videoobject"))

    rich_snippet = item.get("rich_snippet")
    if isinstance(rich_snippet, dict):
        image_url = image_url or _first_media_url(rich_snippet.get("top"))

    if generic_media_url:
        generic_media_type = media_type_hint or _media_type_from_url(generic_media_url)
        if generic_media_type == "video":
            video_url = video_url or generic_media_url
        elif generic_media_type == "image":
            image_url = image_url or generic_media_url

    media_url = video_url or image_url or thumbnail_url or generic_media_url
    media_type = ""
    if video_url:
        media_type = "video"
    elif image_url or thumbnail_url:
        media_type = "image"
    elif media_url:
        media_type = media_type_hint or _media_type_from_url(media_url)

    return {
        "thumbnail_url": thumbnail_url,
        "image_url": image_url or thumbnail_url,
        "video_url": video_url,
        "media_url": media_url,
        "media_type": media_type,
    }


_IMAGE_METADATA_KEYS = {
    "_image_candidates",
    "cover",
    "cse_image",
    "cse_thumbnail",
    "image",
    "image_src",
    "image_url",
    "image_urls",
    "imageurl",
    "imageurls",
    "images",
    "og:image",
    "og_image",
    "poster",
    "thumb",
    "thumbnail",
    "thumbnail_url",
    "thumbnailurl",
}


def _search_result_image_candidates(result: SearchResult) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        for candidate in _all_media_urls(value):
            if candidate in seen or not _is_public_http_url(candidate):
                continue
            seen.add(candidate)
            candidates.append(candidate)

    add(result.image_url)
    add(result.thumbnail_url)
    if result.media_type == "image":
        add(result.media_url)
    if isinstance(result.metadata, dict):
        for candidate in _image_candidates_from_mapping(result.metadata):
            add(candidate)
    for candidate in _text_image_candidates(
        result.title,
        result.snippet,
        result.metadata,
    ):
        add(candidate)
    return candidates


def _text_image_candidates(*values: Any) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()
    remaining_chars = SEARCH_IMAGE_TEXT_SCAN_MAX_CHARS

    def add(candidate: Any) -> None:
        value = str(candidate or "").strip().strip("<>")
        if (
            not value
            or value in seen
            or len(candidates) >= SEARCH_IMAGE_TEXT_CANDIDATE_MAX
            or not _is_public_http_url(value)
        ):
            return
        seen.add(value)
        candidates.append(value)

    def scan_text(text: str) -> None:
        nonlocal remaining_chars
        if (
            remaining_chars <= 0
            or len(candidates) >= SEARCH_IMAGE_TEXT_CANDIDATE_MAX
        ):
            return
        fragment = text[:remaining_chars]
        remaining_chars -= len(fragment)
        for match in MARKDOWN_IMAGE_URL_RE.finditer(fragment):
            add(match.group(1) or match.group(2))
        for match in HTML_IMAGE_SRC_RE.finditer(fragment):
            add(match.group(1) or match.group(2) or match.group(3))
        for url in extract_public_http_urls(fragment):
            if _media_type_from_url(url) == "image":
                add(url)

    def walk(value: Any, *, depth: int = 0) -> None:
        if (
            remaining_chars <= 0
            or len(candidates) >= SEARCH_IMAGE_TEXT_CANDIDATE_MAX
            or depth > 12
        ):
            return
        if isinstance(value, str):
            scan_text(value)
            return
        if isinstance(value, list):
            for nested in value[:100]:
                walk(nested, depth=depth + 1)
            return
        if isinstance(value, dict):
            for nested in list(value.values())[:100]:
                walk(nested, depth=depth + 1)

    for value in values:
        walk(value)
    return candidates


def _image_candidates_from_mapping(item: Any) -> list[str]:
    candidates: list[str] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        for candidate in _all_media_urls(value):
            if candidate in seen or not _is_public_http_url(candidate):
                continue
            seen.add(candidate)
            candidates.append(candidate)

    def walk(value: Any) -> None:
        if isinstance(value, list):
            for nested in value:
                walk(nested)
            return
        if not isinstance(value, dict):
            return
        media_type = _normalize_media_type(
            value.get("media_type") or value.get("mediaType")
        )
        for key, nested in value.items():
            normalized_key = str(key).strip().lower()
            if normalized_key in _IMAGE_METADATA_KEYS:
                add(nested)
            elif normalized_key == "rich_snippet" and isinstance(nested, dict):
                add(nested.get("top"))
            elif normalized_key in {"media_url", "mediaurl"}:
                media_url = _first_media_url(nested)
                if media_type == "image" or _media_type_from_url(media_url) == "image":
                    add(nested)
            if isinstance(nested, (dict, list)):
                walk(nested)

    walk(item)
    return candidates


def _all_media_urls(value: Any) -> list[str]:
    if isinstance(value, str):
        candidate = value.strip()
        return [candidate] if candidate else []
    if isinstance(value, list):
        urls: list[str] = []
        for nested in value:
            urls.extend(_all_media_urls(nested))
        return urls
    if isinstance(value, dict):
        urls: list[str] = []
        preferred_keys = (
            "url",
            "src",
            "link",
            "contentUrl",
            "content_url",
            "image_url",
            "imageUrl",
            "thumbnail_url",
            "thumbnailUrl",
            "poster",
        )
        for key in preferred_keys:
            urls.extend(_all_media_urls(value.get(key)))
        return urls
    return []


def _clear_search_result_image_media(result: SearchResult) -> None:
    image_urls = set(_search_result_image_candidates(result))
    result.thumbnail_url = ""
    result.image_url = ""
    if result.media_type == "image" or result.media_url in image_urls:
        result.media_url = ""
        result.media_type = ""
    result.metadata = _strip_image_metadata(result.metadata)


def _remove_rejected_media_urls(
    result: SearchResult,
    rejected_urls: set[str],
) -> None:
    rejected = {url for url in rejected_urls if url}
    if not rejected:
        return

    def scrub(value: Any) -> Any:
        if isinstance(value, str):
            for rejected_url in rejected:
                escaped_url = re.escape(rejected_url)
                value = re.sub(
                    (
                        rf"!\[[^\]\r\n]{{0,500}}\]\(\s*"
                        rf"(?:<{escaped_url}>|{escaped_url})"
                        rf"(?:\s+[^)\r\n]*)?\)"
                    ),
                    "",
                    value,
                    flags=re.IGNORECASE,
                )
                value = re.sub(
                    rf"<img\b(?=[^>]{{0,4000}}{escaped_url})[^>]{{0,4000}}>",
                    "",
                    value,
                    flags=re.IGNORECASE,
                )
                value = value.replace(rejected_url, "")
            return value
        if isinstance(value, list):
            return [scrub(item) for item in value]
        if isinstance(value, dict):
            return {key: scrub(nested) for key, nested in value.items()}
        return value

    result.title = scrub(result.title)
    result.snippet = scrub(result.snippet)
    result.url = scrub(result.url)
    result.source = scrub(result.source)
    result.metadata = scrub(result.metadata)


def _strip_image_metadata(value: Any) -> Any:
    if isinstance(value, list):
        return [_strip_image_metadata(item) for item in value]
    if not isinstance(value, dict):
        return value

    media_type = _normalize_media_type(
        value.get("media_type") or value.get("mediaType")
    )
    stripped: dict[str, Any] = {}
    for key, nested in value.items():
        normalized_key = str(key).strip().lower()
        if normalized_key in _IMAGE_METADATA_KEYS:
            continue
        if normalized_key == "rich_snippet" and isinstance(nested, dict):
            nested = {
                nested_key: nested_value
                for nested_key, nested_value in nested.items()
                if str(nested_key).strip().lower() != "top"
            }
        if normalized_key in {"media_url", "mediaurl"}:
            media_url = _first_media_url(nested)
            if media_type == "image" or _media_type_from_url(media_url) == "image":
                continue
        if normalized_key in {"media_type", "mediatype"} and media_type == "image":
            continue
        stripped[key] = _strip_image_metadata(nested)
    return stripped


def _set_validated_search_result_image(
    result: SearchResult,
    validated_url: str,
) -> None:
    result.thumbnail_url = validated_url
    result.image_url = validated_url
    if result.media_type != "video":
        result.media_url = validated_url
        result.media_type = "image"

    metadata = dict(result.metadata)
    metadata["thumbnail_url"] = validated_url
    metadata["image_url"] = validated_url
    if result.media_type != "video":
        metadata["media_url"] = validated_url
        metadata["media_type"] = "image"
    result.metadata = metadata


def _merge_search_result_media(
    result: SearchResult,
    incoming: dict[str, str],
) -> None:
    if not any(incoming.values()):
        return

    previous_thumbnail = result.thumbnail_url
    previous_image = result.image_url
    previous_media = result.media_url
    previous_type = result.media_type
    previous_image_was_thumbnail = bool(
        previous_image
        and previous_thumbnail
        and previous_image == previous_thumbnail
    )

    incoming_thumbnail = incoming.get("thumbnail_url", "")
    incoming_image = incoming.get("image_url", "")
    incoming_media = incoming.get("media_url", "")
    incoming_type = incoming.get("media_type", "")

    if not result.thumbnail_url:
        result.thumbnail_url = incoming_thumbnail or incoming_image

    replaced_fallback_image = False
    if incoming_image and (not previous_image or previous_image_was_thumbnail):
        result.image_url = incoming_image
        replaced_fallback_image = True
    elif not result.image_url and incoming_thumbnail:
        result.image_url = incoming_thumbnail

    if not previous_type:
        result.media_type = incoming_type
    if previous_type != "video":
        previous_media_was_fallback = (
            not previous_media
            or not previous_type
            or previous_media in {previous_thumbnail, previous_image}
        )
        if replaced_fallback_image and previous_media_was_fallback:
            result.media_url = result.image_url
            result.media_type = incoming_type or "image"
        elif not result.media_url:
            result.media_url = incoming_media or result.image_url or result.thumbnail_url
            result.media_type = result.media_type or incoming_type

    metadata = dict(result.metadata)
    for key in ("thumbnail_url", "image_url", "media_url", "media_type"):
        value = getattr(result, key)
        if value:
            metadata[key] = value
    video_url = incoming.get("video_url", "")
    if video_url and not metadata.get("video_url"):
        metadata["video_url"] = video_url
    result.metadata = metadata


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


def _normalize_media_type(value: Any) -> str:
    normalized = str(value or "").strip().lower()
    if normalized.startswith("image") or normalized in {"photo", "picture"}:
        return "image"
    if normalized.startswith("video") or normalized in {"movie", "clip"}:
        return "video"
    return ""


def _media_type_from_url(url: str) -> str:
    path = urlparse(str(url or "")).path.lower()
    if path.endswith(
        (".avif", ".bmp", ".gif", ".heic", ".jpeg", ".jpg", ".png", ".svg", ".webp")
    ):
        return "image"
    if path.endswith((".avi", ".m4v", ".mkv", ".mov", ".mp4", ".mpeg", ".mpg", ".webm")):
        return "video"
    return ""


def _resolve_page_media_url(
    raw_url: str,
    *,
    page_url: str,
    base_href: str = "",
) -> str:
    value = str(raw_url or "").strip()
    if not value:
        return ""
    base_url = urljoin(page_url, str(base_href or "").strip()) if base_href else page_url
    resolved = urljoin(base_url, value)
    return resolved if _is_public_http_url(resolved) else ""


def _html_page_media_metadata(
    parser: _ReadableHTMLParser,
    *,
    page_url: str,
) -> dict[str, Any]:
    image_candidates: list[str] = []
    seen: set[str] = set()
    for candidate in parser.image_urls:
        image_url = _resolve_page_media_url(
            candidate,
            page_url=page_url,
            base_href=parser.base_href,
        )
        if not image_url or image_url in seen:
            continue
        seen.add(image_url)
        image_candidates.append(image_url)
    if not image_candidates:
        return {}
    image_url = image_candidates[0]
    return {
        "thumbnail_url": image_url,
        "image_url": image_url,
        "media_url": image_url,
        "media_type": "image",
        "_image_candidates": image_candidates,
    }
