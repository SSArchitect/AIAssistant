from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class AgentInfo(BaseModel):
    id: str
    name: str
    description: str
    runtime: str
    framework: str
    enabled: bool = True
    experimental: bool = False
    capabilities: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentListResponse(BaseModel):
    agents: list[AgentInfo] = Field(default_factory=list)
