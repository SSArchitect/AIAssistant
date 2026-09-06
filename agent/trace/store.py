from __future__ import annotations

from datetime import datetime, timezone
from threading import Lock
from pathlib import Path
import sqlite3
from contextlib import contextmanager
from time import perf_counter
from typing import Any, Optional
from uuid import uuid4

from agent.schemas.trace import RunEvent, RunRecord


def _now() -> datetime:
    return datetime.now(timezone.utc)


class TraceStore:
    """Run/event store with optional SQLite persistence; one runtime owns the database."""

    def __init__(self, path: Path | None = None):
        self._runs: dict[str, RunRecord] = {}
        self._created_at: dict[str, float] = {}
        self._lock = Lock()
        self._path = Path(path) if path else None
        if self._path:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._db() as db:
                db.execute("CREATE TABLE IF NOT EXISTS trace_runs (id TEXT PRIMARY KEY, record TEXT NOT NULL)")
                db.execute("CREATE TABLE IF NOT EXISTS trace_events (id TEXT PRIMARY KEY, run_id TEXT NOT NULL, event TEXT NOT NULL)")
                db.execute("CREATE INDEX IF NOT EXISTS trace_events_run ON trace_events(run_id)")
                for row in db.execute("SELECT record FROM trace_runs"):
                    run = RunRecord.model_validate_json(row[0])
                    self._runs[run.run_id] = run
                for run_id, value in db.execute("SELECT run_id,event FROM trace_events ORDER BY rowid"):
                    if run_id in self._runs:
                        self._runs[run_id].events.append(RunEvent.model_validate_json(value))
            for run in list(self._runs.values()):
                if run.status == "running":
                    run.status = "interrupted"
                    run.error_type = "runtime_restarted"
                    run.error_message = "服务已重启，执行已中断。媒体任务可能仍在生成，请保留原任务信息。"
                    run.completed_at = _now()
                    self.append_event(run.run_id, type="run.interrupted", status="interrupted",
                        title="Execution interrupted by restart", payload={"error_type": run.error_type})

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self._path, timeout=10)
        try:
            with db:
                yield db
        finally:
            db.close()

    def _persist_run(self, db, run):
        db.execute("INSERT OR REPLACE INTO trace_runs VALUES (?,?)",
            (run.run_id, run.model_dump_json(exclude={"events"})))

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
                if self._path:
                    with self._db() as db:
                        self._persist_run(db, run)
                        db.execute("INSERT INTO trace_events VALUES (?,?,?)",
                            (event.id, run_id, event.model_dump_json()))
        return event

    def complete_run(
        self,
        run_id: str,
        *,
        output: str,
        model_used: str = "",
        tokens_used: Optional[dict[str, int]] = None,
        skills_used: Optional[list[str]] = None,
        artifacts: Optional[list[dict[str, Any]]] = None,
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
            run.artifacts = artifacts or []
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
                "artifacts": artifacts or [],
                "tokens_used": tokens_used or {},
            },
            duration_ms=run.duration_ms,
        )
        return run

    def partial_run(
        self,
        run_id: str,
        *,
        output: str,
        error_type: str = "partial_summary",
        error_message: str = "",
        model_used: str = "",
        tokens_used: Optional[dict[str, int]] = None,
        skills_used: Optional[list[str]] = None,
        artifacts: Optional[list[dict[str, Any]]] = None,
    ) -> RunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            run.status = "partial"
            run.output = output
            run.model_used = model_used
            run.tokens_used = tokens_used or {}
            run.skills_used = skills_used or []
            run.artifacts = artifacts or []
            run.error_type = error_type
            run.error_message = error_message
            run.completed_at = _now()
            run.duration_ms = self._duration_ms(run_id)
        self.append_event(
            run_id,
            type="run.partial",
            status="partial",
            title="Run partial summary",
            payload={
                "error_type": error_type,
                "error_message": error_message,
                "model_used": model_used,
                "skills_used": skills_used or [],
                "artifacts": artifacts or [],
                "tokens_used": tokens_used or {},
                "response_status": "partial_summary",
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

    def cancel_run(
        self,
        run_id: str,
        *,
        reason: str = "user_cancelled",
        output: str = "",
    ) -> RunRecord | None:
        with self._lock:
            run = self._runs.get(run_id)
            if run is None:
                return None
            if run.status == "cancelled":
                return run
            run.status = "cancelled"
            run.output = output
            run.error_type = "cancelled"
            run.error_message = reason
            run.completed_at = _now()
            run.duration_ms = self._duration_ms(run_id)
        self.append_event(
            run_id,
            type="run.cancelled",
            status="cancelled",
            title="Run cancelled",
            payload={"error_type": "cancelled", "error_message": reason},
            duration_ms=run.duration_ms,
        )
        return run

    def get_run(self, run_id: str) -> RunRecord | None:
        with self._lock:
            return self._runs.get(run_id)

    def record_skill_use(self, run_id: str, skill_name: str) -> None:
        normalized = str(skill_name or "").strip()
        if not normalized:
            return
        with self._lock:
            run = self._runs.get(run_id)
            if run is not None and normalized not in run.skills_used:
                run.skills_used.append(normalized)
                if self._path:
                    with self._db() as db:
                        self._persist_run(db, run)

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

    def task_runs(self, user_id: str, limit: int = 50) -> list[RunRecord]:
        """Compact root tasks, including every active task regardless of recent history."""
        with self._lock:
            owned = {key: run for key, run in self._runs.items()
                     if run.user_id == self._normalize_user_id(user_id)}
            children = {e.payload.get("child_run_id") for run in owned.values() for e in run.events}
            roots = sorted((r for r in owned.values() if r.run_id not in children),
                           key=lambda r: r.started_at, reverse=True)
            selected = [r for r in roots if r.status == "running"]
            selected += [r for r in roots if r.status != "running"][:limit]
            result = []
            for run in selected:
                related = [run]
                seen = {run.run_id}
                for node in related:
                    for event in node.events:
                        child = owned.get(event.payload.get("child_run_id"))
                        if child and child.run_id not in seen:
                            related.append(child)
                            seen.add(child.run_id)
                events = sorted((e for node in related for e in node.events
                    if e.type.startswith(("media.", "research.", "aigc.", "run.", "approval."))
                    or e.type in {"tool.started", "tool.completed", "tool.failed", "agent.tool.delegated"}),
                    key=lambda e: e.created_at)
                safe_keys = {"kind", "stage", "task_id", "code", "name", "target_agent_id", "child_run_id",
                             "citation_count", "total", "query_index", "query_count", "chunk_index", "chunk_count", "chunk", "queue_position", "progress_percent"}
                compact_events = [e.model_copy(update={"payload": {k: v for k, v in e.payload.items() if k in safe_keys}})
                                  for e in events[-80:]]
                result.append(run.model_copy(update={"input": run.input[:160], "output": "", "events": compact_events}))
            return result

    def purge_user(self, user_id: str | None) -> int:
        normalized_user_id = self._normalize_user_id(user_id)
        with self._lock:
            run_ids = [
                run_id
                for run_id, run in self._runs.items()
                if run.user_id == normalized_user_id
            ]
            if self._path:
                with self._db() as db:
                    db.executemany("DELETE FROM trace_events WHERE run_id=?", [(rid,) for rid in run_ids])
                    db.executemany("DELETE FROM trace_runs WHERE id=?", [(rid,) for rid in run_ids])
            for run_id in run_ids:
                self._runs.pop(run_id, None)
                self._created_at.pop(run_id, None)
        return len(run_ids)

    @staticmethod
    def _normalize_user_id(value: str | int | None) -> str:
        text = str(value if value not in (None, "") else "0").strip()
        return text or "0"

    def _duration_ms(self, run_id: str) -> int:
        started = self._created_at.get(run_id)
        if started is None:
            return 0
        return max(0, int((perf_counter() - started) * 1000))
