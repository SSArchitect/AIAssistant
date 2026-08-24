import asyncio

import pytest

from agent.schemas.chat import ChatRequest
from agent.skills.base import Skill, SkillMetadata, SkillResult
from agent.skills.governance import ToolGovernance
from agent.trace import TraceStore


class GovernedSkill(Skill):
    def __init__(
        self,
        *,
        name: str = "dangerous",
        default_policy: str = "confirm",
        max_calls: int = 2,
        timeout_seconds: float = 1,
        delay: float = 0,
    ):
        self.name = name
        self.default_policy = default_policy
        self.max_calls = max_calls
        self.timeout_seconds = timeout_seconds
        self.delay = delay
        self.calls = 0

    def metadata(self) -> SkillMetadata:
        return SkillMetadata(
            name=self.name,
            description="test",
            risk_level="high",
            access="destructive",
            default_policy=self.default_policy,
            max_calls_per_run=self.max_calls,
            timeout_seconds=self.timeout_seconds,
            sensitive_arguments=["secret"],
            confirmation_keywords=["删除待办"],
        )

    async def execute(self, **kwargs) -> SkillResult:
        self.calls += 1
        if self.delay:
            await asyncio.sleep(self.delay)
        return SkillResult(success=True, data=kwargs)


def request(message: str, *, policies=None) -> ChatRequest:
    return ChatRequest(
        conversation_id="conv-1",
        user_id="alice",
        message=message,
        agent_id="super_chat",
        tool_policies=policies or {},
    )


def governance_run():
    store = TraceStore()
    run = store.start_run(
        conversation_id="conv-1",
        user_id="alice",
        input_text="test",
        agent_id="super_chat",
        runtime="self",
    )
    return ToolGovernance(store), store, run.run_id


@pytest.mark.asyncio
async def test_confirm_policy_requires_explicit_current_turn_intent():
    governance, store, run_id = governance_run()
    skill = GovernedSkill()

    blocked = await governance.execute(
        skill=skill,
        request=request("看看这条待办"),
        run_id=run_id,
        arguments={"todo_id": "todo-1", "secret": "private"},
    )
    allowed = await governance.execute(
        skill=skill,
        request=request("删除待办 todo-1"),
        run_id=run_id,
        arguments={"todo_id": "todo-1", "secret": "private"},
    )

    assert blocked.success is False
    assert blocked.data["governance"]["reason"] == "explicit_confirmation_required"
    assert allowed.success is True
    assert skill.calls == 1
    governance_events = [
        event for event in store.get_run(run_id).events
        if event.type.startswith("tool.governance.")
    ]
    assert governance_events[-1].payload["arguments"]["secret"] == "<redacted>"


@pytest.mark.asyncio
async def test_pending_approval_groups_calls_and_executes_exact_arguments_once():
    governance, store, run_id = governance_run()
    skill = GovernedSkill(max_calls=3)

    first = await governance.execute(
        skill=skill,
        request=request("看看这些待办"),
        run_id=run_id,
        arguments={"todo_id": "todo-1", "secret": "first"},
        step_id="call-1",
    )
    second = await governance.execute(
        skill=skill,
        request=request("看看这些待办"),
        run_id=run_id,
        arguments={"todo_id": "todo-2", "secret": "second"},
        step_id="call-2",
    )

    approval_id = first.data["governance"]["approval_id"]
    assert approval_id == second.data["governance"]["approval_id"]
    required = [event for event in store.get_run(run_id).events if event.type == "approval.required"]
    assert required[-1].payload["request_count"] == 2
    assert required[-1].payload["operations"][0]["arguments"]["secret"] == "<redacted>"
    assert governance.seal_run_approvals(run_id) == 1
    waiter = asyncio.create_task(governance.wait_for_run_approvals(run_id))

    resolution = await governance.resolve_approval(
        approval_id,
        user_id="alice",
        decision="allow_once",
    )
    resumed = await waiter

    assert resolution["status"] == "approved"
    assert resolution["succeeded_count"] == 2
    assert set(resumed) == {"call-1", "call-2"}
    assert skill.calls == 2
    assert store.get_run(run_id).skills_used == ["dangerous"]
    assert any(event.type == "approval.resolved" for event in store.get_run(run_id).events)

    with pytest.raises(RuntimeError, match="already been resolved"):
        await governance.resolve_approval(
            approval_id,
            user_id="alice",
            decision="allow_once",
        )


