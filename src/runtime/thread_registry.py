"""
Persistent thread registry (SQLite) for sidebar thread list.
Stores thread_id, created_at, updated_at, metadata; actual state (messages etc.) stays in checkpointer.
"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


def _default_json(o: Any) -> Any:
    raise TypeError(f"Object of type {type(o).__name__} is not JSON serializable")


class ThreadRegistry:
    """SQLite-backed list of threads for sidebar; survives process restart."""

    def __init__(self, db_path: Path) -> None:
        self._path = Path(db_path)
        self._conn: sqlite3.Connection | None = None

    def _ensure_conn(self) -> sqlite3.Connection:
        if self._conn is None:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(str(self._path), check_same_thread=False)
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute(
                """
                CREATE TABLE IF NOT EXISTS threads (
                    thread_id TEXT PRIMARY KEY,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )
            self._conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_threads_updated_at ON threads(updated_at DESC)"
            )
            self._conn.commit()
        return self._conn

    def create_or_update(
        self,
        *,
        thread_id: str,
        created_at: str,
        updated_at: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        conn = self._ensure_conn()
        meta_json = json.dumps(metadata or {}, ensure_ascii=False, default=_default_json)
        conn.execute(
            """
            INSERT INTO threads (thread_id, created_at, updated_at, metadata)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(thread_id) DO UPDATE SET
                updated_at = excluded.updated_at,
                metadata = excluded.metadata
            """,
            (thread_id, created_at, updated_at, meta_json),
        )
        conn.commit()

    def update_timestamp(self, *, thread_id: str, updated_at: str) -> None:
        conn = self._ensure_conn()
        conn.execute(
            "UPDATE threads SET updated_at = ? WHERE thread_id = ?",
            (updated_at, thread_id),
        )
        conn.commit()

    def delete_thread(self, thread_id: str) -> int:
        conn = self._ensure_conn()
        cursor = conn.execute(
            "DELETE FROM threads WHERE thread_id = ?",
            (thread_id,),
        )
        conn.commit()
        return max(0, int(cursor.rowcount or 0))

    def list_threads(
        self,
        *,
        metadata_filter: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        conn = self._ensure_conn()
        if not metadata_filter:
            rows = conn.execute(
                "SELECT thread_id, created_at, updated_at, metadata FROM threads ORDER BY updated_at DESC LIMIT ? OFFSET ?",
                (limit, offset),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT thread_id, created_at, updated_at, metadata FROM threads ORDER BY updated_at DESC",
            ).fetchall()

        out: list[dict[str, Any]] = []
        for row in rows:
            tid, created_at, updated_at, meta_json = row
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except (TypeError, ValueError):
                meta = {}
            if metadata_filter:
                for k, v in metadata_filter.items():
                    if meta.get(k) != v:
                        break
                else:
                    out.append(
                        {
                            "thread_id": tid,
                            "created_at": created_at,
                            "updated_at": updated_at,
                            "metadata": meta,
                        }
                    )
            else:
                out.append(
                    {
                        "thread_id": tid,
                        "created_at": created_at,
                        "updated_at": updated_at,
                        "metadata": meta,
                    }
                )
        if metadata_filter:
            out = out[offset : offset + limit]
        return out

    def count_threads(self, *, metadata_filter: dict[str, Any] | None = None) -> int:
        conn = self._ensure_conn()
        if not metadata_filter:
            row = conn.execute("SELECT COUNT(*) FROM threads").fetchone()
            return int(row[0] if row else 0)

        rows = conn.execute("SELECT metadata FROM threads").fetchall()
        total = 0
        for (meta_json,) in rows:
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except (TypeError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                continue
            for key, value in metadata_filter.items():
                if meta.get(key) != value:
                    break
            else:
                total += 1
        return total

    def count_distinct_metadata_values(
        self,
        *,
        metadata_key: str,
        metadata_filter: dict[str, Any] | None = None,
    ) -> int:
        conn = self._ensure_conn()
        rows = conn.execute("SELECT metadata FROM threads").fetchall()
        values: set[str] = set()
        for (meta_json,) in rows:
            try:
                meta = json.loads(meta_json) if meta_json else {}
            except (TypeError, ValueError):
                meta = {}
            if not isinstance(meta, dict):
                continue
            if metadata_filter:
                for key, value in metadata_filter.items():
                    if meta.get(key) != value:
                        break
                else:
                    normalized = str(meta.get(metadata_key) or "").strip()
                    if normalized:
                        values.add(normalized)
                continue
            normalized = str(meta.get(metadata_key) or "").strip()
            if normalized:
                values.add(normalized)
        return len(values)

    def get_thread(self, thread_id: str) -> dict[str, Any] | None:
        conn = self._ensure_conn()
        row = conn.execute(
            "SELECT thread_id, created_at, updated_at, metadata FROM threads WHERE thread_id = ?",
            (thread_id,),
        ).fetchone()
        if row is None:
            return None

        tid, created_at, updated_at, meta_json = row
        try:
            meta = json.loads(meta_json) if meta_json else {}
        except (TypeError, ValueError):
            meta = {}

        return {
            "thread_id": tid,
            "created_at": created_at,
            "updated_at": updated_at,
            "metadata": meta,
        }

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None
