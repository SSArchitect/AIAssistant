"""Unit tests for conversation memory."""
import json

import pytest

from agent.memory.conversation import ConversationMemory
from agent.memory.hooks import HeuristicMemoryHook
from agent.memory.role_store import RoleMemoryStore
from agent.llm.base import LLMMessage
from agent.schemas.memory import MemoryUpdateRequest, RoleCreateRequest, RoleProfile, RoleUpdateRequest


class TestConversationMemory:
    def test_empty_history(self):
        mem = ConversationMemory()
        assert mem.get("conv1") == []

    def test_add_and_get(self):
        mem = ConversationMemory()
        msg = LLMMessage(role="user", content="hello")
        mem.add("conv1", msg)

        history = mem.get("conv1")
        assert len(history) == 1
        assert history[0].content == "hello"

    def test_separate_conversations(self):
        mem = ConversationMemory()
        mem.add("conv1", LLMMessage(role="user", content="msg1"))
        mem.add("conv2", LLMMessage(role="user", content="msg2"))

        assert len(mem.get("conv1")) == 1
        assert len(mem.get("conv2")) == 1
        assert mem.get("conv1")[0].content == "msg1"
        assert mem.get("conv2")[0].content == "msg2"

    def test_add_many(self):
        mem = ConversationMemory()
        messages = [
            LLMMessage(role="user", content="hello"),
            LLMMessage(role="assistant", content="hi there"),
        ]
        mem.add_many("conv1", messages)

        history = mem.get("conv1")
        assert len(history) == 2
        assert history[0].role == "user"
        assert history[1].role == "assistant"

    def test_clear(self):
        mem = ConversationMemory()
        mem.add("conv1", LLMMessage(role="user", content="hello"))
        mem.clear("conv1")
        assert mem.get("conv1") == []

    def test_summary_context(self):
        mem = ConversationMemory()
        mem.add("conv1", LLMMessage(role="user", content="hello"))
        mem.set_summary("conv1", "User is designing memory.")

        context = mem.get_context("conv1")

        assert context.summary == "User is designing memory."
        assert context.total_messages == 1
        assert context.messages[0].content == "hello"

    def test_truncation(self):
        mem = ConversationMemory(max_messages=5)
        for i in range(10):
            mem.add("conv1", LLMMessage(role="user", content=f"msg{i}"))

        history = mem.get("conv1")
        assert len(history) == 5
        # Should keep the last 5
        assert history[0].content == "msg5"
        assert history[-1].content == "msg9"

    def test_get_returns_copy(self):
        """Modifying the returned list should not affect internal state."""
        mem = ConversationMemory()
        mem.add("conv1", LLMMessage(role="user", content="hello"))

        history = mem.get("conv1")
        history.clear()

        # Original should still have the message
        assert len(mem.get("conv1")) == 1


