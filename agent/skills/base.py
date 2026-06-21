from __future__ import annotations
from abc import ABC, abstractmethod
from typing import Any, Optional

from pydantic import BaseModel, Field


class SkillParameter(BaseModel):
    name: str
    type: str  # "string", "number", "boolean", "object"
    description: str
    required: bool = True
    default: Any = None


class SkillMetadata(BaseModel):
    name: str
    description: str
    parameters: list[SkillParameter] = Field(default_factory=list)
    version: str = "1.0.0"
    tags: list[str] = Field(default_factory=list)
    source: str = "builtin"
    enabled: bool = True


class SkillResult(BaseModel):
    success: bool
    data: Any = None
    error: Optional[str] = None
    display_text: Optional[str] = None


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
            }
            properties[p.name] = {
                "type": type_map.get(p.type, "string"),
                "description": p.description,
            }
            if p.required:
                required.append(p.name)

        return {
            "name": meta.name,
            "description": meta.description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
            },
        }
