from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field


class SkillParameter(BaseModel):
    name: str
    type: str  # string, number, integer, boolean, object, array
    description: str
    required: bool = True
    default: Any = None
    enum: list[Any] = Field(default_factory=list)
    items: dict[str, Any] | None = None
    minimum: float | int | None = None
    maximum: float | int | None = None
    min_length: int | None = Field(default=None, ge=0)
    max_length: int | None = Field(default=None, ge=0)
    pattern: str | None = None
    format: str | None = None


class SkillMetadata(BaseModel):
    name: str
    description: str
    parameters: list[SkillParameter] = Field(default_factory=list)
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    source: str = "builtin"
    enabled: bool = True
    risk_level: Literal["low", "medium", "high"] = "low"
    access: Literal["read", "write", "destructive", "external"] = "read"
    default_policy: Literal["auto", "confirm", "deny"] = "auto"
    max_calls_per_run: int = Field(default=8, ge=1, le=100)
    timeout_seconds: float = Field(default=30.0, gt=0, le=600)
    sensitive_arguments: list[str] = Field(default_factory=list)
    sensitive_result_fields: list[str] = Field(default_factory=list)
    confirmation_keywords: list[str] = Field(default_factory=list)
    domains: list[str] = Field(default_factory=list)
    routing_keywords: list[str] = Field(default_factory=list)
    allowed_agents: list[str] = Field(default_factory=list)
    always_on: bool = False
    discoverable: bool = True
    parallel_safe: bool = False
    idempotent: bool = False
    output_schema: dict[str, Any] = Field(default_factory=dict)


class SkillResult(BaseModel):
    success: bool
    data: Any = None
    error: Optional[str] = None
    error_code: Optional[str] = None
    retryable: bool = False
    display_text: Optional[str] = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class Skill(ABC):
    @abstractmethod
    def metadata(self) -> SkillMetadata:
        """Return skill metadata for LLM tool-use descriptions."""
        ...

    @abstractmethod
    async def execute(self, **kwargs) -> SkillResult:
        """Execute the skill with given parameters."""
        ...

    def to_tool_definition(self) -> dict:
        """Convert skill metadata to LLM tool definition (JSON Schema)."""
        meta = self.metadata()
        properties = {}
        required = []
        for p in meta.parameters:
            type_map = {
                "string": "string",
                "number": "number",
                "boolean": "boolean",
                "object": "object",
                "integer": "integer",
                "array": "array",
            }
            properties[p.name] = {
                "type": type_map.get(p.type, "string"),
                "description": p.description,
            }
            if p.default is not None:
                properties[p.name]["default"] = p.default
            if p.enum:
                properties[p.name]["enum"] = p.enum
            if p.items is not None:
                properties[p.name]["items"] = p.items
            if p.minimum is not None:
                properties[p.name]["minimum"] = p.minimum
            if p.maximum is not None:
                properties[p.name]["maximum"] = p.maximum
            if p.min_length is not None:
                properties[p.name]["minLength"] = p.min_length
            if p.max_length is not None:
                properties[p.name]["maxLength"] = p.max_length
            if p.pattern:
                properties[p.name]["pattern"] = p.pattern
            if p.format:
                properties[p.name]["format"] = p.format
            if p.required:
                required.append(p.name)

        return {
            "name": meta.name,
            "description": meta.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
            "output_schema": meta.output_schema,
            "metadata": {
                "version": meta.version,
                "tags": meta.tags,
                "source": meta.source,
                "risk_level": meta.risk_level,
                "access": meta.access,
                "default_policy": meta.default_policy,
                "max_calls_per_run": meta.max_calls_per_run,
                "timeout_seconds": meta.timeout_seconds,
                "sensitive_arguments": meta.sensitive_arguments,
                "sensitive_result_fields": meta.sensitive_result_fields,
                "confirmation_keywords": meta.confirmation_keywords,
                "domains": meta.domains,
                "routing_keywords": meta.routing_keywords,
                "allowed_agents": meta.allowed_agents,
                "always_on": meta.always_on,
                "discoverable": meta.discoverable,
                "parallel_safe": meta.parallel_safe,
                "idempotent": meta.idempotent,
            },
        }
