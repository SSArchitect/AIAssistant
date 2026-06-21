from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from pydantic import BaseModel, Field


class RunEvent(BaseModel):
    id: str
    run_id: str
    type: str
    status: str
    title: str = ""
    step_id: Optional[str] = None
    payload: dict[str, Any] = Field(default_factory=dict)
    duration_ms: Optional[int] = None
    created_at: datetime


class RunRecord(BaseModel):
    run_id: str
    conversation_id: str
    agent_id: str
    runtime: str
    status: str
    input: str
    output: str = ""
    model_used: str = ""
    tokens_used: dict[str, int] = Field(default_factory=dict)
    skills_used: list[str] = Field(default_factory=list)
    error_type: Optional[str] = None
    error_message: Optional[str] = None
    duration_ms: Optional[int] = None
    started_at: datetime
    completed_at: Optional[datetime] = None
    events: list[RunEvent] = Field(default_factory=list)


class RunListResponse(BaseModel):
    runs: list[RunRecord] = Field(default_factory=list)
