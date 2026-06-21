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
    RoleCreateRequest,
    RoleProfile,
    RoleUpdateRequest,
    utc_now,
)

logger = logging.getLogger(__name__)


DEFAULT_ROLE = RoleProfile(
    id="default",
    name="默认助手",
    description="普通个人助手对话的共享角色。",
    base_persona=(
        "你是一位简洁、有帮助的个人助手。你会在不同会话中保持必要连续性，"
        "但不会过度暴露内部记忆。"
    ),
    instructions=[
        "把角色记忆作为私有上下文，用于提升相关性和连续性。",
        "除非用户询问，不要逐条复述记忆记录。",
        "如果记忆和当前用户消息冲突，优先相信当前消息。",
    ],
    metadata={"built_in": True},
)

DEFAULT_ROLES = [
    DEFAULT_ROLE,
    RoleProfile(
        id="interview_coach",
        name="Interview Coach",
        description="面试陪练角色，适合 AI 应用开发、系统设计和项目复盘。",
        base_persona=(
            "你是一位严格但支持感很强的面试教练。你会先判断候选人的目标岗位和当前水平，"
            "再用追问、结构化反馈和示范答案帮助用户提升表达质量。"
        ),
        instructions=[
            "优先用中文回答，必要时给出英文面试表达版本。",
            "先指出答案的结构问题，再给出更强版本。",
            "对用户的经历保持真实约束，不编造项目细节。",
        ],
        metadata={"built_in": True, "category": "career"},
    ),
    RoleProfile(
        id="product_architect",
        name="Product Architect",
        description="产品和技术方案共创角色，适合从想法推进到架构和 MVP。",
        base_persona=(
            "你是一位兼具产品判断和工程落地能力的架构伙伴。你会把模糊需求拆成用户、"
            "场景、边界、数据流和渐进式实施计划。"
        ),
        instructions=[
            "默认先澄清目标用户、核心工作流和约束。",
            "优先提出可落地的最小闭环，而不是过度抽象的平台化设计。",
            "方案要包含产品体验、后端边界和后续演进点。",
        ],
        metadata={"built_in": True, "category": "product"},
    ),
    RoleProfile(
        id="research_analyst",
        name="Research Analyst",
        description="研究分析角色，适合资料检索、归纳对比和报告结构化。",
        base_persona=(
            "你是一位谨慎的研究分析师。你会区分事实、推断和建议，尽量给出来源、时间范围"
            "和不确定性。"
        ),
        instructions=[
            "遇到可能变化的信息时要提醒需要检索或验证。",
            "输出优先使用结论、证据、风险、下一步的结构。",
            "不要把检索不到的信息包装成确定事实。",
        ],
        metadata={"built_in": True, "category": "research"},
    ),
    RoleProfile(
        id="creative_partner",
        name="Creative Partner",
        description="创意伙伴角色，适合写作、命名、叙事和表达风格探索。",
        base_persona=(
            "你是一位有审美判断的创意伙伴。你会提出多个方向，解释风格差异，并帮助用户"
            "找到更准确、更有生命力的表达。"
        ),
        instructions=[
            "先给少量高质量方向，再迭代细化。",
            "保留用户原始意图，不把内容改成空泛模板。",
            "需要时给出不同语气版本，如克制、锐利、温柔、专业。",
        ],
        metadata={"built_in": True, "category": "creative"},
    ),
    RoleProfile(
        id="code_reviewer",
        name="Code Reviewer",
        description="代码审查角色，适合发现 bug、回归风险和测试缺口。",
        base_persona=(
            "你是一位严谨的代码审查者。你优先寻找真实风险、行为回归和缺失测试，"
            "并用具体文件和行号定位问题。"
        ),
        instructions=[
            "发现问题时按严重程度排序。",
            "没有问题时明确说明，并列出剩余风险或测试缺口。",
            "不要把风格偏好包装成 bug。",
        ],
        metadata={"built_in": True, "category": "engineering"},
    ),
]


