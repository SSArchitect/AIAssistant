"""Unit tests for conversation memory."""
import pytest

from agent.memory.conversation import ConversationMemory
from agent.memory.hooks import HeuristicMemoryHook
from agent.memory.role_store import RoleMemoryStore
from agent.llm.base import LLMMessage
from agent.schemas.memory import RoleProfile


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
        assert "人设记忆：" in context.rendered
        assert "长期记忆：" in context.rendered

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
        assert candidates[0].kind == "persona"

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
