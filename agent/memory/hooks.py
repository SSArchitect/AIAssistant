from __future__ import annotations

import re
from typing import Protocol

from agent.llm.base import LLMMessage
from agent.schemas.memory import MemoryCandidate, RoleProfile


class MemoryHook(Protocol):
    async def review_turn(
        self,
        *,
        role: RoleProfile,
        agent_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        new_messages: list[LLMMessage],
    ) -> list[MemoryCandidate]:
        ...


class HeuristicMemoryHook:
    """Small post-chat memory reviewer.

    This is the native placeholder for a future LLM-backed memory sub-agent. It
    only writes explicit or high-signal user facts, keeping memory curated.
    """

    _direct_patterns = [
        re.compile(
            r"(?:请)?(?:帮我)?记住(?:一下)?[：:\s]*(?P<content>.+)",
            re.I | re.S,
        ),
        re.compile(r"以后(?:请)?记得[：:\s]*(?P<content>.+)", re.I | re.S),
        re.compile(
            r"(?:please\s+)?remember(?: that)?[：:\s]+(?P<content>.+)",
            re.I | re.S,
        ),
    ]
    _negated_remember_patterns = [
        re.compile(r"(?:不要|别|无需|不用).{0,6}记住", re.I | re.S),
        re.compile(r"\b(?:do not|don't|dont|no need to)\s+remember\b", re.I | re.S),
    ]
    _persona_patterns = (
        re.compile(
            r"(?:你的人设|你的角色|你的说话风格|你的语气|以后你要|你应该|请你|请用|用.+?(?:风格|语气)).+",
            re.I | re.S,
        ),
        re.compile(
            r"\b(?:your persona|your role|your style|your tone|you should|please use|speak in)\b.+",
            re.I | re.S,
        ),
    )
    _ignored_fact_keys = {"问题", "请求", "意思", "想法", "观点"}
    _preference_patterns = [
        re.compile(
            r"我(?:喜欢|偏好|更喜欢|讨厌|不喜欢|习惯|常用).+",
            re.I | re.S,
        ),
        re.compile(
            r"我(?:正在|计划)(?!.*(?:帮我|帮忙|一下|这次|本轮|当前|怎么|如何|吗|？|\?)).+",
            re.I | re.S,
        ),
        re.compile(r"我的(?P<key>[^，。,.!?]{1,24})(?:是|叫|为).+", re.I | re.S),
        re.compile(r"\bmy\s+[^.?!]{1,48}\s+is\s+[^.?!]+", re.I | re.S),
        re.compile(
            r"\bi\s+(?:like|prefer|love|hate|use|work on|am working on|need|usually)\s+[^.?!]+",
            re.I | re.S,
        ),
    ]

    def __init__(self, *, max_candidate_chars: int = 240):
        self._max_candidate_chars = max_candidate_chars

    async def review_turn(
        self,
        *,
        role: RoleProfile,
        agent_id: str,
        conversation_id: str,
        user_message: str,
        assistant_message: str,
        new_messages: list[LLMMessage],
    ) -> list[MemoryCandidate]:
        if not role.memory_enabled:
            return []

        text = user_message.strip()
        if len(text) < 4:
            return []

        direct = self._extract_direct_memory(text)
        if direct:
            kind = "role" if self._looks_like_persona_memory(direct) else "long_term"
            return [
                MemoryCandidate(
                    kind=kind,
                    content=self._trim(direct),
                    confidence=0.9,
                    reason="explicit_remember_request",
                    tags=["explicit"],
                )
            ]

        if self._looks_like_persona_memory(text):
            return [
                MemoryCandidate(
                    kind="role",
                    content=self._trim(text),
                    confidence=0.72,
                    reason="persona_instruction",
                    tags=["persona"],
                )
            ]

        for pattern in self._preference_patterns:
            match = pattern.search(text)
            if match:
                key = match.groupdict().get("key")
                if key and key.strip() in self._ignored_fact_keys:
                    continue
                content = self._trim(match.group(0))
                return [
                    MemoryCandidate(
                        kind="long_term",
                        content=content,
                        confidence=0.7,
                        reason="user_preference_or_fact",
                        tags=["user_fact"],
                    )
                ]
        return []

    def _extract_direct_memory(self, text: str) -> str | None:
        if any(pattern.search(text) for pattern in self._negated_remember_patterns):
            return None
        for pattern in self._direct_patterns:
            match = pattern.search(text)
            if match:
                return match.group("content")
        return None

    def _looks_like_persona_memory(self, text: str) -> bool:
        return any(pattern.search(text) for pattern in self._persona_patterns)

    def _trim(self, text: str) -> str:
        text = re.sub(r"\s+", " ", text.strip()).strip("。.!? ")
        if len(text) <= self._max_candidate_chars:
            return text
        return text[: self._max_candidate_chars].rstrip() + "..."
