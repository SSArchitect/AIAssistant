from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class DocumentParseRequest(BaseModel):
    name: str = ""
    mime_type: str = ""
    data_base64: str = ""
    data_url: str = ""
    max_chars: int = Field(default=220000, ge=1000, le=220000)


class DocumentParseResponse(BaseModel):
    supported: bool
    format: str = ""
    parser: str = ""
    text: str = ""
    title: str = ""
    summary: str = ""
    truncated: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
