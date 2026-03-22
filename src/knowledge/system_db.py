"""
SystemDB
────────
管理系统运行数据：会话、消息记录。
Checkpoint 由 LangGraph 自己管，不在这里。
"""
from __future__ import annotations

import json
import logging
import os
import threading
import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import create_engine, event, text
from sqlalchemy.pool import StaticPool

from ..config.settings import config

logger = logging.getLogger(__name__)


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
        db_path = os.path.abspath(config.db.system_db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        # 使用正斜杠，避免 Windows 下 \ 在 URL 中被转义
        db_uri = "sqlite:///" + db_path.replace("\\", "/")
        self._engine = create_engine(
            db_uri,
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            pool_pre_ping=True,
        )

        @event.listens_for(self._engine, "connect")
        def _set_sqlite_wal(dbapi_conn, connection_record):
            cursor = dbapi_conn.cursor()
            cursor.execute("PRAGMA journal_mode=WAL")
            cursor.close()

        self._migrate()
        logger.info("SystemDB 初始化完成")

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
                "meta":    json.dumps(meta) if meta else None,
            })
            conn.commit()
        return conversation_id

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
        """获取某会话的完整消息列表"""
        with self._engine.connect() as conn:
            result = conn.execute(text("""
                SELECT * FROM messages
                WHERE conversation_id = :id
                ORDER BY created_at ASC
            """), {"id": conversation_id})
            cols = list(result.keys())
            return [dict(zip(cols, row)) for row in result.fetchall()]