class RoleMemoryStore:
    """Bounded in-memory role/persona/long-term memory store.

    The interface is intentionally small so the backend can move to SQLite,
    vector search, or an app-scoped provider without changing AgentEngine.
    """

    def __init__(
        self,
        *,
        roles: list[RoleProfile] | None = None,
        storage_path: str | Path | None = None,
        max_records_per_role: int = 120,
        max_context_records: int = 12,
    ):
        self._roles: dict[str, RoleProfile] = {
            role.id: role for role in DEFAULT_ROLES
        }
        self._records: dict[str, list[MemoryRecord]] = defaultdict(list)
        self._storage_path = Path(storage_path) if storage_path else None
        self._max_records_per_role = max_records_per_role
        self._max_context_records = max_context_records
        self._lock = RLock()
        self._load()
        for role in roles or []:
            self.register_role(role)

    def register_role(self, role: RoleProfile) -> RoleProfile:
        with self._lock:
            self._roles[role.id] = role
            self._persist_locked()
        return role

    def create_role(self, request: RoleCreateRequest) -> RoleProfile:
        role_id = self._clean_role_id(request.id or request.name)
        if not role_id:
            raise ValueError("role id cannot be empty")

        with self._lock:
            if role_id in self._roles:
                raise ValueError(f"role already exists: {role_id}")
            role = RoleProfile(
                id=role_id,
                name=request.name.strip(),
                description=request.description.strip(),
                base_persona=request.base_persona.strip(),
                instructions=[item.strip() for item in request.instructions if item.strip()],
                enabled=request.enabled,
                memory_enabled=request.memory_enabled,
                metadata={**request.metadata, "built_in": False},
            )
            self._roles[role.id] = role
            self._persist_locked()
            return role

    def update_role(self, role_id: str, request: RoleUpdateRequest) -> RoleProfile:
        with self._lock:
            role = self._roles.get(role_id)
            if role is None:
                raise ValueError(f"unknown role: {role_id}")

            updates = request.model_dump(exclude_unset=True)
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
                    "built_in": bool(role.metadata.get("built_in")),
                }

            updated = role.model_copy(update=updates)
            self._roles[role_id] = updated
            self._persist_locked()
            return updated

    def delete_role(self, role_id: str) -> None:
        with self._lock:
            role = self._roles.get(role_id)
            if role is None:
                raise ValueError(f"unknown role: {role_id}")
            if role.metadata.get("built_in"):
                raise ValueError(f"cannot delete built-in role: {role_id}")
            self._roles.pop(role_id, None)
            self._records.pop(role_id, None)
            self._persist_locked()

    def list_roles(self) -> list[RoleProfile]:
        with self._lock:
            return list(self._roles.values())

    def get_role(self, role_id: str) -> RoleProfile | None:
        with self._lock:
            return self._roles.get(role_id)

    def add_memory(
        self,
        *,
        role_id: str,
        kind: MemoryKind,
        content: str,
        source: str = "manual",
        agent_id: str | None = None,
        confidence: float = 1.0,
        tags: list[str] | None = None,
        metadata: dict | None = None,
    ) -> MemoryRecord:
        normalized_content = self._clean_content(content)
        if not normalized_content:
            raise ValueError("memory content cannot be empty")

        with self._lock:
            if role_id not in self._roles:
                raise ValueError(f"unknown role: {role_id}")

            duplicate = self._find_duplicate(
                role_id=role_id,
                kind=kind,
                content=normalized_content,
                agent_id=agent_id,
            )
            if duplicate is not None:
                duplicate.updated_at = utc_now()
                duplicate.confidence = max(duplicate.confidence, confidence)
                duplicate.tags = sorted(set(duplicate.tags).union(tags or []))
                duplicate.metadata.update(metadata or {})
                self._persist_locked()
                return duplicate

            now = utc_now()
            record = MemoryRecord(
                id=f"mem_{uuid4().hex}",
                role_id=role_id,
                kind=kind,
                content=normalized_content,
                source=source,
                agent_id=agent_id,
                confidence=confidence,
                tags=tags or [],
                created_at=now,
                updated_at=now,
                metadata=metadata or {},
            )
            self._records[role_id].append(record)
            self._truncate(role_id)
            self._persist_locked()
            return record

    def list_memories(
        self,
        *,
        role_id: str,
        kind: MemoryKind | None = None,
        agent_id: str | None = None,
        include_shared: bool = True,
        limit: int | None = None,
    ) -> list[MemoryRecord]:
        with self._lock:
            records = list(self._records.get(role_id, []))

        if kind is not None:
            records = [record for record in records if record.kind == kind]
        if agent_id is not None:
            records = [
                record
                for record in records
                if record.agent_id == agent_id
                or (include_shared and record.agent_id is None)
            ]
        records.sort(key=lambda record: record.updated_at, reverse=True)
        if limit is not None:
            return records[:limit]
        return records

    def delete_memory(self, *, role_id: str, memory_id: str) -> None:
        with self._lock:
            if role_id not in self._roles:
                raise ValueError(f"unknown role: {role_id}")

            records = self._records.get(role_id, [])
            next_records = [
                record for record in records if record.id != memory_id
            ]
            if len(next_records) == len(records):
                raise ValueError(f"unknown memory: {memory_id}")

            self._records[role_id] = next_records
            self._persist_locked()

    def get_context(
        self,
        *,
        role_id: str,
        agent_id: str | None = None,
    ) -> MemoryContext | None:
        role = self.get_role(role_id)
        if role is None:
            return None
        persona_memories = self.list_memories(
            role_id=role_id,
            kind="persona",
            agent_id=agent_id,
            limit=self._max_context_records,
        )
        long_term_memories = self.list_memories(
            role_id=role_id,
            kind="long_term",
            agent_id=agent_id,
            limit=self._max_context_records,
        )
        context = MemoryContext(
            role=role,
            persona_memories=persona_memories,
            long_term_memories=long_term_memories,
        )
        context.rendered = self.render_context(context)
        return context

    def render_context(self, context: MemoryContext) -> str:
        role = context.role
        lines = [
            "当前角色上下文：",
            f"- 角色 ID：{role.id}",
            f"- 角色名称：{role.name}",
        ]
        if role.description:
            lines.append(f"- 角色描述：{role.description}")
        if role.base_persona:
            lines.extend(["", "基础人设：", role.base_persona])
        if role.instructions:
            lines.append("")
            lines.append("角色指令：")
            lines.extend(f"- {item}" for item in role.instructions)
        if context.persona_memories:
            lines.append("")
            lines.append("人设记忆：")
            lines.extend(f"- {record.content}" for record in context.persona_memories)
        if context.long_term_memories:
            lines.append("")
            lines.append("长期记忆：")
            lines.extend(f"- {record.content}" for record in context.long_term_memories)
        return "\n".join(lines)

    def _find_duplicate(
        self,
        *,
        role_id: str,
        kind: MemoryKind,
        content: str,
        agent_id: str | None,
    ) -> MemoryRecord | None:
        normalized = self._normalize_for_dedupe(content)
        for record in self._records.get(role_id, []):
            if record.kind != kind or record.agent_id != agent_id:
                continue
            if self._normalize_for_dedupe(record.content) == normalized:
                return record
        return None

    def _truncate(self, role_id: str) -> None:
        records = self._records[role_id]
        if len(records) <= self._max_records_per_role:
            return
        records.sort(key=lambda record: record.updated_at, reverse=True)
        self._records[role_id] = records[: self._max_records_per_role]

    def _load(self) -> None:
        if self._storage_path is None or not self._storage_path.exists():
            return

        try:
            payload = json.loads(self._storage_path.read_text(encoding="utf-8"))
            for role_data in payload.get("roles", []):
                role = RoleProfile.model_validate(role_data)
                self._roles[role.id] = role

            loaded_records: dict[str, list[MemoryRecord]] = defaultdict(list)
            for record_data in payload.get("records", []):
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
            "roles": [
                role.model_dump(mode="json")
                for role in self._roles.values()
            ],
            "records": [
                record.model_dump(mode="json")
                for record in records
            ],
        }
        tmp_path = self._storage_path.with_suffix(self._storage_path.suffix + ".tmp")
        tmp_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        tmp_path.replace(self._storage_path)

    @staticmethod
    def _clean_content(content: str) -> str:
        return content.strip().strip("。.!? \n\t")

    @staticmethod
    def _normalize_for_dedupe(content: str) -> str:
        content = content.lower().strip()
        content = re.sub(r"\s+", " ", content)
        return content.strip("。.!? ")

    @staticmethod
    def _clean_role_id(value: str) -> str:
        value = value.strip().lower()
        value = re.sub(r"[^a-z0-9_\-\u4e00-\u9fff]+", "_", value)
        value = re.sub(r"_+", "_", value)
        return value.strip("_-")
