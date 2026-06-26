from __future__ import annotations

import json
import logging
import re
from collections import defaultdict
from pathlib import Path
from threading import RLock
from uuid import uuid4

from agent.schemas.memory import (
    MemoryContext,
    MemoryKind,
    MemoryRecord,
    MemoryUpdateRequest,
    RoleCreateRequest,
    RoleProfile,
    RoleUpdateRequest,
    utc_now,
)

logger = logging.getLogger(__name__)

DEFAULT_USER_ID = "0"
ROLE_OWNER_METADATA_KEY = "owner_user_id"
MEMORY_STORAGE_SCHEMA_VERSION = 2


def _role_metadata(
    *,
    category: str,
    zh_name: str,
    zh_description: str,
    en_name: str,
    en_description: str,
    preferences: list[str] | None = None,
) -> dict:
    return {
        "built_in": True,
        "category": category,
        "localized": {
            "zh": {"name": zh_name, "description": zh_description},
            "en": {"name": en_name, "description": en_description},
        },
        "preferences": preferences or [],
    }


DEFAULT_ROLE = RoleProfile(
    id="default",
    name="默认助手",
    description="日常聊天、问答、整理和轻量任务的默认角色。",
    base_persona=(
        "你是一位温和、清晰、有行动感的个人助手。你会先理解用户真正想完成的事，"
        "再用简洁的结构给出回答、建议或下一步。"
    ),
    instructions=[
        "把角色记忆作为私有上下文，用于提升相关性和连续性。",
        "除非用户询问，不要逐条复述记忆记录。",
        "如果记忆和当前用户消息冲突，优先相信当前消息。",
        "默认跟随用户当前使用的语言回答。",
    ],
    metadata=_role_metadata(
        category="daily",
        zh_name="默认助手",
        zh_description="日常聊天、问答、整理和轻量任务的默认角色。",
        en_name="Everyday Assistant",
        en_description="A balanced default persona for chat, Q&A, notes, and lightweight tasks.",
        preferences=["回答先给结论，再补必要背景。", "不确定时明确说明边界。"],
    ),
)

DEFAULT_ROLES = [
    DEFAULT_ROLE,
    RoleProfile(
        id="work_partner",
        name="工作搭档",
        description="适合拆任务、写计划、整理会议和推进日常工作。",
        base_persona=(
            "你是一位可靠的工作搭档。你擅长把杂乱信息整理成目标、行动项、优先级和"
            "可追踪的下一步。"
        ),
        instructions=[
            "先识别目标、截止时间、相关人和阻塞点。",
            "输出要便于直接复制到待办、周报或会议纪要。",
            "在信息不足时给出最小可行动版本，并标出需要补充的内容。",
        ],
        metadata=_role_metadata(
            category="work",
            zh_name="工作搭档",
            zh_description="适合拆任务、写计划、整理会议和推进日常工作。",
            en_name="Work Partner",
            en_description="For planning tasks, meeting notes, prioritization, and daily execution.",
            preferences=["偏好行动清单和明确负责人。", "复杂事项先拆阶段。"],
        ),
    ),
    RoleProfile(
        id="learning_coach",
        name="学习教练",
        description="适合学习计划、概念讲解、复习路径和刻意练习。",
        base_persona=(
            "你是一位耐心但不纵容模糊的学习教练。你会先判断用户当前水平，再用小步解释、"
            "例题、反问和复盘帮助用户真正掌握。"
        ),
        instructions=[
            "先判断用户已经知道什么，再决定讲解深度。",
            "复杂概念用例子和对比解释。",
            "每次给一个可练习的小任务，避免一次塞太多内容。",
        ],
        metadata=_role_metadata(
            category="learning",
            zh_name="学习教练",
            zh_description="适合学习计划、概念讲解、复习路径和刻意练习。",
            en_name="Learning Coach",
            en_description="For learning plans, explanations, review paths, and deliberate practice.",
            preferences=["一步一步讲清楚。", "用小测和复盘确认掌握。"],
        ),
    ),
    RoleProfile(
        id="初一",
        name="初一",
        description="一个赛博小书生，适合陪聊、解释知识、整理灵感和轻快共创。",
        base_persona=(
            "你是一个赛博小书生，上通天文，下懂地理，技巧可爱。你会用轻快、有书卷气"
            "但不过度表演的方式陪用户聊天、解释问题、整理想法。"
        ),
        instructions=[
            "默认跟随用户当前使用的语言回答。",
            "解释复杂问题时先用通俗说法，再补关键细节。",
            "可以保持一点灵动可爱的表达，但不要影响准确性和效率。",
        ],
        metadata=_role_metadata(
            category="companion",
            zh_name="初一",
            zh_description="一个赛博小书生，适合陪聊、解释知识、整理灵感和轻快共创。",
            en_name="Chuyi",
            en_description="A cyber young scholar for conversation, explanations, idea sorting, and playful collaboration.",
            preferences=["语气轻巧可爱，但不牺牲准确性。", "先讲通俗版本，再补关键细节。"],
        ),
    ),
]


