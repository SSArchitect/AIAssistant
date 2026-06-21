from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

from agent.schemas.trace import RunEvent, RunRecord


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TraceStore:
    """In-memory run/event store for local debugging and MVP tracing."""

    def __init__(self):
        self._runs: dict[str, RunRecord] = {}
        self._created_at: dict[str, float] = {}
        self._lock = Lock()

    def start_run(
        self,
        *,
        conversation_id: str,
        user_id: str | None = None,
        input_text: str,
        agent_id: str,
        runtime: str,
        run_id: str | None = None,
    ) -> RunRecord:
        run_id = run_id or f"run_{uuid4().hex}"
        run = RunRecord(
            run_id=run_id,
            conversation_id=conversation_id,
            user_id=self._normalize_user_id(user_id),
            agent_id=agent_id,
            runtime=runtime,
            status="running",
            input=input_text,
            started_at=_now(),
        )
        with self._lock:
            self._runs[run_id] = run
            self._created_at[run_id] = perf_counter()
        self.append_event(
            run_id,
            type="run.started",
            status="running",
            title="Run started",
            payload={
                "agent_id": agent_id,
                "runtime": runtime,
                "user_id": self._normalize_user_id(user_id),
            },
        )
        return run

    def append_event(
        self,
        run_id: str,
        *,
        type: str,
        status: str,
        title: str = "",
        payload: Optional[dict[str, Any]] = None,
        duration_ms: Optional[int] = None,
        step_id: Optional[str] = None,
    ) -> RunEvent:
        event = RunEvent(
            id=f"evt_{uuid4().hex}",
            run_id=run_id,
            type=type,
            status=status,
            title=title,
            step_id=step_id,
            payload=payload or {},
            duration_ms=duration_ms,
            created_at=_now(),
        )
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None:
                run.events.append(event)
        return event

    def complete_run(
        self,
        run_id: str,
        *,
        output: str,
        model_used: str = "",
        tokens_used: Optional[dict[str, int]] = None,
        skills_used: Optional[list[str]] = None,
    ) -> RunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            run.status = "completed"
            run.output = output
            run.model_used = model_used
            run.tokens_used = tokens_used or {}
            run.skills_used = skills_used or []
            run.completed_at = _now()
            run.duration_ms = self._duration_ms(run_id)
        self.append_event(
            run_id,
            type="run.completed",
            status="completed",
            title="Run completed",
            payload={
                "model_used": model_used,
                "skills_used": skills_used or [],
                "tokens_used": tokens_used or {},
            },
            duration_ms=run.duration_ms,
        )
        return run

    def fail_run(
        self,
        run_id: str,
        *,
        error_message: str,
        error_type: str = "error",
        output: str = "",
    ) -> RunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            run.status = "failed"
            run.output = output
            run.error_type = error_type
            run.error_message = error_message
            run.completed_at = _now()
            run.duration_ms = self._duration_ms(run_id)
        self.append_event(
            run_id,
            type="run.failed",
            status="error",
            title="Run failed",
            payload={"error_type": error_type, "error_message": error_message},
            duration_ms=run.duration_ms,
        )
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def list_runs(
        self,
        *,
        conversation_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
    ) -> list[RunRecord]:
        with self._lock:
            runs = list(self._runs.values())
        if conversation_id:
            runs = [r for r in runs if r.conversation_id == conversation_id]
        if user_id is not None:
            normalized_user_id = self._normalize_user_id(user_id)
            runs = [r for r in runs if r.user_id == normalized_user_id]
        runs.sort(key=lambda r: r.started_at, reverse=True)
        return runs[:limit]

    @staticmethod
    def _normalize_user_id(value: str | int | None) -> str:
        text = str(value if value not in (None, "") else "0").strip()
        return text or "0"

    def _duration_ms(self, run_id: str) -> int:
        started = self._created_at.get(run_id)
        if started is None:
            return 0
        return max(0, int((perf_counter() - started) * 1000))
