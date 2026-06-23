from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


MemoryKind = Literal["role", "persona", "long_term"]
MemoryScope = Literal["user", "chat", "agent", "workspace"]
MemoryStatus = Literal["active", "pending_review", "archived"]
MemoryReviewState = Literal["manual", "auto_accepted", "pending", "reviewed"]


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
    user_id: Optional[str] = None
    id: Optional[str] = None
    name: str
    description: str = ""
    base_persona: str = ""
    instructions: list[str] = Field(default_factory=list)
    enabled: bool = True
    memory_enabled: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class RoleUpdateRequest(BaseModel):
    user_id: Optional[str] = None
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
    user_id: str = "0"
    kind: MemoryKind
    scope: MemoryScope = "user"
    status: MemoryStatus = "active"
    review_state: MemoryReviewState = "manual"
    content: str
    source: str = "manual"
    agent_id: Optional[str] = None
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)
    source_trace: dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    last_used_at: Optional[datetime] = None
    ttl_days: Optional[int] = None
    sensitivity: str = "normal"
    review_notes: str = ""
    version: int = 1
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
    user_id: Optional[str] = None
    kind: MemoryKind = "long_term"
    scope: MemoryScope = "user"
    status: MemoryStatus = "active"
    review_state: MemoryReviewState = "manual"
    content: str
    source: str = "manual"
    agent_id: Optional[str] = None
    confidence: float = 1.0
    tags: list[str] = Field(default_factory=list)
    source_trace: dict[str, Any] = Field(default_factory=dict)
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    ttl_days: Optional[int] = None
    sensitivity: str = "normal"
    review_notes: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class MemoryUpdateRequest(BaseModel):
    user_id: Optional[str] = None
    kind: Optional[MemoryKind] = None
    scope: Optional[MemoryScope] = None
    status: Optional[MemoryStatus] = None
    review_state: Optional[MemoryReviewState] = None
    content: Optional[str] = None
    source: Optional[str] = None
    agent_id: Optional[str] = None
    confidence: Optional[float] = None
    tags: Optional[list[str]] = None
    source_trace: Optional[dict[str, Any]] = None
    valid_from: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    ttl_days: Optional[int] = None
    sensitivity: Optional[str] = None
    review_notes: Optional[str] = None
    metadata: Optional[dict[str, Any]] = None


class MemoryListResponse(BaseModel):
    memories: list[MemoryRecord] = Field(default_factory=list)


class RoleListResponse(BaseModel):
    roles: list[RoleProfile] = Field(default_factory=list)
