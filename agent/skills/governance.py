from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

from agent.schemas.chat import ChatRequest
from agent.skills.base import Skill, SkillResult
from agent.trace import TraceStore


TOOL_POLICIES = {"auto", "confirm", "deny"}
_ACTION_KEYWORDS = (
    "删除",
    "删掉",
    "移除",
    "分享",
    "共享",
    "公开",
    "发布",
    "归档",
    "收藏",
    "保存网页",
    "保存链接",
    "delete",
    "remove",
    "share",
    "publish",
    "archive",
)
_TARGET_ARGUMENTS = (
    "item_id",
    "todo_id",
    "path",
    "url",
    "name",
)
_TRUSTED_WORKFLOW_CALL_LIMITS = {
    "search": 48,
}


@dataclass(frozen=True)
class ToolGovernanceDecision:
    allowed: bool
    tool_name: str
    policy: str
    reason: str
    call_count: int
    max_calls: int

    def as_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "tool_name": self.tool_name,
            "policy": self.policy,
            "reason": self.reason,
            "call_count": self.call_count,
            "max_calls": self.max_calls,
        }


class ToolGovernance:
    """Authorize, limit, time-bound, and audit tool executions."""

    def __init__(self, trace_store: TraceStore):
        self.trace_store = trace_store

    def authorize(
        self,
        *,
        skill: Skill,
        request: ChatRequest,
        run_id: str,
        arguments: dict[str, Any],
        trusted: bool = False,
        step_id: str | None = None,
    ) -> ToolGovernanceDecision:
        meta = skill.metadata()
        configured_policy = str((request.tool_policies or {}).get(meta.name) or "").strip().lower()
        policy = configured_policy if configured_policy in TOOL_POLICIES else meta.default_policy
        call_count = self._allowed_call_count(run_id, meta.name)
        max_calls = max(
            meta.max_calls_per_run,
            _TRUSTED_WORKFLOW_CALL_LIMITS.get(meta.name, 0) if trusted else 0,
        )

        allowed = True
        reason = "policy_auto"
        if policy == "deny":
            allowed = False
            reason = "policy_denied"
        elif call_count >= max_calls:
            allowed = False
            reason = "run_call_limit_exceeded"
        elif policy == "confirm":
            if trusted:
                reason = "trusted_workflow_confirmation"
            elif self._has_explicit_confirmation(
                request.message,
                arguments,
                meta.confirmation_keywords,
            ):
                reason = "explicit_current_turn_confirmation"
            else:
                allowed = False
                reason = "explicit_confirmation_required"

        decision = ToolGovernanceDecision(
            allowed=allowed,
            tool_name=meta.name,
            policy=policy,
            reason=reason,
            call_count=call_count + (1 if allowed else 0),
            max_calls=max_calls,
        )
        self.trace_store.append_event(
            run_id,
            type="tool.governance.allowed" if allowed else "tool.governance.blocked",
            status="completed" if allowed else "error",
            title=f"Tool governance {'allowed' if allowed else 'blocked'} {meta.name}",
            step_id=step_id,
            payload={
                **decision.as_dict(),
                "risk_level": meta.risk_level,
                "access": meta.access,
                "trusted_workflow": trusted,
                "arguments": self.redact_arguments(skill, arguments),
            },
        )
        return decision

    async def execute(
        self,
        *,
        skill: Skill,
        request: ChatRequest,
        run_id: str,
        arguments: dict[str, Any],
        trusted: bool = False,
        step_id: str | None = None,
    ) -> SkillResult:
        decision = self.authorize(
            skill=skill,
            request=request,
            run_id=run_id,
            arguments=arguments,
            trusted=trusted,
            step_id=step_id,
        )
        if not decision.allowed:
            return self.blocked_result(decision)

        timeout_seconds = skill.metadata().timeout_seconds
        try:
            return await asyncio.wait_for(
                skill.execute(**arguments),
                timeout=timeout_seconds,
            )
        except (TimeoutError, asyncio.TimeoutError):
            self.trace_store.append_event(
                run_id,
                type="tool.governance.timeout",
                status="error",
                title=f"Tool timed out {decision.tool_name}",
                step_id=step_id,
                payload={
                    **decision.as_dict(),
                    "timeout_seconds": timeout_seconds,
                },
            )
            return SkillResult(
                success=False,
                error=f"Tool timed out after {timeout_seconds:g}s: {decision.tool_name}",
                data={
                    "governance": {
                        **decision.as_dict(),
                        "timeout_seconds": timeout_seconds,
                    }
                },
            )

    @staticmethod
    def blocked_result(decision: ToolGovernanceDecision) -> SkillResult:
        if decision.reason == "explicit_confirmation_required":
            detail = (
                "当前消息需要明确说明要执行这个高风险动作；"
                "也可以在工具管理中把该工具策略改为 auto。"
            )
        elif decision.reason == "run_call_limit_exceeded":
            detail = f"本次运行已达到调用上限 {decision.max_calls}。"
        else:
            detail = "该工具已被当前帐号策略禁止。"
        return SkillResult(
            success=False,
            error=f"Tool governance blocked {decision.tool_name}: {detail}",
            data={"governance": decision.as_dict()},
        )

    @staticmethod
    def redact_arguments(skill: Skill, arguments: dict[str, Any]) -> dict[str, Any]:
        sensitive = {name.strip() for name in skill.metadata().sensitive_arguments if name.strip()}
        return {
            key: "<redacted>" if key in sensitive else value
            for key, value in arguments.items()
            if not key.startswith("_")
        }

    def record_timeout(
        self,
        *,
        decision: ToolGovernanceDecision,
        run_id: str,
        timeout_seconds: float,
        step_id: str | None = None,
    ) -> SkillResult:
        self.trace_store.append_event(
            run_id,
            type="tool.governance.timeout",
            status="error",
            title=f"Tool timed out {decision.tool_name}",
            step_id=step_id,
            payload={
                **decision.as_dict(),
                "timeout_seconds": timeout_seconds,
            },
        )
        return SkillResult(
            success=False,
            error=f"Tool timed out after {timeout_seconds:g}s: {decision.tool_name}",
            data={
                "governance": {
                    **decision.as_dict(),
                    "timeout_seconds": timeout_seconds,
                }
            },
        )

    def _allowed_call_count(self, run_id: str, tool_name: str) -> int:
        run = self.trace_store.get_run(run_id)
        if run is None:
            return 0
        return sum(
            1
            for event in run.events
            if event.type == "tool.governance.allowed"
            and str(event.payload.get("tool_name") or "") == tool_name
        )

    @staticmethod
    def _has_explicit_confirmation(
        message: str,
        arguments: dict[str, Any],
        confirmation_keywords: list[str],
    ) -> bool:
        normalized_message = " ".join(str(message or "").casefold().split())
        if not normalized_message:
            return False
        if any(
            " ".join(str(keyword or "").casefold().split()) in normalized_message
            for keyword in confirmation_keywords
            if str(keyword or "").strip()
        ):
            return True
        if not any(keyword in normalized_message for keyword in _ACTION_KEYWORDS):
            return False
        for argument_name in _TARGET_ARGUMENTS:
            value = " ".join(str(arguments.get(argument_name) or "").casefold().split())
            if len(value) >= 3 and value in normalized_message:
                return True
        return False
