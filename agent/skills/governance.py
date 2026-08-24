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
    sealed: bool = False


class ToolGovernance:
    """Authorize, limit, time-bound, and audit tool executions."""

    def __init__(self, trace_store: TraceStore):
        self.trace_store = trace_store
        self._pending_approvals: dict[str, PendingToolApproval] = {}
        self._approval_groups: dict[tuple[str, str], str] = {}
        self._approval_events: dict[str, asyncio.Event] = {}
        self._resolved_step_results: dict[tuple[str, str], SkillResult] = {}
        self._conversation_grants: set[tuple[str, str, str]] = set()
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
        grant_key = (
            str(request.user_id or "0"),
            str(request.conversation_id or ""),
            meta.name,
        )
        with self._approval_lock:
            conversation_granted = grant_key in self._conversation_grants
        if configured_policy == "deny":
            policy = "deny"
        elif conversation_granted:
            policy = "auto"
        else:
            policy = configured_policy if configured_policy in TOOL_POLICIES else meta.default_policy
        call_count = self._allowed_call_count(run_id, meta.name)
        max_calls = max(
            meta.max_calls_per_run,
            _TRUSTED_WORKFLOW_CALL_LIMITS.get(meta.name, 0) if trusted else 0,
        )
        pending_count = self._pending_call_count(run_id, meta.name)

        allowed = True
        reason = "conversation_policy_auto" if conversation_granted else "policy_auto"
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
                or pending.sealed
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
            approval_event = self._approval_events.setdefault(run_id, asyncio.Event())
            approval_event.clear()
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
            payload = self._approval_event_payload(pending)
        self.trace_store.append_event(
            pending.run_id,
            type="approval.required",
            status="pending",
            title=f"Approval required for {pending.tool_name}",
            payload=payload,
        )

    def seal_run_approvals(self, run_id: str) -> int:
        """Freeze all approvals collected for a model round and expose their actions."""
        with self._approval_lock:
            approvals = [
                pending
                for pending in self._pending_approvals.values()
                if pending.run_id == run_id and pending.status == "pending"
            ]
            for pending in approvals:
                pending.sealed = True
            payloads = [
                (pending, self._approval_event_payload(pending))
                for pending in approvals
            ]
        for pending, payload in payloads:
            self.trace_store.append_event(
                run_id,
                type="approval.required",
                status="pending",
                title=f"Approval ready for {pending.tool_name}",
                payload={**payload, "ready": True},
            )
        return len(approvals)

    async def wait_for_run_approvals(self, run_id: str) -> dict[str, SkillResult]:
        """Wait until every sealed approval for a run is resolved, denied, or expired."""
        while True:
            with self._approval_lock:
                outstanding = [
                    pending
                    for pending in self._pending_approvals.values()
                    if pending.run_id == run_id
                    and pending.status in {"pending", "resolving"}
                ]
                if not outstanding:
                    results = {
                        step_id: result
                        for (result_run_id, step_id), result in list(self._resolved_step_results.items())
                        if result_run_id == run_id
                    }
                    for step_id in results:
                        self._resolved_step_results.pop((run_id, step_id), None)
                    self._approval_events.pop(run_id, None)
                    return results
                event = self._approval_events.setdefault(run_id, asyncio.Event())
                event.clear()
                pending_expirations = [
                    pending.expires_at
                    for pending in outstanding
                    if pending.status == "pending"
                ]

            timeout_seconds: float | None = None
            if pending_expirations:
                timeout_seconds = max(
                    0.0,
                    (min(pending_expirations) - datetime.now(timezone.utc)).total_seconds(),
                )
            try:
                if timeout_seconds is None:
                    await event.wait()
                else:
                    await asyncio.wait_for(event.wait(), timeout=timeout_seconds)
            except (TimeoutError, asyncio.TimeoutError):
                self._expire_run_approvals(run_id)

    def _approval_event_payload(self, pending: PendingToolApproval) -> dict[str, Any]:
        items = list(pending.items)
        return {
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
            "ready": pending.sealed,
        }

    async def resolve_approval(
        self,
        approval_id: str,
        *,
        user_id: str,
        decision: str,
    ) -> dict[str, Any]:
        if decision == "allow_always":
            decision = "allow_conversation"
        if decision not in {"allow_once", "allow_conversation", "deny"}:
            raise ValueError("invalid approval decision")
        now = datetime.now(timezone.utc)
        expired = False
        with self._approval_lock:
            pending = self._pending_approvals.get(approval_id)
            if pending is None:
                raise KeyError("approval not found")
            if pending.user_id != str(user_id or "0"):
                raise PermissionError("approval not found")
            if pending.status != "pending":
                raise RuntimeError("approval has already been resolved")
            if not pending.sealed:
                raise RuntimeError("approval operations are still being collected")
            if pending.expires_at <= now:
                expired = True
            else:
                pending.status = "resolving" if decision != "deny" else "denied"
            items = list(pending.items)

        if expired:
            self._expire_run_approvals(pending.run_id)
            raise TimeoutError("approval has expired")

        if decision != "deny":
            self.trace_store.append_event(
                pending.run_id,
                type="approval.resolving",
                status="running",
                title=f"Approval resolving for {pending.tool_name}",
                payload={
                    "approval_id": approval_id,
                    "tool_name": pending.tool_name,
                    "decision": decision,
                    "request_count": len(items),
                },
            )

        if decision == "allow_conversation":
            with self._approval_lock:
                self._conversation_grants.add(
                    (pending.user_id, pending.conversation_id, pending.tool_name)
                )

        if decision == "deny":
            with self._approval_lock:
                self._approval_groups.pop((pending.run_id, pending.tool_name), None)
                for item in items:
                    if item.step_id:
                        self._resolved_step_results[(pending.run_id, item.step_id)] = SkillResult(
                            success=False,
                            error=f"User denied approval for {pending.tool_name}",
                            error_code="approval_denied",
                            data={"approval_id": approval_id, "decision": decision},
                            display_text="用户拒绝了该操作。",
                        )
            for item in items:
                self.trace_store.append_event(
                    pending.run_id,
                    type="tool.cancelled",
                    status="cancelled",
                    title=f"Tool {pending.tool_name} denied by user",
                    step_id=item.step_id,
                    payload={
                        "name": pending.tool_name,
                        "approval_id": approval_id,
                        "approval_resume": True,
                    },
                )
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
            self._notify_run_if_resolved(pending.run_id)
            return self._approval_resolution_payload(pending, decision, [], "denied")

        results: list[dict[str, Any]] = []
        for item in items:
            meta = item.skill.metadata()
            started_at = datetime.now(timezone.utc)
            self.trace_store.append_event(
                pending.run_id,
                type="tool.governance.allowed",
                status="completed",
                title=f"Tool governance allowed {pending.tool_name} after approval",
                step_id=item.step_id,
                payload={
                    "allowed": True,
                    "tool_name": pending.tool_name,
                    "policy": "confirm",
                    "reason": "conversation_approval" if decision == "allow_conversation" else "one_time_approval",
                    "call_count": self._allowed_call_count(pending.run_id, pending.tool_name) + 1,
                    "max_calls": meta.max_calls_per_run,
                    "approval_id": approval_id,
                    "risk_level": meta.risk_level,
                    "access": meta.access,
                    "arguments": self.redact_arguments(item.skill, item.arguments),
                },
            )
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
            if item.step_id:
                with self._approval_lock:
                    self._resolved_step_results[(pending.run_id, item.step_id)] = result
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
        self._notify_run_if_resolved(pending.run_id)
        return self._approval_resolution_payload(pending, decision, results, status)

    def _expire_run_approvals(self, run_id: str) -> None:
        now = datetime.now(timezone.utc)
        expired: list[tuple[PendingToolApproval, list[PendingToolApprovalItem]]] = []
        with self._approval_lock:
            for pending in self._pending_approvals.values():
                if (
                    pending.run_id != run_id
                    or pending.status != "pending"
                    or pending.expires_at > now
                ):
                    continue
                pending.status = "expired"
                self._approval_groups.pop((pending.run_id, pending.tool_name), None)
                items = list(pending.items)
                expired.append((pending, items))
                for item in items:
                    if item.step_id:
                        self._resolved_step_results[(run_id, item.step_id)] = SkillResult(
                            success=False,
                            error=f"Approval expired for {pending.tool_name}",
                            error_code="approval_expired",
                            data={"approval_id": pending.approval_id, "decision": "expired"},
                            display_text="授权已过期。",
                        )
        for pending, items in expired:
            self.trace_store.append_event(
                run_id,
                type="approval.resolved",
                status="error",
                title=f"Approval expired for {pending.tool_name}",
                payload={
                    "approval_id": pending.approval_id,
                    "tool_name": pending.tool_name,
                    "decision": "expired",
                    "request_count": len(items),
                    "succeeded_count": 0,
                    "failed_count": len(items),
                },
            )
        self._notify_run_if_resolved(run_id)

    def _notify_run_if_resolved(self, run_id: str) -> None:
        with self._approval_lock:
            outstanding = any(
                pending.run_id == run_id
                and pending.status in {"pending", "resolving"}
                for pending in self._pending_approvals.values()
            )
            event = self._approval_events.get(run_id)
            if not outstanding and event is not None:
                event.set()

    def cancel_run_approvals(self, run_id: str, *, reason: str = "run_cancelled") -> int:
        cancelled: list[tuple[PendingToolApproval, list[PendingToolApprovalItem]]] = []
        with self._approval_lock:
            for pending in self._pending_approvals.values():
                if pending.run_id != run_id or pending.status not in {"pending", "resolving"}:
                    continue
                pending.status = "cancelled"
                self._approval_groups.pop((pending.run_id, pending.tool_name), None)
                items = list(pending.items)
                cancelled.append((pending, items))
                for item in items:
                    if item.step_id:
                        self._resolved_step_results[(run_id, item.step_id)] = SkillResult(
                            success=False,
                            error=f"Approval cancelled for {pending.tool_name}: {reason}",
                            error_code="approval_cancelled",
                            data={"approval_id": pending.approval_id, "decision": "cancelled"},
                        )
        for pending, items in cancelled:
            self.trace_store.append_event(
                run_id,
                type="approval.resolved",
                status="cancelled",
                title=f"Approval cancelled for {pending.tool_name}",
                payload={
                    "approval_id": pending.approval_id,
                    "tool_name": pending.tool_name,
                    "decision": "cancelled",
                    "request_count": len(items),
                    "succeeded_count": 0,
                    "failed_count": 0,
                    "reason": reason,
                },
            )
        self._notify_run_if_resolved(run_id)
        return len(cancelled)

    def purge_user(self, user_id: str) -> None:
        normalized_user_id = str(user_id or "0").strip() or "0"
        with self._approval_lock:
            run_ids = {
                pending.run_id
                for pending in self._pending_approvals.values()
                if pending.user_id == normalized_user_id
                and pending.status in {"pending", "resolving"}
            }
            self._conversation_grants = {
                grant
                for grant in self._conversation_grants
                if grant[0] != normalized_user_id
            }
        for run_id in run_ids:
            self.cancel_run_approvals(run_id, reason="user_data_purged")

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