@pytest.mark.asyncio
async def test_pending_approval_rejects_wrong_user_and_supports_deny():
    governance, _, run_id = governance_run()
    skill = GovernedSkill()
    blocked = await governance.execute(
        skill=skill,
        request=request("看看这条待办"),
        run_id=run_id,
        arguments={"todo_id": "todo-1"},
    )
    approval_id = blocked.data["governance"]["approval_id"]
    governance.seal_run_approvals(run_id)

    with pytest.raises(PermissionError):
        await governance.resolve_approval(
            approval_id,
            user_id="mallory",
            decision="allow_once",
        )

    resolution = await governance.resolve_approval(
        approval_id,
        user_id="alice",
        decision="deny",
    )
    assert resolution["status"] == "denied"
    assert skill.calls == 0


@pytest.mark.asyncio
async def test_conversation_approval_resumes_waiter_and_only_grants_same_conversation():
    governance, store, run_id = governance_run()
    skill = GovernedSkill(max_calls=3)
    blocked = await governance.execute(
        skill=skill,
        request=request("看看这条待办"),
        run_id=run_id,
        arguments={"todo_id": "todo-1"},
        step_id="call-1",
    )
    approval_id = blocked.data["governance"]["approval_id"]
    assert governance.seal_run_approvals(run_id) == 1

    waiter = asyncio.create_task(governance.wait_for_run_approvals(run_id))
    await asyncio.sleep(0)
    resolution = await governance.resolve_approval(
        approval_id,
        user_id="alice",
        decision="allow_conversation",
    )
    resumed = await waiter

    assert resolution["decision"] == "allow_conversation"
    assert resumed["call-1"].success is True
    assert skill.calls == 1

    same_conversation_run = store.start_run(
        conversation_id="conv-1",
        user_id="alice",
        input_text="same conversation",
        agent_id="super_chat",
        runtime="self",
    )
    same_conversation = await governance.execute(
        skill=skill,
        request=request("看看另一条待办"),
        run_id=same_conversation_run.run_id,
        arguments={"todo_id": "todo-2"},
    )
    assert same_conversation.success is True

    other_conversation_run = store.start_run(
        conversation_id="conv-2",
        user_id="alice",
        input_text="other conversation",
        agent_id="super_chat",
        runtime="self",
    )
    other_conversation = await governance.execute(
        skill=skill,
        request=ChatRequest(
            conversation_id="conv-2",
            user_id="alice",
            message="看看另一条待办",
            agent_id="super_chat",
        ),
        run_id=other_conversation_run.run_id,
        arguments={"todo_id": "todo-3"},
    )
    assert other_conversation.success is False
    assert other_conversation.error_code == "explicit_confirmation_required"


@pytest.mark.asyncio
async def test_user_deny_policy_blocks_trusted_workflow():
    governance, _, run_id = governance_run()
    skill = GovernedSkill(default_policy="auto")

    result = await governance.execute(
        skill=skill,
        request=request("删除待办 todo-1", policies={"dangerous": "deny"}),
        run_id=run_id,
        arguments={"todo_id": "todo-1"},
        trusted=True,
    )

    assert result.success is False
    assert result.data["governance"]["reason"] == "policy_denied"
    assert skill.calls == 0


@pytest.mark.asyncio
async def test_run_call_limit_is_enforced():
    governance, _, run_id = governance_run()
    skill = GovernedSkill(default_policy="auto", max_calls=1)

    first = await governance.execute(
        skill=skill,
        request=request("run"),
        run_id=run_id,
        arguments={},
    )
    second = await governance.execute(
        skill=skill,
        request=request("run"),
        run_id=run_id,
        arguments={},
    )

    assert first.success is True
    assert second.success is False
    assert second.data["governance"]["reason"] == "run_call_limit_exceeded"
    assert skill.calls == 1


@pytest.mark.asyncio
async def test_tool_timeout_returns_governance_error():
    governance, store, run_id = governance_run()
    skill = GovernedSkill(
        default_policy="auto",
        timeout_seconds=0.01,
        delay=0.05,
    )

    result = await governance.execute(
        skill=skill,
        request=request("run"),
        run_id=run_id,
        arguments={},
    )

    assert result.success is False
    assert "timed out" in result.error
    assert any(event.type == "tool.governance.timeout" for event in store.get_run(run_id).events)
