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
    attachments: list["ChatAttachment"] = Field(default_factory=list)
    agent_input: AgentInputPacket | None = None
    handoff: AgentInputPacket | None = None
    memory_enabled: bool = True
    run_id: Optional[str] = None


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


class ChatResponse(BaseModel):
    conversation_id: str
    response: str
    skills_used: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
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


class SkillParameterSchema(BaseModel):
    name: str
    type: str
    description: str
    required: bool = True


class SkillInfo(BaseModel):
    name: str
    description: str
    parameters: list[SkillParameterSchema] = Field(default_factory=list)
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    source: str = "builtin"
    enabled: bool = True


class SkillListResponse(BaseModel):
    skills: list[SkillInfo]
