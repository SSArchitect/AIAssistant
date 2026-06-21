from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


MemoryKind = Literal["persona", "long_term"]


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class RoleProfile(BaseModel):
    id: str
    name: str
    description: str = ""
    base_persona: str = ""
    instructions: list[str] = Field(default_factory=list)
    enabled: bool = True
    memory_enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleCreateRequest(BaseModel):
    id: Optional[str] = None
    name: str
    description: str = ""
    base_persona: str = ""
    instructions: list[str] = Field(default_factory=list)
    enabled: bool = True
    memory_enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleUpdateRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    base_persona: Optional[str] = None
    instructions: Optional[list[str]] = None
    enabled: Optional[bool] = None
    memory_enabled: Optional[bool] = None
    metadata: Optional[dict[str, Any]] = None


class MemoryRecord(BaseModel):
    id: str
    role_id: str
    kind: MemoryKind
    content: str
    source: str = "manual"
    agent_id: Optional[str] = None
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryContext(BaseModel):
    role: RoleProfile
    persona_memories: list[MemoryRecord] = Field(default_factory=list)
    long_term_memories: list[MemoryRecord] = Field(default_factory=list)
    rendered: str = ""

    @property
    def records(self) -> list[MemoryRecord]:
        return [*self.persona_memories, *self.long_term_memories]


class MemoryCandidate(BaseModel):
    kind: MemoryKind
    content: str
    confidence: float = 0.7
    reason: str = ""
    tags: list[str] = Field(default_factory=list)
    agent_id: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryCreateRequest(BaseModel):
    kind: MemoryKind = "long_term"
    content: str
    source: str = "manual"
    agent_id: Optional[str] = None
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryListResponse(BaseModel):
    memories: list[MemoryRecord] = Field(default_factory=list)


class RoleListResponse(BaseModel):
    roles: list[RoleProfile] = Field(default_factory=list)