class RoleMemoryStore:
    """Bounded in-memory role/persona/long-term memory store.

    The interface is intentionally small so the backend can move to SQLite,
    vector search, or an app-scoped provider without changing AgentEngine.
    """

    _TERM_STOPWORDS = {
        "the",
        "and",
        "for",
        "that",
        "this",
        "with",
        "user",
        "users",
        "我的",
        "这个",
        "那个",
        "一下",
        "帮我",
        "用户",
        "问题",
        "提问",
        "什么",
        "怎么",
        "可以",
        "看看",
    }
    _ZH_STOP_CHARS = set("我你他她它的是了和吗呢吧啊哦嗯这那有在")
    _RELATED_MEMORY_SIMILARITY_THRESHOLD = 0.64
    _MAX_MERGED_CONTENT_CHARS = 260
    _MAX_RENDERED_CONTENT_CHARS = 360

    def __init__(
        self,
        *,
        roles: list[RoleProfile] | None = None,
        storage_path: str | Path | None = None,
        max_records_per_role: int = 120,
        max_context_records: int = 12,
    ):
        self._roles: dict[str, RoleProfile] = {
            self._role_storage_key(role): role for role in DEFAULT_ROLES
        }
        self._records: dict[str, list[MemoryRecord]] = defaultdict(list)
        self._storage_path = Path(storage_path) if storage_path else None
        self._max_records_per_role = max_records_per_role
        self._max_context_records = max_context_records
        self._storage_needs_migration = False
        self._lock = RLock()
        self._load()
        self._sync_default_roles()
        if self._storage_needs_migration:
            with self._lock:
                self._persist_locked()
        for role in roles or []:
            self.register_role(role)

    def register_role(
        self,
        role: RoleProfile,
        *,
        user_id: str | None = None,
    ) -> RoleProfile:
        role = self._role_with_owner(role, user_id=user_id)
        with self._lock:
            self._roles[self._role_storage_key(role)] = role
            self._persist_locked()
        return role

    def create_role(self, request: RoleCreateRequest) -> RoleProfile:
        role_id = self._clean_role_id(request.id or request.name)
        if not role_id:
            raise ValueError("role id cannot be empty")
        owner_user_id = self._normalize_user_id(request.user_id)

        with self._lock:
            if role_id in self._default_role_ids():
                raise ValueError(f"role id is reserved by built-in role: {role_id}")
            role_key = self._role_storage_key_for(role_id, owner_user_id)
            if role_key in self._roles:
                raise ValueError(f"role already exists for user {owner_user_id}: {role_id}")
            role = RoleProfile(
                id=role_id,
                name=request.name.strip(),
                description=request.description.strip(),
                base_persona=request.base_persona.strip(),
                instructions=[item.strip() for item in request.instructions if item.strip()],
                enabled=request.enabled,
                memory_enabled=request.memory_enabled,
                metadata={
                    **request.metadata,
                    "built_in": False,
                    ROLE_OWNER_METADATA_KEY: owner_user_id,
                },
            )
            self._roles[role_key] = role
            self._persist_locked()
            return role

    def update_role(self, role_id: str, request: RoleUpdateRequest) -> RoleProfile:
        owner_user_id = self._normalize_user_id(request.user_id)
        with self._lock:
            role_key = self._role_storage_key_for(role_id, owner_user_id)
            role = self._roles.get(role_key)
            if role is None:
                raise ValueError(f"unknown role: {role_id}")
            if role.metadata.get("built_in"):
                raise ValueError(f"cannot update built-in role: {role_id}")

            updates = request.model_dump(exclude_unset=True)
            updates.pop("user_id", None)
            metadata = updates.pop("metadata", None)
            if "name" in updates and updates["name"] is not None:
                updates["name"] = updates["name"].strip()
            if "description" in updates and updates["description"] is not None:
                updates["description"] = updates["description"].strip()
            if "base_persona" in updates and updates["base_persona"] is not None:
                updates["base_persona"] = updates["base_persona"].strip()
            if "instructions" in updates and updates["instructions"] is not None:
                updates["instructions"] = [
                    item.strip()
                    for item in updates["instructions"]
                    if item.strip()
                ]
            if metadata is not None:
                updates["metadata"] = {
                    **role.metadata,
                    **metadata,
                    "built_in": False,
                    ROLE_OWNER_METADATA_KEY: owner_user_id,
                }

            updated = role.model_copy(update=updates)
            self._roles[role_key] = updated
            self._persist_locked()
            return updated

    def delete_role(self, role_id: str, *, user_id: str | None = None) -> None:
        owner_user_id = self._normalize_user_id(user_id)
        with self._lock:
            role_key = self._role_storage_key_for(role_id, owner_user_id)
            role = self._roles.get(role_key)
            if role is None:
                raise ValueError(f"unknown role: {role_id}")
            if role.metadata.get("built_in"):
                raise ValueError(f"cannot delete built-in role: {role_id}")
            self._roles.pop(role_key, None)
            self._records[role_id] = [
                record
                for record in self._records.get(role_id, [])
                if record.user_id != owner_user_id
            ]
            if not self._records[role_id]:
                self._records.pop(role_id, None)
            self._persist_locked()

    def list_roles(self, *, user_id: str | None = None) -> list[RoleProfile]:
        owner_user_id = self._normalize_user_id(user_id)
        with self._lock:
            built_ins = [
                self._roles[role.id]
                for role in DEFAULT_ROLES
                if role.id in self._roles
            ]
            custom = [
                role
                for role in self._roles.values()
                if not role.metadata.get("built_in")
                and self._role_owner_user_id(role) == owner_user_id
            ]
            return [*built_ins, *custom]

    def get_role(self, role_id: str, *, user_id: str | None = None) -> RoleProfile | None:
        owner_user_id = self._normalize_user_id(user_id)
        with self._lock:
            custom = self._roles.get(self._role_storage_key_for(role_id, owner_user_id))
            if custom is not None:
                return custom
            return self._roles.get(role_id)

    def add_memory(
        self,
        *,
        role_id: str,
        user_id: str | None = None,
        kind: MemoryKind,
        content: str,
        scope: str = "user",
        status: str = "active",
        review_state: str = "manual",
        source: str = "manual",
        agent_id: str | None = None,
        confidence: float = 1.0,
        tags: list[str] | None = None,
        source_trace: dict | None = None,
        valid_from=None,
        valid_until=None,
        ttl_days: int | None = None,
        sensitivity: str = "normal",
        review_notes: str = "",
        metadata: dict | None = None,
    ) -> MemoryRecord:
        normalized_content = self._clean_content(content)
        normalized_user_id = self._normalize_user_id(user_id)
        if not normalized_content:
            raise ValueError("memory content cannot be empty")

        with self._lock:
            if self.get_role(role_id, user_id=normalized_user_id) is None:
                raise ValueError(f"unknown role: {role_id}")

            duplicate = self._find_duplicate(
                role_id=role_id,
                user_id=normalized_user_id,
                kind=kind,
                content=normalized_content,
                agent_id=agent_id,
            )
            if duplicate is not None:
                merged_content = self._merge_memory_content(
                    duplicate.content,
                    normalized_content,
                )
                if merged_content != duplicate.content:
                    duplicate.content = merged_content
                duplicate.updated_at = utc_now()
                duplicate.confidence = max(duplicate.confidence, confidence)
                duplicate.tags = sorted(set(duplicate.tags).union(tags or []))
                duplicate.scope = scope or duplicate.scope
                duplicate.status = status or duplicate.status
                duplicate.review_state = review_state or duplicate.review_state
                duplicate.source_trace.update(source_trace or {})
                duplicate.valid_from = valid_from or duplicate.valid_from
                duplicate.valid_until = valid_until or duplicate.valid_until
                duplicate.ttl_days = ttl_days if ttl_days is not None else duplicate.ttl_days
                duplicate.sensitivity = sensitivity or duplicate.sensitivity
                duplicate.review_notes = review_notes or duplicate.review_notes
                duplicate.version += 1
                duplicate.metadata.update(metadata or {})
                self._persist_locked()
                return duplicate

            now = utc_now()
            record = MemoryRecord(
                id=f"mem_{uuid4().hex}",
                role_id=role_id,
                user_id=normalized_user_id,
                kind=kind,
                scope=scope,  # type: ignore[arg-type]
                status=status,  # type: ignore[arg-type]
                review_state=review_state,  # type: ignore[arg-type]
                content=normalized_content,
                source=source,
                agent_id=agent_id,
                confidence=confidence,
                tags=tags or [],
                source_trace=source_trace or {},
                valid_from=valid_from,
                valid_until=valid_until,
                ttl_days=ttl_days,
                sensitivity=sensitivity or "normal",
                review_notes=review_notes,
                created_at=now,
                updated_at=now,
                metadata=metadata or {},
            )
            self._records[role_id].append(record)
            self._truncate(role_id, user_id=normalized_user_id)
            self._persist_locked()
            return record

    def list_memories(
        self,
        *,
        role_id: str,
        user_id: str | None = None,
        kind: MemoryKind | None = None,
        agent_id: str | None = None,
        include_shared: bool = True,
        include_inactive: bool = False,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        with self._lock:
            records = list(self._records.get(role_id, []))

        normalized_user_id = self._normalize_user_id(user_id)
        records = [record for record in records if record.user_id == normalized_user_id]
        if kind is not None:
            records = [record for record in records if record.kind == kind]
        if agent_id is not None:
            records = [
                record
                for record in records
                if record.agent_id == agent_id
                or (include_shared and record.agent_id is None)
            ]
        if not include_inactive:
            records = [
                record
                for record in records
                if self._memory_is_context_eligible(record)
            ]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        if limit is not None:
            return records[:limit]
        return records

    @classmethod
    def group_memories_by_date(
        cls,
        records: list[MemoryRecord],
    ) -> list[dict[str, object]]:
        grouped: dict[str, list[MemoryRecord]] = defaultdict(list)
        for record in records:
            grouped[cls._memory_date_key(record)].append(record)

        groups: list[dict[str, object]] = []
        for date_key, date_records in grouped.items():
            date_records.sort(key=lambda record: record.updated_at, reverse=True)
            groups.append(
                {
                    "date": date_key,
                    "record_count": len(date_records),
                    "records": date_records,
                }
            )
        groups.sort(key=lambda group: str(group["date"]), reverse=True)
        return groups

    def update_memory(
        self,
        *,
        role_id: str,
        memory_id: str,
        request: MemoryUpdateRequest,
    ) -> MemoryRecord:
        normalized_user_id = self._normalize_user_id(request.user_id)
        with self._lock:
            if self.get_role(role_id, user_id=normalized_user_id) is None:
                raise ValueError(f"unknown role: {role_id}")

            record = self._find_memory_locked(
                role_id=role_id,
                memory_id=memory_id,
                user_id=normalized_user_id,
            )
            if record is None:
                raise ValueError(f"unknown memory: {memory_id}")

            updates = request.model_dump(exclude_unset=True)
            updates.pop("user_id", None)
            metadata = updates.pop("metadata", None)
            source_trace = updates.pop("source_trace", None)
            content = updates.pop("content", None)
            tags = updates.pop("tags", None)
            confidence = updates.pop("confidence", None)

            if content is not None:
                normalized_content = self._clean_content(content)
                if not normalized_content:
                    raise ValueError("memory content cannot be empty")
                record.content = normalized_content
            if tags is not None:
                record.tags = [
                    str(tag).strip()
                    for tag in tags
                    if str(tag).strip()
                ][:12]
            if confidence is not None:
                record.confidence = max(0.0, min(float(confidence), 1.0))
            if metadata is not None:
                record.metadata = {
                    **record.metadata,
                    **metadata,
                }
            if source_trace is not None:
                record.source_trace = {
                    **record.source_trace,
                    **source_trace,
                }

            for field_name, value in updates.items():
                if value is not None:
                    setattr(record, field_name, value)
            record.updated_at = utc_now()
            record.version += 1
            self._persist_locked()
            return record

    def delete_memory(
        self,
        *,
        role_id: str,
        memory_id: str,
        user_id: str | None = None,
    ) -> None:
        normalized_user_id = self._normalize_user_id(user_id)
        with self._lock:
            if self.get_role(role_id, user_id=normalized_user_id) is None:
                raise ValueError(f"unknown role: {role_id}")

            records = self._records.get(role_id, [])
            next_records = [
                record
                for record in records
                if record.id != memory_id or record.user_id != normalized_user_id
            ]
            if len(next_records) == len(records):
                raise ValueError(f"unknown memory: {memory_id}")

            self._records[role_id] = next_records
            self._persist_locked()

    def get_context(
        self,
        *,
        role_id: str,
        user_id: str | None = None,
        agent_id: str | None = None,
        query: str | None = None,
    ) -> MemoryContext | None:
        role = self.get_role(role_id, user_id=user_id)
        if role is None:
            return None
        role_memories = self.list_memories(
            role_id=role_id,
            user_id=user_id,
            kind="role",
            agent_id=agent_id,
            limit=self._max_context_records,
        )
        persona_memories = self.list_memories(
            role_id=role_id,
            user_id=user_id,
            kind="persona",
            agent_id=agent_id,
            limit=self._max_context_records,
        )
        long_term_memories = self.list_memories(
            role_id=role_id,
            user_id=user_id,
            kind="long_term",
            agent_id=agent_id,
        )
        long_term_memories = self._select_relevant_memories(
            long_term_memories,
            query=query,
            limit=self._max_context_records,
        )
        context = MemoryContext(
            role=role,
            persona_memories=[*role_memories, *persona_memories],
            long_term_memories=long_term_memories,
        )
        self._mark_used(context.records)
        context.rendered = self.render_context(context)
        return context

    def render_context(self, context: MemoryContext) -> str:
        role = context.role
        lines = ["长期记忆："]
        if context.long_term_memories:
            for group in self.group_memories_by_date(context.long_term_memories):
                lines.append(f"- {group['date']}：")
                lines.extend(
                    f"  - {self._render_memory_content(record.content)}"
                    for record in group["records"]  # type: ignore[index]
                )
        else:
            lines.append("- 暂无。")

        lines.extend(["", "角色记忆：", f"- 角色 ID：{role.id}", f"- 角色名称：{role.name}"])
        if role.description:
            lines.append(f"- 角色描述：{role.description}")
        if role.base_persona:
            lines.append(f"- 基础人设：{role.base_persona}")
        if role.instructions:
            lines.append("- 角色指令：")
            lines.extend(f"  - {item}" for item in role.instructions)
        preferences = self._metadata_list(role.metadata.get("preferences"))
        if preferences:
            lines.append("- 习惯/偏好：")
            lines.extend(f"  - {item}" for item in preferences)
        if context.persona_memories:
            lines.append("- 用户更新的角色记忆：")
            for group in self.group_memories_by_date(context.persona_memories):
                lines.append(f"  - {group['date']}：")
                lines.extend(
                    f"    - {self._render_memory_content(record.content)}"
                    for record in group["records"]  # type: ignore[index]
                )
        return "\n".join(lines)

    def _find_duplicate(
        self,
        *,
        role_id: str,
        user_id: str,
        kind: MemoryKind,
        content: str,
        agent_id: str | None,
    ) -> MemoryRecord | None:
        normalized = self._normalize_for_dedupe(content)
        for record in self._records.get(role_id, []):
            if (
                record.user_id != user_id
                or record.kind != kind
                or record.agent_id != agent_id
            ):
                continue
            if self._normalize_for_dedupe(record.content) == normalized:
                return record
            if (
                self._memory_similarity(record.content, content)
                >= self._RELATED_MEMORY_SIMILARITY_THRESHOLD
            ):
                return record
        return None

    @classmethod
    def _merge_memory_content(cls, existing: str, incoming: str) -> str:
        existing = cls._clean_content(existing)
        incoming = cls._clean_content(incoming)
        if not incoming:
            return existing
        if not existing:
            return incoming

        normalized_existing = cls._normalize_for_dedupe(existing)
        normalized_incoming = cls._normalize_for_dedupe(incoming)
        if normalized_existing == normalized_incoming:
            return existing
        if normalized_incoming in normalized_existing:
            return existing
        if normalized_existing in normalized_incoming:
            return incoming[: cls._MAX_MERGED_CONTENT_CHARS].rstrip()

        parts: list[str] = []
        for value in (existing, incoming):
            for part in re.split(r"[\n。；;]+", value):
                clean = cls._clean_content(part)
                if not clean:
                    continue
                if any(cls._memory_similarity(clean, current) >= 0.86 for current in parts):
                    continue
                parts.append(clean)

        separator = "；" if cls._contains_cjk(existing + incoming) else "; "
        merged = separator.join(parts).strip()
        if len(merged) <= cls._MAX_MERGED_CONTENT_CHARS:
            return merged
        return merged[: cls._MAX_MERGED_CONTENT_CHARS - 3].rstrip() + "..."

    def _select_relevant_memories(
        self,
        records: list[MemoryRecord],
        *,
        query: str | None,
        limit: int,
    ) -> list[MemoryRecord]:
        query_text = " ".join(str(query or "").split()).strip()
        if not query_text:
            return records[:limit]

        scored = [
            (self._memory_relevance_score(record, query_text), record)
            for record in records
        ]
        relevant = [
            (score, record)
            for score, record in scored
            if score > 0
        ]
        relevant.sort(key=lambda item: (item[0], item[1].updated_at), reverse=True)
        return [record for _, record in relevant[:limit]]

    def _memory_relevance_score(self, record: MemoryRecord, query: str) -> float:
        query_terms = self._dedupe_terms(query)
        if not query_terms:
            return 0.0

        content = " ".join(
            [
                record.content,
                " ".join(record.tags),
                str(record.metadata.get("reason") or ""),
            ]
        )
        content_terms = self._dedupe_terms(content)
        if not content_terms:
            return 0.0

        normalized_query = self._normalize_for_dedupe(query)
        normalized_content = self._normalize_for_dedupe(content)
        if len(normalized_query) >= 4 and normalized_query in normalized_content:
            return 6.0

        tag_terms = self._dedupe_terms(" ".join(record.tags))
        overlap = query_terms.intersection(content_terms)
        tag_overlap = query_terms.intersection(tag_terms)
        if not overlap and not tag_overlap:
            return 0.0
        strong_overlap = {
            term
            for term in overlap
            if len(term) >= 3 or re.search(r"[a-z0-9]", term)
        }
        if not tag_overlap and not strong_overlap and len(overlap) < 2:
            return 0.0
        return float(len(overlap)) + float(len(tag_overlap) * 2)

    @classmethod
    def _memory_similarity(cls, left: str, right: str) -> float:
        left_terms = cls._dedupe_terms(left)
        right_terms = cls._dedupe_terms(right)
        if not left_terms or not right_terms:
            return 0.0
        if cls._normalize_for_dedupe(left) in cls._normalize_for_dedupe(right):
            return 1.0
        if cls._normalize_for_dedupe(right) in cls._normalize_for_dedupe(left):
            return 1.0
        overlap = len(left_terms.intersection(right_terms))
        union = len(left_terms.union(right_terms))
        return overlap / union if union else 0.0

    @classmethod
    def _dedupe_terms(cls, value: str) -> set[str]:
        text = cls._normalize_for_dedupe(value)
        terms: set[str] = set()
        for token in re.findall(r"[a-z0-9][a-z0-9_\-]{1,}", text):
            if token not in cls._TERM_STOPWORDS:
                terms.add(token)
        for segment in re.findall(r"[\u4e00-\u9fff]+", text):
            if len(segment) == 1:
                if segment not in cls._ZH_STOP_CHARS:
                    terms.add(segment)
                continue
            for size in (2, 3):
                if len(segment) < size:
                    continue
                for index in range(0, len(segment) - size + 1):
                    term = segment[index : index + size]
                    if term not in cls._TERM_STOPWORDS:
                        terms.add(term)
        return terms

    def _find_memory_locked(
        self,
        *,
        role_id: str,
        memory_id: str,
        user_id: str,
    ) -> MemoryRecord | None:
        for record in self._records.get(role_id, []):
            if record.id == memory_id and record.user_id == user_id:
                return record
        return None

    def _mark_used(self, records: list[MemoryRecord]) -> None:
        if not records:
            return
        now = utc_now()
        for record in records:
            record.last_used_at = now
        with self._lock:
            self._persist_locked()

    def _memory_is_context_eligible(self, record: MemoryRecord) -> bool:
        if record.status != "active":
            return False
        if record.valid_until is not None and record.valid_until <= utc_now():
            return False
        return True

    @staticmethod
    def _memory_date_key(record: MemoryRecord) -> str:
        value = record.updated_at or record.created_at
        return value.date().isoformat()

    @classmethod
    def _render_memory_content(cls, content: str) -> str:
        text = cls._clean_content(content)
        if len(text) <= cls._MAX_RENDERED_CONTENT_CHARS:
            return text
        return text[: cls._MAX_RENDERED_CONTENT_CHARS - 3].rstrip() + "..."

    def _truncate(self, role_id: str, *, user_id: str) -> None:
        records = self._records[role_id]
        scoped_records = [record for record in records if record.user_id == user_id]
        if len(scoped_records) <= self._max_records_per_role:
            return
        scoped_records.sort(key=lambda record: record.updated_at, reverse=True)
        keep_ids = {record.id for record in scoped_records[: self._max_records_per_role]}
        self._records[role_id] = [
            record
            for record in records
            if record.user_id != user_id or record.id in keep_ids
        ]

    def _sync_default_roles(self) -> None:
        changed = False
        with self._lock:
            default_role_ids = {role.id for role in DEFAULT_ROLES}
            for role in DEFAULT_ROLES:
                current = self._roles.get(role.id)
                if current != role:
                    changed = changed or current != role
                    self._roles[role.id] = role
            stale_role_keys = [
                role_key
                for role_key, role in self._roles.items()
                if (
                    role.metadata.get("built_in")
                    and role.id not in default_role_ids
                )
                or (
                    not role.metadata.get("built_in")
                    and role.id in default_role_ids
                )
            ]
            for role_key in stale_role_keys:
                role = self._roles.pop(role_key, None)
                if role is not None and role.metadata.get("built_in"):
                    self._records.pop(role.id, None)
                changed = True
            if changed:
                self._persist_locked()

    def _load(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return

        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                return
            self._storage_needs_migration = (
                payload.get("schema_version") != MEMORY_STORAGE_SCHEMA_VERSION
            )
            for role_data in payload.get("roles", []):
                role = RoleProfile.model_validate(role_data)
                role = self._role_with_owner(role)
                self._roles[self._role_storage_key(role)] = role

            loaded_records: dict[str, list[MemoryRecord]] = defaultdict(list)
            record_items: list[dict] = []
            if isinstance(payload.get("record_groups"), list):
                for group in payload.get("record_groups", []):
                    if not isinstance(group, dict):
                        continue
                    records = group.get("records")
                    if isinstance(records, list):
                        record_items.extend(item for item in records if isinstance(item, dict))
            elif isinstance(payload.get("records_by_date"), dict):
                for records in payload.get("records_by_date", {}).values():
                    if isinstance(records, list):
                        record_items.extend(item for item in records if isinstance(item, dict))
                self._storage_needs_migration = True
            else:
                records = payload.get("records", [])
                if isinstance(records, list):
                    record_items.extend(item for item in records if isinstance(item, dict))

            for record_data in record_items:
                record = MemoryRecord.model_validate(record_data)
                loaded_records[record.role_id].append(record)
            self._records = loaded_records
        except Exception:
            logger.exception("Failed to load role memory from %s", self._storage_path)

    def _persist_locked(self) -> None:
        if self._storage_path is None:
            return

        self._storage_path.parent.mkdir(parents=True, exist_ok=True)
        records = [
            record
            for role_records in self._records.values()
            for record in role_records
        ]
        payload = {
            "schema_version": MEMORY_STORAGE_SCHEMA_VERSION,
            "roles": [
                role.model_dump(mode="json")
                for role in self._roles.values()
            ],
            "record_groups": [
                {
                    "date": group["date"],
                    "record_count": group["record_count"],
                    "records": [
                        record.model_dump(mode="json")
                        for record in group["records"]  # type: ignore[index]
                    ],
                }
                for group in self.group_memories_by_date(records)
            ],
        }
        tmp_path = self._storage_path.with_suffix(self._storage_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self._storage_path)

    def _role_with_owner(
        self,
        role: RoleProfile,
        *,
        user_id: str | None = None,
    ) -> RoleProfile:
        if role.metadata.get("built_in"):
            metadata = {**role.metadata, "built_in": True}
            metadata.pop(ROLE_OWNER_METADATA_KEY, None)
            return role.model_copy(update={"metadata": metadata})

        owner_user_id = self._normalize_user_id(
            user_id
            or role.metadata.get(ROLE_OWNER_METADATA_KEY)
            or role.metadata.get("user_id")
        )
        return role.model_copy(
            update={
                "metadata": {
                    **role.metadata,
                    "built_in": False,
                    ROLE_OWNER_METADATA_KEY: owner_user_id,
                }
            }
        )

    def _role_storage_key(self, role: RoleProfile) -> str:
        if role.metadata.get("built_in"):
            return role.id
        return self._role_storage_key_for(role.id, self._role_owner_user_id(role))

    def _role_storage_key_for(self, role_id: str, user_id: str | None) -> str:
        if role_id in self._default_role_ids():
            return role_id
        return f"user:{self._normalize_user_id(user_id)}:role:{role_id}"

    def _role_owner_user_id(self, role: RoleProfile) -> str:
        return self._normalize_user_id(role.metadata.get(ROLE_OWNER_METADATA_KEY))

    @staticmethod
    def _default_role_ids() -> set[str]:
        return {role.id for role in DEFAULT_ROLES}

    @staticmethod
    def _normalize_user_id(value: str | int | None) -> str:
        text = str(value if value not in (None, "") else "0").strip()
        return text or "0"

    @staticmethod
    def _metadata_list(value: object) -> list[str]:
        if isinstance(value, str):
            return [value.strip()] if value.strip() else []
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()]
        return []

    @staticmethod
    def _clean_content(content: str) -> str:
        return content.strip().strip("。.!? \n\t")

    @staticmethod
    def _normalize_for_dedupe(content: str) -> str:
        content = content.lower().strip()
        content = re.sub(r"\s+", " ", content)
        return content.strip("。.!? ")

    @staticmethod
    def _contains_cjk(content: str) -> bool:
        return bool(re.search(r"[\u4e00-\u9fff]", content))

    @staticmethod
    def _clean_role_id(value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9_\-\u4e00-\u9fff]+", "_", value)
        value = re.sub(r"_+", "_", value)
        return value.strip("_-")
