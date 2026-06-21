from __future__ import annotations

import base64
import re
from typing import Any


DATA_URL_RE = re.compile(r"^data:([^;,]+);base64,(.*)$", re.DOTALL)


def normalize_content_parts(content: str | list[dict[str, Any]]) -> list[dict[str, Any]]:
    if isinstance(content, str):
        return [{"type": "text", "text": content}]
    parts: list[dict[str, Any]] = []
    for item in content:
        if not isinstance(item, dict):
            parts.append({"type": "text", "text": str(item)})
            continue
        item_type = str(item.get("type") or "").strip()
        if item_type == "text":
            text = str(item.get("text") or "")
            if text:
                parts.append({"type": "text", "text": text})
            continue
        if item_type == "image_url":
            image_url = item.get("image_url")
            if isinstance(image_url, dict):
                url = str(image_url.get("url") or "").strip()
            else:
                url = str(image_url or "").strip()
            if url:
                parts.append({"type": "image_url", "image_url": {"url": url}})
            continue
        parts.append({"type": "text", "text": str(item)})
    return parts


def content_to_plain_text(content: str | list[dict[str, Any]]) -> str:
    if isinstance(content, str):
        return content
    chunks: list[str] = []
    for item in normalize_content_parts(content):
        if item["type"] == "text":
            chunks.append(item["text"])
        elif item["type"] == "image_url":
            chunks.append("[image attachment]")
    return "\n".join(chunk for chunk in chunks if chunk)


def data_url_bytes(data_url: str) -> tuple[str, bytes] | None:
    match = DATA_URL_RE.match(data_url.strip())
    if not match:
        return None
    mime_type = match.group(1)
    try:
        data = base64.b64decode(match.group(2), validate=False)
    except Exception:
        return None
    return mime_type, data
