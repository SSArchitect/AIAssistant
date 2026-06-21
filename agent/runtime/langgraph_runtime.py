from __future__ import annotations

from importlib.util import find_spec


def is_available() -> bool:
    return find_spec("langgraph") is not None


def missing_dependency_message() -> str:
    return "Install langgraph to enable LangGraph-backed experimental agents."
