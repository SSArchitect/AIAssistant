from __future__ import annotations
from dataclasses import dataclass, field
from collections import defaultdict

from agent.llm.base import LLMMessage


@dataclass(frozen=True)
class ConversationMemoryContext:
    """Short-term conversation memory used when building model context."""

    summary: str = ""
    messages: list[LLMMessage] = field(default_factory=list)
    total_messages: int = 0


class ConversationMemory:
    """In-memory conversation history manager with summary-aware compaction."""

    def __init__(self, max_messages: int = 50):
        self._history: dict[str, list[LLMMessage]] = defaultdict(list)
        self._summaries: dict[str, str] = {}
        self._max_messages = max_messages

    def get(self, conversation_id: str) -> list[LLMMessage]:
        return list(self._history[conversation_id])

    def get_context(self, conversation_id: str) -> ConversationMemoryContext:
        messages = self.get(conversation_id)
        return ConversationMemoryContext(
            summary=self.get_summary(conversation_id),
            messages=messages,
            total_messages=len(messages),
        )

    def get_summary(self, conversation_id: str) -> str:
        return self._summaries.get(conversation_id, "")

    def set_summary(self, conversation_id: str, summary: str) -> None:
        summary = " ".join(str(summary or "").split()).strip()
        if summary:
            self._summaries[conversation_id] = summary
        else:
            self._summaries.pop(conversation_id, None)

    def add(self, conversation_id: str, message: LLMMessage) -> None:
        self._history[conversation_id].append(message)
        self._truncate(conversation_id)

    def add_many(self, conversation_id: str, messages: list[LLMMessage]) -> None:
        self._history[conversation_id].extend(messages)
        self._truncate(conversation_id)

    def needs_compaction(self, conversation_id: str, *, threshold: int) -> bool:
        return len(self._history[conversation_id]) > threshold

    def compact(
        self,
        conversation_id: str,
        *,
        summary: str,
        keep_messages: list[LLMMessage],
    ) -> None:
        self.set_summary(conversation_id, summary)
        self._history[conversation_id] = list(keep_messages)
        self._truncate(conversation_id)

    def clear(self, conversation_id: str) -> None:
        self._history.pop(conversation_id, None)
        self._summaries.pop(conversation_id, None)

    def _truncate(self, conversation_id: str) -> None:
        history = self._history[conversation_id]
        if len(history) > self._max_messages:
            self._history[conversation_id] = history[-self._max_messages :]