class TestRoleMemoryStore:
    def test_role_memories_are_isolated(self):
        store = RoleMemoryStore(
            roles=[
                RoleProfile(id="coach", name="Coach"),
                RoleProfile(id="planner", name="Planner"),
            ]
        )

        store.add_memory(role_id="coach", kind="long_term", content="User likes concise replies")
        store.add_memory(role_id="planner", kind="long_term", content="User likes detailed plans")

        coach_context = store.get_context(role_id="coach", agent_id="general_assistant")
        planner_context = store.get_context(role_id="planner", agent_id="general_assistant")

        assert coach_context is not None
        assert planner_context is not None
        assert "concise replies" in coach_context.rendered
        assert "detailed plans" not in coach_context.rendered
        assert "detailed plans" in planner_context.rendered

    def test_persona_and_long_term_memory_render_separately(self):
        store = RoleMemoryStore(roles=[RoleProfile(id="mentor", name="Mentor")])

        store.add_memory(role_id="mentor", kind="persona", content="Use Socratic questions")
        store.add_memory(role_id="mentor", kind="long_term", content="User is preparing interviews")

        context = store.get_context(role_id="mentor", agent_id="general_assistant")

        assert context is not None
        assert context.persona_memories[0].content == "Use Socratic questions"
        assert context.long_term_memories[0].content == "User is preparing interviews"
        assert "角色记忆：" in context.rendered
        assert "用户更新的角色记忆：" in context.rendered
        assert "长期记忆：" in context.rendered
        assert context.rendered.index("长期记忆：") < context.rendered.index("角色记忆：")

    def test_context_filters_unrelated_long_term_memory_by_query(self):
        store = RoleMemoryStore()
        game_memory = store.add_memory(
            role_id="default",
            kind="long_term",
            content="用户喜欢玩游戏，对游戏推荐感兴趣",
            tags=["游戏"],
        )
        store.add_memory(
            role_id="default",
            kind="role",
            content="称呼用户为老板",
        )

        unrelated = store.get_context(role_id="default", query="歪")
        related = store.get_context(role_id="default", query="推荐几个好玩的游戏")

        assert unrelated is not None
        assert related is not None
        assert unrelated.long_term_memories == []
        assert "用户喜欢玩游戏" not in unrelated.rendered
        assert [record.id for record in related.long_term_memories] == [game_memory.id]

    def test_role_preferences_render_in_context(self):
        store = RoleMemoryStore(
            roles=[
                RoleProfile(
                    id="operator",
                    name="Operator",
                    metadata={"preferences": ["Answer with the conclusion first"]},
                )
            ]
        )

        context = store.get_context(role_id="operator", agent_id="general_assistant")

        assert context is not None
        assert "习惯/偏好：" in context.rendered
        assert "Answer with the conclusion first" in context.rendered

    def test_duplicate_memory_updates_existing_record(self):
        store = RoleMemoryStore()

        first = store.add_memory(
            role_id="default",
            kind="long_term",
            content="User likes terse answers.",
            tags=["first"],
        )
        second = store.add_memory(
            role_id="default",
            kind="long_term",
            content="user likes terse answers",
            confidence=0.9,
            tags=["second"],
        )

        memories = store.list_memories(role_id="default")
        assert first.id == second.id
        assert len(memories) == 1
        assert memories[0].confidence == 1.0
        assert memories[0].tags == ["first", "second"]

    def test_similar_memory_updates_existing_record(self):
        store = RoleMemoryStore()

        first = store.add_memory(
            role_id="default",
            kind="long_term",
            content="用户喜欢玩游戏，对游戏推荐感兴趣",
            tags=["游戏"],
        )
        second = store.add_memory(
            role_id="default",
            kind="long_term",
            content="用户对游戏推荐感兴趣，也喜欢玩游戏",
            confidence=0.8,
            tags=["推荐"],
        )

        memories = store.list_memories(role_id="default")
        assert first.id == second.id
        assert len(memories) == 1
        assert memories[0].tags == ["推荐", "游戏"]
        assert memories[0].version == 2

    def test_role_memories_are_scoped_by_user_id(self):
        store = RoleMemoryStore()
        store.add_memory(
            role_id="default",
            user_id="a",
            kind="long_term",
            content="User A likes terse answers.",
        )
        store.add_memory(
            role_id="default",
            user_id="b",
            kind="long_term",
            content="User B likes detailed answers.",
        )

        context_a = store.get_context(role_id="default", user_id="a")
        context_b = store.get_context(role_id="default", user_id="b")

        assert context_a is not None
        assert context_b is not None
        assert "User A likes terse answers" in context_a.rendered
        assert "User B likes detailed answers" not in context_a.rendered
        assert "User B likes detailed answers" in context_b.rendered

    def test_custom_roles_are_visible_only_to_owner(self):
        store = RoleMemoryStore()

        role_a = store.create_role(
            RoleCreateRequest(
                user_id="account-a",
                id="private_helper",
                name="Account A Helper",
            )
        )
        role_b = store.create_role(
            RoleCreateRequest(
                user_id="account-b",
                id="private_helper",
                name="Account B Helper",
            )
        )

        assert role_a.metadata["owner_user_id"] == "account-a"
        assert role_b.metadata["owner_user_id"] == "account-b"
        roles_a = {role.id: role for role in store.list_roles(user_id="account-a")}
        roles_b = {role.id: role for role in store.list_roles(user_id="account-b")}
        assert roles_a["private_helper"].name == "Account A Helper"
        assert roles_b["private_helper"].name == "Account B Helper"

        store.update_role(
            "private_helper",
            RoleUpdateRequest(user_id="account-a", name="Account A Updated"),
        )
        assert store.get_role("private_helper", user_id="account-a").name == "Account A Updated"
        assert store.get_role("private_helper", user_id="account-b").name == "Account B Helper"

        store.delete_role("private_helper", user_id="account-a")
        assert store.get_role("private_helper", user_id="account-a") is None
        assert store.get_role("private_helper", user_id="account-b") is not None

    def test_persists_memory_records_to_json(self, tmp_path):
        storage_path = tmp_path / "agent_memory.json"
        store = RoleMemoryStore(storage_path=storage_path)
        written = store.add_memory(
            role_id="default",
            kind="long_term",
            content="User prefers durable memory",
        )

        restored = RoleMemoryStore(storage_path=storage_path)
        memories = restored.list_memories(role_id="default", kind="long_term")

        assert storage_path.exists()
        assert len(memories) == 1
        assert memories[0].id == written.id
        assert memories[0].content == "User prefers durable memory"

    def test_archived_memories_are_listed_but_not_injected(self):
        store = RoleMemoryStore()
        active = store.add_memory(
            role_id="default",
            kind="long_term",
            content="User likes active memory",
        )
        archived = store.add_memory(
            role_id="default",
            kind="long_term",
            content="User likes archived memory",
            status="archived",
        )

        context = store.get_context(role_id="default")
        all_memories = store.list_memories(role_id="default", include_inactive=True)

        assert context is not None
        assert [record.id for record in context.long_term_memories] == [active.id]
        assert "active memory" in context.rendered
        assert "archived memory" not in context.rendered
        assert {record.id for record in all_memories} == {active.id, archived.id}

    def test_update_memory_lifecycle_fields(self):
        store = RoleMemoryStore()
        memory = store.add_memory(
            role_id="default",
            kind="long_term",
            content="Original memory",
            source_trace={"run_id": "run_old"},
        )

        updated = store.update_memory(
            role_id="default",
            memory_id=memory.id,
            request=MemoryUpdateRequest(
                content="Updated memory",
                status="archived",
                review_state="reviewed",
                review_notes="Reviewed by developer",
                source_trace={"conversation_id": "conv_1"},
            ),
        )

        assert updated.content == "Updated memory"
        assert updated.status == "archived"
        assert updated.review_state == "reviewed"
        assert updated.review_notes == "Reviewed by developer"
        assert updated.version == 2
        assert updated.source_trace["run_id"] == "run_old"
        assert updated.source_trace["conversation_id"] == "conv_1"

    def test_default_role_sync_prunes_retired_builtins_and_promotes_chuyi(self, tmp_path):
        storage_path = tmp_path / "agent_memory.json"
        retired_builtin = RoleProfile(
            id="research_analyst",
            name="Research Analyst",
            metadata={"built_in": True},
        )
        old_chuyi = RoleProfile(
            id="初一",
            name="初一",
            description="一个赛博小书生",
            base_persona="一个赛博小书生，上通天文，下懂地理，技巧可爱",
            metadata={"built_in": False},
        )
        custom = RoleProfile(
            id="custom_writer",
            name="Custom Writer",
            metadata={"built_in": False},
        )
        storage_path.write_text(
            json.dumps(
                {
                    "roles": [
                        retired_builtin.model_dump(mode="json"),
                        old_chuyi.model_dump(mode="json"),
                        custom.model_dump(mode="json"),
                    ],
                    "records": [],
                },
                ensure_ascii=False,
            ),
            encoding="utf-8",
        )

        store = RoleMemoryStore(storage_path=storage_path)

        roles = {role.id: role for role in store.list_roles()}
        assert set(roles) == {
            "default",
            "work_partner",
            "learning_coach",
            "初一",
            "custom_writer",
        }
        assert roles["初一"].metadata["built_in"] is True
        assert roles["初一"].metadata["localized"]["en"]["name"] == "Chuyi"
        assert roles["custom_writer"].metadata["built_in"] is False


