from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


AGENT_INPUT_PROTOCOL_VERSION = "agent_input.v1"
AGENT_HANDOFF_PROTOCOL_VERSION = AGENT_INPUT_PROTOCOL_VERSION


class AgentInputMessage(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    source: str = "conversation"
    index: int = 0


class AgentInputAttachment(BaseModel):
    name: str = ""
    kind: str = "file"
    mime_type: str = ""
    size: int = 0
    content_preview: str = ""
    has_data_url: bool = False
    truncated: bool = False


class AgentStageContext(BaseModel):
    stage_id: str
    status: Literal["pending", "running", "completed", "failed"] = "completed"
    summary: str = ""
    content: str = ""
    data: dict[str, Any] = Field(default_factory=dict)


class AgentInputPacket(BaseModel):
    protocol_version: Literal["agent_input.v1"] = AGENT_INPUT_PROTOCOL_VERSION
    source_agent_id: str
    target_agent_id: str
    reason: str = ""
    forced: bool = False
    conversation_id: str
    current_request: str
    mode_ids: list[str] = Field(default_factory=list)
    mode_prompts: list[str] = Field(default_factory=list)
    candidate_context_brief: str = ""
    messages: list[AgentInputMessage] = Field(default_factory=list)
    attachments: list[AgentInputAttachment] = Field(default_factory=list)
    stage_contexts: list[AgentStageContext] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


AgentHandoffMessage = AgentInputMessage
AgentHandoffAttachment = AgentInputAttachment
AgentHandoffPacket = AgentInputPacket
