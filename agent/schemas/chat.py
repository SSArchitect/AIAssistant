from __future__ import annotations
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field

from agent.schemas.memory import MemoryRecord
from agent.schemas.trace import RunEvent
from agent.schemas.handoff import AgentInputPacket


class ChatAttachment(BaseModel):
    name: str = ""
    type: str = ""
    size: int = 0
    kind: Literal["text", "image", "audio", "video", "file"] = "file"
    content: str = ""
    data_url: str = ""
    truncated: bool = False
    extraction_status: str = ""
    parser: str = ""
    extraction_error: str = ""
    extraction_metadata: dict[str, Any] = Field(default_factory=dict)


class DriveContextItem(BaseModel):
    id: str = ""
    type: str = ""
    name: str = ""
    path: str = ""
    mime_type: str = ""
    size: int = 0
    summary: str = ""
    updated_at: str = ""


class DriveContext(BaseModel):
    current_folder_id: str = ""
    current_path: str = ""
    items: list[DriveContextItem] = Field(default_factory=list)
    truncated: bool = False


class ChatRequest(BaseModel):
    conversation_id: str
    user_id: str = "0"
    message: str
    stream: bool = False
    model_preference: Optional[str] = None
    agent_id: str = "general_assistant"
    role_id: Optional[str] = None
    mode_ids: list[str] = Field(default_factory=list)
    mode_prompts: list[str] = Field(default_factory=list)
    context_blocks: list[str] = Field(default_factory=list)
    drive_context: DriveContext | None = None
    attachments: list["ChatAttachment"] = Field(default_factory=list)
    agent_input: AgentInputPacket | None = None
    handoff: AgentInputPacket | None = None
    memory_enabled: bool = True
    run_id: Optional[str] = None
    disabled_tools: list[str] = Field(default_factory=list)
    tool_policies: dict[str, Literal["auto", "confirm", "deny"]] = Field(default_factory=dict)


class SkillCallInfo(BaseModel):
    skill: str
    action: str
    status: str = "completed"
    result_summary: Optional[str] = None


class Citation(BaseModel):
    index: int = 0
    title: str = ""
    url: str = ""
    snippet: str = ""
    source: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatArtifact(BaseModel):
    type: str = "drive_file"
    item_id: str = ""
    name: str = ""
    title: str = ""
    mime_type: str = ""
    size: int = 0
    summary: str = ""
    url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    skills_used: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    artifacts: list[ChatArtifact] = Field(default_factory=list)
    plan: Optional[list[SkillCallInfo]] = None
    model_used: str = ""
    tokens_used: dict[str, int] = Field(default_factory=dict)
    error_type: Optional[str] = None  # "rate_limit", etc.
    agent_id: str = "general_assistant"
    role_id: Optional[str] = None
    runtime: str = "self"
    run_id: Optional[str] = None
    events: list[RunEvent] = Field(default_factory=list)
    memory_context: list[MemoryRecord] = Field(default_factory=list)
    memory_updates: list[MemoryRecord] = Field(default_factory=list)


class FollowUpRequest(BaseModel):
    user_question: str
    assistant_answer: str
    language: Literal["zh", "en"] = "zh"
    model_preference: Optional[str] = None


class FollowUpResponse(BaseModel):
    questions: list[str] = Field(default_factory=list)
    model_used: str = ""


class SkillParameterSchema(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True
    default: Any = None
    enum: list[Any] = Field(default_factory=list)
    items: dict[str, Any] | None = None
    minimum: float | int | None = None
    maximum: float | int | None = None
    min_length: int | None = None
    max_length: int | None = None
    pattern: str | None = None
    format: str | None = None


class SkillInfo(BaseModel):
    name: str
    description: str
    parameters: list[SkillParameterSchema] = Field(default_factory=list)
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    source: str = "builtin"
    enabled: bool = True
    risk_level: Literal["low", "medium", "high"] = "low"
    access: Literal["read", "write", "destructive", "external"] = "read"
    default_policy: Literal["auto", "confirm", "deny"] = "auto"
    max_calls_per_run: int = 8
    timeout_seconds: float = 30.0
    sensitive_arguments: list[str] = Field(default_factory=list)
    sensitive_result_fields: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    routing_keywords: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    always_on: bool = False
    discoverable: bool = True
    parallel_safe: bool = False
    idempotent: bool = False
    output_schema: dict[str, Any] = Field(default_factory=dict)
    user_enabled: bool | None = None
    effective_enabled: bool = True
    user_policy: Literal["auto", "confirm", "deny"] | None = None
    effective_policy: Literal["auto", "confirm", "deny"] = "auto"
    configurable: bool = False


class SkillListResponse(BaseModel):
    skills: list[SkillInfo]
