from __future__ import annotations
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from agent.llm.base import LLMMessage


LOCAL_TIMEZONE = ZoneInfo("Asia/Shanghai")


@dataclass(frozen=True)
class ConversationSummaryBlock:
    """A bounded short-term summary bucket for one local date."""

    date: str
    content: str
    created_at: datetime
    updated_at: datetime
    version: int = 1


@dataclass(frozen=True)
class ConversationMemoryContext:
    """Short-term conversation memory used when building model context."""

    summary: str = ""
    summary_blocks: list[ConversationSummaryBlock] = field(default_factory=list)
    messages: list[LLMMessage] = field(default_factory=list)
    total_messages: int = 0


class ConversationMemory:
    """In-memory conversation history manager with summary-aware compaction."""

    def __init__(
        self,
        max_messages: int = 50,
        *,
        max_summary_block_chars: int = 1200,
        max_summary_blocks: int = 8,
        max_rendered_summary_chars: int = 2400,
    ):
        self._history: dict[str, list[LLMMessage]] = defaultdict(list)
        self._summary_blocks: dict[str, list[ConversationSummaryBlock]] = defaultdict(list)
        self._max_messages = max_messages
        self._max_summary_block_chars = max(200, max_summary_block_chars)
        self._max_summary_blocks = max(1, max_summary_blocks)
        self._max_rendered_summary_chars = max(200, max_rendered_summary_chars)

    def get(self, conversation_id: str) -> list[LLMMessage]:
        return list(self._history[conversation_id])

    def get_context(self, conversation_id: str) -> ConversationMemoryContext:
        messages = self.get(conversation_id)
        return ConversationMemoryContext(
            summary=self.get_summary(conversation_id),
            summary_blocks=self.get_summary_blocks(conversation_id),
            messages=messages,
            total_messages=len(messages),
        )

    def get_summary(self, conversation_id: str) -> str:
        blocks = self.get_summary_blocks(conversation_id)
        if not blocks:
            return ""

        lines: list[str] = []
        for block in blocks:
            lines.append(f"{block.date}:")
            for line in block.content.splitlines():
                content = line.strip().lstrip("- ").strip()
                if content:
                    lines.append(f"- {content}")
        rendered = "\n".join(lines).strip()
        if len(rendered) <= self._max_rendered_summary_chars:
            return rendered
        return rendered[: self._max_rendered_summary_chars].rstrip() + "..."

    def get_summary_blocks(self, conversation_id: str) -> list[ConversationSummaryBlock]:
        blocks = list(self._summary_blocks.get(conversation_id, []))
        blocks.sort(key=lambda block: (block.date, block.updated_at), reverse=True)
        return blocks[: self._max_summary_blocks]

    def set_summary(
        self,
        conversation_id: str,
        summary: str,
        *,
        date_key: str | None = None,
    ) -> None:
        summary = " ".join(str(summary or "").split()).strip()
        if summary:
            summary = self._clip_summary(summary)
            date_key = date_key or self._today_key()
            now = datetime.now(timezone.utc)
            existing_blocks = list(self._summary_blocks.get(conversation_id, []))
            existing = next(
                (block for block in existing_blocks if block.date == date_key),
                None,
            )
            next_block = ConversationSummaryBlock(
                date=date_key,
                content=summary,
                created_at=existing.created_at if existing else now,
                updated_at=now,
                version=(existing.version + 1) if existing else 1,
            )
            blocks = [block for block in existing_blocks if block.date != date_key]
            blocks.append(next_block)
            blocks.sort(key=lambda block: (block.date, block.updated_at), reverse=True)
            self._summary_blocks[conversation_id] = blocks[: self._max_summary_blocks]
        else:
            self._summary_blocks.pop(conversation_id, None)

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
        self._summary_blocks.pop(conversation_id, None)

    def _truncate(self, conversation_id: str) -> None:
        history = self._history[conversation_id]
        if len(history) > self._max_messages:
            self._history[conversation_id] = history[-self._max_messages :]

    def _clip_summary(self, summary: str) -> str:
        if len(summary) <= self._max_summary_block_chars:
            return summary
        return summary[: self._max_summary_block_chars].rstrip() + "..."

    @staticmethod
    def _today_key() -> str:
        return datetime.now(LOCAL_TIMEZONE).strftime("%Y-%m-%d")
