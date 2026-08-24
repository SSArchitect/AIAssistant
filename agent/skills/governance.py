from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any
from uuid import uuid4

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
    approval_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload = {
            "allowed": self.allowed,
            "tool_name": self.tool_name,
            "policy": self.policy,
            "reason": self.reason,
            "call_count": self.call_count,
            "max_calls": self.max_calls,
        }
        if self.approval_id:
            payload["approval_id"] = self.approval_id
        return payload


@dataclass
class PendingToolApprovalItem:
    skill: Skill
    arguments: dict[str, Any]
    step_id: str | None


@dataclass
class PendingToolApproval:
    approval_id: str
    run_id: str
    conversation_id: str
    user_id: str
    tool_name: str
    risk_level: str
    access: str
    created_at: datetime
    expires_at: datetime
    status: str
    items: list[PendingToolApprovalItem]


class ToolGovernance:
    """Authorize, limit, time-bound, and audit tool executions."""

    def __init__(self, trace_store: TraceStore):
        self.trace_store = trace_store
        self._pending_approvals: dict[str, PendingToolApproval] = {}
        self._approval_groups: dict[tuple[str, str], str] = {}
        self._approval_lock = Lock()

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
        pending_count = self._pending_call_count(run_id, meta.name)

        allowed = True
        reason = "policy_auto"
        approval_id: str | None = None
        if policy == "deny":
            allowed = False
            reason = "policy_denied"
        elif call_count + pending_count >= max_calls:
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
                pending = self._register_pending_approval(
                    skill=skill,
                    request=request,
                    run_id=run_id,
                    arguments=arguments,
                    step_id=step_id,
                )
                approval_id = pending.approval_id

        decision = ToolGovernanceDecision(
            allowed=allowed,
            tool_name=meta.name,
            policy=policy,
            reason=reason,
            call_count=call_count + (1 if allowed else 0),
            max_calls=max_calls,
            approval_id=approval_id,
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
        if approval_id:
            self._append_approval_required_event(approval_id)
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
                error_code="tool_timeout",
                retryable=True,
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
                "该操作正在等待用户通过授权卡片确认；"
                "不要要求用户改写或重复发送确认消息。"
            )
        elif decision.reason == "run_call_limit_exceeded":
            detail = f"本次运行已达到调用上限 {decision.max_calls}。"
        else:
            detail = "该工具已被当前帐号策略禁止。"
        return SkillResult(
            success=False,
            error=f"Tool governance blocked {decision.tool_name}: {detail}",
            error_code=decision.reason,
            retryable=False,
            data={"governance": decision.as_dict()},
            display_text=(
                "需要用户授权。请使用聊天消息中的授权卡片。"
                if decision.reason == "explicit_confirmation_required"
                else None
            ),
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
            error_code="tool_timeout",
            retryable=True,
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

    def _pending_call_count(self, run_id: str, tool_name: str) -> int:
        with self._approval_lock:
            approval_id = self._approval_groups.get((run_id, tool_name))
            pending = self._pending_approvals.get(approval_id or "")
            if pending is None or pending.status != "pending":
                return 0
            if pending.expires_at <= datetime.now(timezone.utc):
                return 0
            return len(pending.items)

    def _register_pending_approval(
        self,
        *,
        skill: Skill,
        request: ChatRequest,
        run_id: str,
        arguments: dict[str, Any],
        step_id: str | None,
    ) -> PendingToolApproval:
        meta = skill.metadata()
        now = datetime.now(timezone.utc)
        group_key = (run_id, meta.name)
        with self._approval_lock:
            approval_id = self._approval_groups.get(group_key)
            pending = self._pending_approvals.get(approval_id or "")
            if (
                pending is None
                or pending.status != "pending"
                or pending.expires_at <= now
            ):
                pending = PendingToolApproval(
                    approval_id=f"approval_{uuid4().hex}",
                    run_id=run_id,
                    conversation_id=request.conversation_id,
                    user_id=str(request.user_id or "0"),
                    tool_name=meta.name,
                    risk_level=meta.risk_level,
                    access=meta.access,
                    created_at=now,
                    expires_at=now + timedelta(minutes=15),
                    status="pending",
                    items=[],
                )
                self._pending_approvals[pending.approval_id] = pending
                self._approval_groups[group_key] = pending.approval_id
            if not any(item.step_id == step_id and step_id for item in pending.items):
                pending.items.append(
                    PendingToolApprovalItem(
                        skill=skill,
                        arguments=dict(arguments),
                        step_id=step_id,
                    )
                )
            return pending

    def _append_approval_required_event(self, approval_id: str) -> None:
        with self._approval_lock:
            pending = self._pending_approvals.get(approval_id)
            if pending is None:
                return
            items = list(pending.items)
            payload = {
                "approval_id": pending.approval_id,
                "tool_name": pending.tool_name,
                "policy": "confirm",
                "risk_level": pending.risk_level,
                "access": pending.access,
                "request_count": len(items),
                "operations": [
                    {
                        "step_id": item.step_id,
                        "arguments": self.redact_arguments(item.skill, item.arguments),
                    }
                    for item in items
                ],
                "expires_at": pending.expires_at.isoformat(),
            }
        self.trace_store.append_event(
            pending.run_id,
            type="approval.required",
            status="pending",
            title=f"Approval required for {pending.tool_name}",
            payload=payload,
        )

    async def resolve_approval(
        self,
        approval_id: str,
        *,
        user_id: str,
        decision: str,
    ) -> dict[str, Any]:
        if decision not in {"allow_once", "allow_always", "deny"}:
            raise ValueError("invalid approval decision")
        now = datetime.now(timezone.utc)
        with self._approval_lock:
            pending = self._pending_approvals.get(approval_id)
            if pending is None:
                raise KeyError("approval not found")
            if pending.user_id != str(user_id or "0"):
                raise PermissionError("approval not found")
            if pending.status != "pending":
                raise RuntimeError("approval has already been resolved")
            if pending.expires_at <= now:
                pending.status = "expired"
                raise TimeoutError("approval has expired")
            pending.status = "resolving" if decision != "deny" else "denied"
            items = list(pending.items)

        if decision == "deny":
            with self._approval_lock:
                self._approval_groups.pop((pending.run_id, pending.tool_name), None)
            self.trace_store.append_event(
                pending.run_id,
                type="approval.resolved",
                status="cancelled",
                title=f"Approval denied for {pending.tool_name}",
                payload={
                    "approval_id": approval_id,
                    "tool_name": pending.tool_name,
                    "decision": decision,
                    "request_count": len(items),
                    "succeeded_count": 0,
                    "failed_count": 0,
                },
            )
            return self._approval_resolution_payload(pending, decision, [], "denied")

        results: list[dict[str, Any]] = []
        for item in items:
            meta = item.skill.metadata()
            started_at = datetime.now(timezone.utc)
            self.trace_store.append_event(
                pending.run_id,
                type="tool.started",
                status="running",
                title=f"Tool {pending.tool_name} resumed after approval",
                step_id=item.step_id,
                payload={
                    "name": pending.tool_name,
                    "arguments": self.redact_arguments(item.skill, item.arguments),
                    "approval_id": approval_id,
                    "approval_resume": True,
                },
            )
            try:
                result = await asyncio.wait_for(
                    item.skill.execute(**item.arguments),
                    timeout=meta.timeout_seconds,
                )
            except (TimeoutError, asyncio.TimeoutError):
                result = SkillResult(
                    success=False,
                    error=f"Tool timed out after {meta.timeout_seconds:g}s: {pending.tool_name}",
                    error_code="tool_timeout",
                )
            except Exception as exc:
                result = SkillResult(success=False, error=str(exc), error_code="tool_error")
            duration_ms = max(
                0,
                int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000),
            )
            result_summary = {
                "step_id": item.step_id,
                "success": result.success,
                "display_text": result.display_text or "",
                "error": result.error or "",
                "error_code": result.error_code or "",
            }
            results.append(result_summary)
            self.trace_store.append_event(
                pending.run_id,
                type="tool.completed" if result.success else "tool.failed",
                status="completed" if result.success else "error",
                title=f"Tool {pending.tool_name} {'completed' if result.success else 'failed'} after approval",
                step_id=item.step_id,
                payload={
                    "name": pending.tool_name,
                    "approval_id": approval_id,
                    "approval_resume": True,
                    "result_preview": {
                        "success": result.success,
                        "display_text": result.display_text or "",
                        "error": result.error or "",
                        "error_code": result.error_code or "",
                    },
                },
                duration_ms=duration_ms,
            )
            if result.success:
                self.trace_store.record_skill_use(pending.run_id, pending.tool_name)

        succeeded = sum(1 for result in results if result["success"])
        failed = len(results) - succeeded
        status = "approved" if not failed else "partial" if succeeded else "failed"
        with self._approval_lock:
            pending.status = status
            self._approval_groups.pop((pending.run_id, pending.tool_name), None)
        self.trace_store.append_event(
            pending.run_id,
            type="approval.resolved",
            status="completed" if not failed else "error",
            title=f"Approval resolved for {pending.tool_name}",
            payload={
                "approval_id": approval_id,
                "tool_name": pending.tool_name,
                "decision": decision,
                "request_count": len(items),
                "succeeded_count": succeeded,
                "failed_count": failed,
            },
        )
        return self._approval_resolution_payload(pending, decision, results, status)

    def _approval_resolution_payload(
        self,
        pending: PendingToolApproval,
        decision: str,
        results: list[dict[str, Any]],
        status: str,
    ) -> dict[str, Any]:
        run = self.trace_store.get_run(pending.run_id)
        return {
            "approval_id": pending.approval_id,
            "run_id": pending.run_id,
            "conversation_id": pending.conversation_id,
            "tool_name": pending.tool_name,
            "decision": decision,
            "status": status,
            "request_count": len(pending.items),
            "succeeded_count": sum(1 for result in results if result.get("success")),
            "failed_count": sum(1 for result in results if not result.get("success")),
            "results": results,
            "events": list(run.events) if run is not None else [],
            "skills_used": list(run.skills_used) if run is not None else [],
        }

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