class TestHeuristicMemoryHook:
    @pytest.mark.asyncio
    async def test_extracts_explicit_long_term_memory(self):
        hook = HeuristicMemoryHook()

        candidates = await hook.review_turn(
            role=RoleProfile(id="default", name="Default"),
            agent_id="general_assistant",
            conversation_id="conv1",
            user_message="请记住：我的名字是安安",
            assistant_message="好的",
            new_messages=[],
        )

        assert len(candidates) == 1
        assert candidates[0].kind == "long_term"
        assert candidates[0].content == "我的名字是安安"
        assert candidates[0].reason == "explicit_remember_request"

    @pytest.mark.asyncio
    async def test_extracts_explicit_persona_memory(self):
        hook = HeuristicMemoryHook()

        candidates = await hook.review_turn(
            role=RoleProfile(id="default", name="Default"),
            agent_id="general_assistant",
            conversation_id="conv1",
            user_message="请记住：以后你要用苏格拉底式提问",
            assistant_message="好的",
            new_messages=[],
        )

        assert len(candidates) == 1
        assert candidates[0].kind == "role"

    @pytest.mark.asyncio
    async def test_ignores_low_signal_followup(self):
        hook = HeuristicMemoryHook()

        candidates = await hook.review_turn(
            role=RoleProfile(id="default", name="Default"),
            agent_id="general_assistant",
            conversation_id="conv1",
            user_message="Remember?",
            assistant_message="Yes",
            new_messages=[],
        )

        assert candidates == []

    @pytest.mark.asyncio
    async def test_ignores_normal_questions_with_you(self):
        hook = HeuristicMemoryHook()

        candidates = await hook.review_turn(
            role=RoleProfile(id="default", name="Default"),
            agent_id="general_assistant",
            conversation_id="conv1",
            user_message="你觉得这个方案怎么样？",
            assistant_message="还不错",
            new_messages=[],
        )

        assert candidates == []

    @pytest.mark.asyncio
    async def test_ignores_question_as_user_fact(self):
        hook = HeuristicMemoryHook()

        candidates = await hook.review_turn(
            role=RoleProfile(id="default", name="Default"),
            agent_id="general_assistant",
            conversation_id="conv1",
            user_message="我的问题是：怎么设计 memory？",
            assistant_message="可以分层设计",
            new_messages=[],
        )

        assert candidates == []

    @pytest.mark.asyncio
    async def test_ignores_negated_remember_request(self):
        hook = HeuristicMemoryHook()

        candidates = await hook.review_turn(
            role=RoleProfile(id="default", name="Default"),
            agent_id="general_assistant",
            conversation_id="conv1",
            user_message="不要记住：这只是临时测试",
            assistant_message="好的",
            new_messages=[],
        )

        assert candidates == []
