"""SQLite task history and audit trail."""

from __future__ import annotations

import json
import sqlite3
import threading
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 2

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
        self._conn.execute("UPDATE meta SET value=? WHERE key='schema_version'", (str(version),))

    def mark_interrupted(self) -> int:
        """Tasks left running when the backend stopped are marked as interrupted, never as done."""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE tasks SET status='interrupted', updated_at=?, error=COALESCE(error, 'The agent stopped before this task finished.') "
                "WHERE status IN ('planning','running','awaiting_approval')",
                (_now(),),
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
            sql += " WHERE task_text LIKE ? ESCAPE '\\'"
            escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            params.append(f"%{escaped}%")
        sql += " ORDER BY created_at DESC LIMIT ?"
        params.append(limit)
        with self._lock:
            rows = self._conn.execute(sql, params).fetchall()
        return [_row_to_task(r) for r in rows]


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
