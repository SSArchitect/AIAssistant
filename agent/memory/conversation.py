from __future__ import annotations
from collections import defaultdict

from agent.llm.base import LLMMessage


class ConversationMemory:
    """In-memory conversation history manager with context window management."""

    def __init__(self, max_messages: int = 50):
        self._history: dict[str, list[LLMMessage]] = defaultdict(list)
        self._max_messages = max_messages

    def get(self, conversation_id: str) -> list[LLMMessage]:
        return list(self._history[conversation_id])

    def add(self, conversation_id: str, message: LLMMessage) -> None:
        self._history[conversation_id].append(message)
        self._truncate(conversation_id)

    def add_many(self, conversation_id: str, messages: list[LLMMessage]) -> None:
        self._history[conversation_id].extend(messages)
        self._truncate(conversation_id)

    def clear(self, conversation_id: str) -> None:
        self._history.pop(conversation_id, None)

    def _truncate(self, conversation_id: str) -> None:
        history = self._history[conversation_id]
        if len(history) > self._max_messages:
            self._history[conversation_id] = history[-self._max_messages :]
