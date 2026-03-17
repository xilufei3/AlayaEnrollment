"""
SystemDB
────────
管理系统运行数据：会话与消息记录。
Checkpoint（LangGraph 状态快照）由 LangGraph 自身管理，不在这里。

配置：
  - SYSTEM_DB_PATH  环境变量（可选）：覆盖默认数据库文件路径
  - 默认路径：<repo_root>/.runtime/chat-api/system.db
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_DB_PATH = _REPO_ROOT / ".runtime" / "chat-api" / "system.db"


def _resolve_db_path() -> Path:
    env_path = os.getenv("SYSTEM_DB_PATH")
    if env_path:
        p = Path(env_path)
        return p if p.is_absolute() else _REPO_ROOT / p
    return _DEFAULT_DB_PATH


class SystemDB:
    _instance: "SystemDB | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "SystemDB":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._initialized = False
                    cls._instance = obj
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._setup()
            self._initialized = True

    def _setup(self) -> None:
        db_path = _resolve_db_path()
        db_path.parent.mkdir(parents=True, exist_ok=True)
        db_uri = "sqlite:///" + str(db_path).replace("\\", "/")
        self._engine = create_engine(
            db_uri,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_pre_ping=True,
        )
        self._migrate()
        logger.info("SystemDB 初始化完成：%s", db_path)

    def _migrate(self) -> None:
        """建表，已存在则跳过"""
        with self._engine.connect() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS conversations (
                    id           TEXT PRIMARY KEY,
                    created_at   DATETIME NOT NULL DEFAULT (datetime('now')),
                    updated_at   DATETIME NOT NULL DEFAULT (datetime('now')),
                    user_id      TEXT,
                    channel      TEXT,
                    status       TEXT NOT NULL DEFAULT 'active',
                    summary      TEXT,
                    meta         TEXT
                )
            """))
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS messages (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    conversation_id TEXT    NOT NULL REFERENCES conversations(id),
                    role            TEXT    NOT NULL,
                    content         TEXT    NOT NULL,
                    created_at      DATETIME NOT NULL DEFAULT (datetime('now')),
                    intents         TEXT,
                    retrieval_mode  TEXT,
                    chunks_count    INTEGER,
                    sql_hit         INTEGER,
                    latency_ms      INTEGER
                )
            """))
            conn.commit()

    # ── 会话管理 ─────────────────────────────────────────────

    def create_conversation(
        self,
        user_id: str | None = None,
        channel: str = "web",
        meta: dict | None = None,
    ) -> str:
        """创建新会话，返回 conversation_id"""
        conversation_id = str(uuid.uuid4())
        with self._engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO conversations (id, user_id, channel, meta)
                VALUES (:id, :user_id, :channel, :meta)
            """), {
                "id":      conversation_id,
                "user_id": user_id,
                "channel": channel,
                "meta":    json.dumps(meta, ensure_ascii=False) if meta else None,
            })
            conn.commit()
        return conversation_id

    def get_conversation(self, conversation_id: str) -> dict[str, Any] | None:
        """获取单条会话信息，不存在返回 None"""
        with self._engine.connect() as conn:
            result = conn.execute(text("""
                SELECT * FROM conversations WHERE id = :id
            """), {"id": conversation_id})
            row = result.fetchone()
            if row is None:
                return None
            cols = list(result.keys())
            record = dict(zip(cols, row))
            if record.get("meta"):
                try:
                    record["meta"] = json.loads(record["meta"])
                except (json.JSONDecodeError, TypeError):
                    pass
            return record

    def list_conversations(
        self,
        *,
        user_id: str | None = None,
        channel: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """列出会话，支持按 user_id / channel / status 过滤"""
        clauses = ["1=1"]
        params: dict[str, Any] = {"limit": limit}
        if user_id is not None:
            clauses.append("user_id = :user_id")
            params["user_id"] = user_id
        if channel is not None:
            clauses.append("channel = :channel")
            params["channel"] = channel
        if status is not None:
            clauses.append("status = :status")
            params["status"] = status
        where = " AND ".join(clauses)
        with self._engine.connect() as conn:
            result = conn.execute(text(f"""
                SELECT * FROM conversations
                WHERE {where}
                ORDER BY updated_at DESC
                LIMIT :limit
            """), params)
            cols = list(result.keys())
            rows = []
            for row in result.fetchall():
                record = dict(zip(cols, row))
                if record.get("meta"):
                    try:
                        record["meta"] = json.loads(record["meta"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                rows.append(record)
            return rows

    def update_summary(self, conversation_id: str, summary: str) -> None:
        """更新会话摘要（由 summary_node 调用）"""
        with self._engine.connect() as conn:
            conn.execute(text("""
                UPDATE conversations
                SET summary    = :summary,
                    updated_at = datetime('now')
                WHERE id = :id
            """), {"summary": summary, "id": conversation_id})
            conn.commit()

    def end_conversation(self, conversation_id: str) -> None:
        """将会话标记为已结束"""
        with self._engine.connect() as conn:
            conn.execute(text("""
                UPDATE conversations
                SET status     = 'ended',
                    updated_at = datetime('now')
                WHERE id = :id
            """), {"id": conversation_id})
            conn.commit()

    # ── 消息记录 ─────────────────────────────────────────────

    def add_message(
        self,
        conversation_id: str,
        role: str,
        content: str,
        intents: list | None = None,
        retrieval_mode: str | None = None,
        chunks_count: int | None = None,
        sql_hit: bool | None = None,
        latency_ms: int | None = None,
    ) -> None:
        """记录一条消息"""
        with self._engine.connect() as conn:
            conn.execute(text("""
                INSERT INTO messages (
                    conversation_id, role, content,
                    intents, retrieval_mode, chunks_count, sql_hit, latency_ms
                ) VALUES (
                    :conversation_id, :role, :content,
                    :intents, :retrieval_mode, :chunks_count, :sql_hit, :latency_ms
                )
            """), {
                "conversation_id": conversation_id,
                "role":            role,
                "content":         content,
                "intents":         json.dumps(intents, ensure_ascii=False) if intents else None,
                "retrieval_mode":  retrieval_mode,
                "chunks_count":    chunks_count,
                "sql_hit":         1 if sql_hit else 0,
                "latency_ms":      latency_ms,
            })
            conn.commit()

    def get_messages(self, conversation_id: str) -> list[dict[str, Any]]:
        """获取某会话的完整消息列表（按时间正序）"""
        with self._engine.connect() as conn:
            result = conn.execute(text("""
                SELECT * FROM messages
                WHERE conversation_id = :id
                ORDER BY created_at ASC
            """), {"id": conversation_id})
            cols = list(result.keys())
            rows = []
            for row in result.fetchall():
                record = dict(zip(cols, row))
                if record.get("intents"):
                    try:
                        record["intents"] = json.loads(record["intents"])
                    except (json.JSONDecodeError, TypeError):
                        pass
                rows.append(record)
            return rows
