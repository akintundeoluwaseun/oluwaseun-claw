"""SQLite task history and audit trail."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 4

_SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS tasks (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    task_text TEXT NOT NULL,
    status TEXT NOT NULL,
    model TEXT,
    plan_json TEXT,
    error TEXT
);
CREATE TABLE IF NOT EXISTS task_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    task_id TEXT NOT NULL REFERENCES tasks(id) ON DELETE CASCADE,
    ts TEXT NOT NULL,
    kind TEXT NOT NULL,
    data_json TEXT NOT NULL
);
-- What S-CLAW remembers about the person. Deliberately a plain table with a
-- LIKE search rather than FTS5: a personal memory is hundreds of rows, not
-- millions, and FTS5 is not present in every SQLite that ships inside a frozen
-- build. Every row carries where it came from, because a memory with no
-- provenance cannot be judged later.
CREATE TABLE IF NOT EXISTS memories (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    kind TEXT NOT NULL,
    subject TEXT NOT NULL,
    fact TEXT NOT NULL,
    source TEXT NOT NULL,
    task_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_memories_kind ON memories(kind, subject);
-- Work S-CLAW does on a schedule. Every job keeps its own history, because a
-- job you cannot audit is a job you cannot trust: "it ran" is not an answer.
CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    name TEXT NOT NULL,
    task_text TEXT NOT NULL,
    kind TEXT NOT NULL,
    minutes INTEGER NOT NULL DEFAULT 0,
    at TEXT NOT NULL DEFAULT '',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_run TEXT,
    last_status TEXT,
    last_detail TEXT
);
CREATE TABLE IF NOT EXISTS job_runs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    at TEXT NOT NULL,
    status TEXT NOT NULL,
    detail TEXT NOT NULL DEFAULT '',
    task_id TEXT
);
CREATE INDEX IF NOT EXISTS idx_job_runs ON job_runs(job_id, id DESC);
CREATE INDEX IF NOT EXISTS idx_tasks_created ON tasks(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_events_task ON task_events(task_id, id);
"""


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds")


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._conn.execute("PRAGMA foreign_keys = ON")
            self._conn.execute("PRAGMA journal_mode = WAL")
            self._conn.executescript(_SCHEMA)
            self._conn.execute("INSERT OR IGNORE INTO meta(key, value) VALUES ('schema_version', '1')")
            self._migrate()
            self._conn.commit()

    def _migrate(self) -> None:
        version = int(self._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()["value"])
        if version < 2:
            cols = {r["name"] for r in self._conn.execute("PRAGMA table_info(tasks)")}
            if "result_json" not in cols:
                self._conn.execute("ALTER TABLE tasks ADD COLUMN result_json TEXT")
            version = 2
        if version < 4:
            pass        # the tables above are created with IF NOT EXISTS
        if version < 3:
            # The table itself is created by _SCHEMA above (CREATE TABLE IF NOT
            # EXISTS), so this only moves the version forward.
            version = 4
        self._conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(version),))

    def mark_interrupted(self) -> int:
        """Tasks left running when the backend stopped are marked as interrupted, never as done.

        The same applies to scheduled jobs. A job whose run was cut short keeps
        its "started" row otherwise, so Automations reads "Last: running now"
        for a run that ended when the computer was switched off, and the person
        has no way to tell that from a job that is genuinely working.
        """
        now = _now()
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status='interrupted', updated_at=?, error=COALESCE(error, 'The agent stopped before this task finished.') "
                "WHERE status IN ('planning','running','awaiting_approval')",
                (now,),
            )
            self._conn.execute(
                "UPDATE job_runs SET status='interrupted', "
                "detail='S-CLAW stopped before this run finished.' WHERE status='started'")
            self._conn.execute(
                "UPDATE jobs SET last_status='interrupted', updated_at=?, "
                "last_detail='S-CLAW stopped before this run finished.' WHERE last_status='started'",
                (now,),
            )
            self._conn.commit()
            return cur.rowcount

    def close(self) -> None:
        with self._lock:
            self._conn.close()

    def schema_version(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row["value"])

    def create_task(self, task_text: str, model: str | None) -> str:
        task_id = uuid.uuid4().hex
        ts = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO tasks(id, created_at, updated_at, task_text, status, model) VALUES (?,?,?,?,?,?)",
                (task_id, ts, ts, task_text, "created", model),
            )
            self._conn.commit()
        return task_id

    def update_task(
        self, task_id: str, *, status: str, plan: dict | None = None, error: str | None = None, result: dict | None = None
    ) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE tasks SET status=?, updated_at=?, plan_json=COALESCE(?, plan_json), error=?, "
                "result_json=COALESCE(?, result_json) WHERE id=?",
                (
                    status,
                    _now(),
                    json.dumps(plan) if plan is not None else None,
                    error,
                    json.dumps(result, default=str) if result is not None else None,
                    task_id,
                ),
            )
            self._conn.commit()

    def add_event(self, task_id: str, kind: str, data: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO task_events(task_id, ts, kind, data_json) VALUES (?,?,?,?)",
                (task_id, _now(), kind, json.dumps(data, default=str)),
            )
            self._conn.commit()

    def get_events(self, task_id: str, after_id: int = 0) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, kind, data_json FROM task_events WHERE task_id=? AND id>? ORDER BY id", (task_id, after_id)
            ).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "kind": r["kind"], "data": json.loads(r["data_json"])} for r in rows]

    def get_task(self, task_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
            if row is None:
                return None
            events = self._conn.execute(
                "SELECT id, ts, kind, data_json FROM task_events WHERE task_id=? ORDER BY id", (task_id,)
            ).fetchall()
        task = _row_to_task(row)
        task["events"] = [{"id": e["id"], "ts": e["ts"], "kind": e["kind"], "data": json.loads(e["data_json"])} for e in events]
        return task

    def list_tasks(self, limit: int = 50, query: str | None = None) -> list[dict[str, Any]]:
        limit = max(1, min(limit, 500))
        sql = "SELECT * FROM tasks"
        params: list[Any] = []
        if query:
            # Search what was asked, what Claw answered, and what went wrong.
            sql += " WHERE task_text LIKE ? ESCAPE '\\' OR result_json LIKE ? ESCAPE '\\' OR error LIKE ? ESCAPE '\\'"
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params += [f"%{escaped}%"] * 3
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_task(r) for r in rows]


    # ---------- memory ----------
    def remember(self, kind: str, subject: str, fact: str, source: str,
                 task_id: str | None = None) -> dict[str, Any]:
        """Store one thing. Replaces an earlier memory of the same kind and subject.

        Replacing rather than appending is the point: a preference that changed
        is not two preferences, and a person who corrects S-CLAW should not have
        to delete the old answer first.
        """
        now = _now()
        # The lock is not reentrant, so the row is read back *after* it is
        # released. Reading inside the block deadlocks the whole backend.
        with self._lock:
            existing = self._conn.execute(
                "SELECT id FROM memories WHERE kind=? AND lower(subject)=lower(?) AND lower(fact)=lower(?)",
                (kind, subject, fact)).fetchone()
            if existing:
                mem_id = existing["id"]
                self._conn.execute("UPDATE memories SET updated_at=?, source=?, task_id=? WHERE id=?",
                                   (now, source, task_id, mem_id))
            else:
                mem_id = uuid.uuid4().hex
                self._conn.execute(
                    "INSERT INTO memories(id, created_at, updated_at, kind, subject, fact, source, task_id) "
                    "VALUES (?,?,?,?,?,?,?,?)",
                    (mem_id, now, now, kind, subject, fact, source, task_id))
            self._conn.commit()
        return self._memory(mem_id)

    def _memory(self, mem_id: str) -> dict[str, Any]:
        with self._lock:
            row = self._conn.execute("SELECT * FROM memories WHERE id=?", (mem_id,)).fetchone()
        return dict(row) if row else {}

    def memories(self, query: str | None = None, kind: str | None = None,
                 limit: int = 200) -> list[dict[str, Any]]:
        sql = "SELECT * FROM memories"
        where, params = [], []
        if kind:
            where.append("kind=?")
            params.append(kind)
        if query:
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            where.append("(subject LIKE ? ESCAPE '\\' OR fact LIKE ? ESCAPE '\\')")
            params += [f"%{escaped}%"] * 2
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY updated_at DESC LIMIT ?"
        params.append(max(1, min(limit, 1000)))
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [dict(r) for r in rows]

    def forget(self, mem_id: str) -> dict[str, Any] | None:
        """Remove one memory, and hand back what was removed."""
        gone = self._memory(mem_id)
        if not gone:
            return None
        with self._lock:
            self._conn.execute("DELETE FROM memories WHERE id=?", (mem_id,))
            self._conn.commit()
        return gone

    def forget_all(self, kind: str | None = None) -> int:
        with self._lock:
            cur = (self._conn.execute("DELETE FROM memories WHERE kind=?", (kind,)) if kind
                   else self._conn.execute("DELETE FROM memories"))
            self._conn.commit()
            return cur.rowcount


    # ---------- scheduled jobs ----------
    def add_job(self, name: str, task_text: str, kind: str, minutes: int = 0, at: str = "") -> str:
        now = _now()
        job_id = uuid.uuid4().hex
        with self._lock:
            self._conn.execute(
                "INSERT INTO jobs(id, created_at, updated_at, name, task_text, kind, minutes, at) "
                "VALUES (?,?,?,?,?,?,?,?)", (job_id, now, now, name, task_text, kind, minutes, at))
            self._conn.commit()
        return job_id

    def jobs(self, only_enabled: bool = False) -> list[dict[str, Any]]:
        sql = "SELECT * FROM jobs" + (" WHERE enabled=1" if only_enabled else "") + " ORDER BY created_at"
        with self._lock:
            return [dict(r) for r in self._conn.execute(sql).fetchall()]

    def job(self, job_id: str) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        return dict(row) if row else None

    def set_job_enabled(self, job_id: str, enabled: bool) -> bool:
        with self._lock:
            cur = self._conn.execute("UPDATE jobs SET enabled=?, updated_at=? WHERE id=?",
                                     (1 if enabled else 0, _now(), job_id))
            self._conn.commit()
            return cur.rowcount > 0

    def delete_job(self, job_id: str) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM jobs WHERE id=?", (job_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def record_job_run(self, job_id: str, status: str, detail: str = "",
                       task_id: str | None = None) -> None:
        """One line of a job's history, and the summary on the job itself."""
        now = _now()
        with self._lock:
            self._conn.execute(
                "INSERT INTO job_runs(job_id, at, status, detail, task_id) VALUES (?,?,?,?,?)",
                (job_id, now, status, detail[:500], task_id))
            # "skipped" is history, not a run: a job skipped because the person
            # was using S-CLAW must still be due the moment they stop.
            if status != "skipped":
                self._conn.execute(
                    "UPDATE jobs SET last_run=?, last_status=?, last_detail=?, updated_at=? WHERE id=?",
                    (now, status, detail[:500], now, job_id))
            else:
                self._conn.execute("UPDATE jobs SET last_status=?, last_detail=?, updated_at=? WHERE id=?",
                                   (status, detail[:500], now, job_id))
            self._conn.commit()

    def job_runs(self, job_id: str, limit: int = 20) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM job_runs WHERE job_id=? ORDER BY id DESC LIMIT ?",
                (job_id, max(1, min(limit, 200)))).fetchall()
        return [dict(r) for r in rows]


def _row_to_task(row: sqlite3.Row) -> dict[str, Any]:
    return {
        "id": row["id"],
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
        "task_text": row["task_text"],
        "status": row["status"],
        "model": row["model"],
        "plan": json.loads(row["plan_json"]) if row["plan_json"] else None,
        "error": row["error"],
        "result": json.loads(row["result_json"]) if row["result_json"] else None,
    }
