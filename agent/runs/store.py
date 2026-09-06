from __future__ import annotations

import asyncio
import hashlib
import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Callable

from agent.schemas.chat import ChatRequest, ChatResponse


class RunConflict(ValueError):
    pass


class ConnectRuns:
    """Single-process runtime ownership; a restart interrupts unfinished work, never replays it."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.tasks: dict[str, asyncio.Task] = {}
        with self._db() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS connect_runs (
                id TEXT PRIMARY KEY, user_id TEXT NOT NULL, request_hash TEXT NOT NULL,
                status TEXT NOT NULL, response TEXT, error TEXT)""")
            db.execute("UPDATE connect_runs SET status='interrupted', error='runtime restarted' WHERE status='running'")

    @contextmanager
    def _db(self):
        db = sqlite3.connect(self.path, timeout=5)
        try:
            with db:
                yield db
        finally:
            db.close()

    def get(self, run_id: str, user_id: str) -> dict | None:
        with self._db() as db:
            row = db.execute("SELECT status,response,error FROM connect_runs WHERE id=? AND user_id=?", (run_id, user_id)).fetchone()
        if row is None:
            return None
        return {"run_id": run_id, "status": row[0], "response": json.loads(row[1]) if row[1] else None, "error": row[2]}

    def reserve(self, request: ChatRequest) -> bool:
        value = request.model_dump_json()
        digest = hashlib.sha256(value.encode()).hexdigest()
        with self._db() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT user_id,request_hash FROM connect_runs WHERE id=?", (request.run_id,)).fetchone()
            if existing:
                if existing != (request.user_id, digest):
                    raise RunConflict("run identity or parameters conflict")
                return False
            db.execute("INSERT INTO connect_runs(id,user_id,request_hash,status) VALUES(?,?,?,'running')", (request.run_id, request.user_id, digest))
        return True

    def finish(self, run_id: str, status: str, response: ChatResponse | None = None, error: str = ""):
        with self._db() as db:
            db.execute("UPDATE connect_runs SET status=?,response=?,error=? WHERE id=? AND status='running'", (status, response.model_dump_json() if response else None, error, run_id))

    def submit(self, request: ChatRequest, process: Callable, active: dict) -> dict:
        if not self.reserve(request):
            return self.get(request.run_id, request.user_id)

        async def execute():
            try:
                result = await process(request)
                self.finish(request.run_id, "completed", result)
                return result
            except asyncio.CancelledError:
                self.finish(request.run_id, "cancelled", error="cancelled")
            except Exception:
                self.finish(request.run_id, "failed", error="Agent execution failed; inspect the run trace")
            finally:
                self.tasks.pop(request.run_id, None)
                active.pop(request.run_id, None)

        task = asyncio.create_task(execute())
        self.tasks[request.run_id] = task
        active[request.run_id] = task
        # Cancellation before the coroutine first runs does not enter its finally block.
        def completed(done):
            if done.cancelled():
                self.finish(request.run_id, "cancelled", error="cancelled")
            self.tasks.pop(request.run_id, None)
            active.pop(request.run_id, None)
        task.add_done_callback(completed)
        return self.get(request.run_id, request.user_id)

    async def close(self):
        tasks = list(self.tasks.values())
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def purge_user(self, user_id: str):
        with self._db() as db:
            ids = [row[0] for row in db.execute("SELECT id FROM connect_runs WHERE user_id=?", (user_id,))]
        tasks = [self.tasks[run_id] for run_id in ids if run_id in self.tasks]
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        with self._db() as db:
            db.execute("DELETE FROM connect_runs WHERE user_id=?", (user_id,))
