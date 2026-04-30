from __future__ import annotations

import asyncio
import os
import sqlite3
import time
from collections import OrderedDict
from contextlib import nullcontext
from dataclasses import dataclass
from datetime import datetime, timezone
from inspect import signature
from pathlib import Path
from typing import Any, AsyncIterator
from uuid import uuid4

from langchain_core.messages import HumanMessage


_DEFAULT_THREAD_CACHE_MAX = 2000
_DEFAULT_THREAD_CACHE_TTL = 7200  # 2 hours


class _LRUThreadCache:
    """Bounded LRU cache with TTL for in-memory thread objects.

    Actual thread data lives in SQLite (ThreadRegistry + checkpointer).
    This cache only holds hot thread objects to avoid repeated DB reads.
    Evicted threads are NOT deleted — they reload from DB on next access.
    """

    def __init__(self, maxsize: int = _DEFAULT_THREAD_CACHE_MAX, ttl: float = _DEFAULT_THREAD_CACHE_TTL) -> None:
        self._maxsize = max(1, maxsize)
        self._ttl = max(0.0, ttl)
        self._data: OrderedDict[str, tuple[dict[str, Any], float]] = OrderedDict()

    def get(self, key: str) -> dict[str, Any] | None:
        entry = self._data.get(key)
        if entry is None:
            return None
        value, ts = entry
        if self._ttl and (time.monotonic() - ts) > self._ttl:
            del self._data[key]
            return None
        self._data.move_to_end(key)
        return value

    def put(self, key: str, value: dict[str, Any]) -> None:
        if key in self._data:
            self._data.move_to_end(key)
            self._data[key] = (value, time.monotonic())
        else:
            if len(self._data) >= self._maxsize:
                self._data.popitem(last=False)  # evict oldest
            self._data[key] = (value, time.monotonic())

    def values(self) -> list[dict[str, Any]]:
        now = time.monotonic()
        result: list[dict[str, Any]] = []
        expired: list[str] = []
        for key, (value, ts) in self._data.items():
            if self._ttl and (now - ts) > self._ttl:
                expired.append(key)
            else:
                result.append(value)
        for key in expired:
            del self._data[key]
        return result

    def delete(self, key: str) -> dict[str, Any] | None:
        entry = self._data.pop(key, None)
        if entry is None:
            return None
        value, _ = entry
        return value

    def __len__(self) -> int:
        return len(self._data)

from ..knowledge import SQLManager, SystemDB
from ..knowledge.vector_manager import VectorManager
from ..graph.node.runtime_resources import bootstrap_runtime_dirs, load_dotenv_file
from .thread_registry import ThreadRegistry


@dataclass(slots=True, frozen=True)
class _LangfuseSettings:
    public_key: str
    secret_key: str
    host: str


def _read_env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    return raw.lower() in {"1", "true", "yes", "on"}


def _read_channel_rag_max_iterations(channel: str | None) -> int | None:
    normalized = str(channel or "").strip().lower()
    if not normalized:
        return None
    env_name = f"{normalized.upper()}_RAG_MAX_ITERATIONS"
    raw = os.getenv(env_name, "").strip()
    if not raw:
        return None
    try:
        value = int(raw)
    except ValueError:
        return None
    return max(0, value)


def _langfuse_enabled() -> bool:
    return _read_env_bool("LANGFUSE_ENABLED", False)


def _get_langfuse_settings() -> _LangfuseSettings | None:
    if not _langfuse_enabled():
        return None

    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    host = (
        os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    ).strip().rstrip("/")

    if not public_key or not secret_key or public_key.endswith("-"):
        return None

    return _LangfuseSettings(
        public_key=public_key,
        secret_key=secret_key,
        host=host,
    )


def get_client(*, public_key: str | None = None) -> Any:
    from langfuse import get_client as langfuse_get_client

    return langfuse_get_client(public_key=public_key)


def _build_langfuse_client() -> Any | None:
    settings = _get_langfuse_settings()
    if settings is None:
        return None

    try:
        from langfuse import Langfuse

        return Langfuse(
            public_key=settings.public_key,
            secret_key=settings.secret_key,
            host=settings.host,
        )
    except Exception as exc:
        _logging.getLogger(__name__).warning(
            "Langfuse client initialization failed: %s",
            exc,
            exc_info=True,
        )
        return None


def _flush_langfuse_client(public_key: str | None = None) -> None:
    settings = _get_langfuse_settings()
    resolved_public_key = public_key or (settings.public_key if settings is not None else None)
    if not resolved_public_key:
        return

    try:
        get_client(public_key=resolved_public_key).flush()
    except Exception:
        return


def _shutdown_langfuse_client(public_key: str | None = None) -> None:
    settings = _get_langfuse_settings()
    resolved_public_key = public_key or (settings.public_key if settings is not None else None)
    if not resolved_public_key:
        return

    try:
        get_client(public_key=resolved_public_key).shutdown()
    except Exception:
        return


def _build_langfuse_handler(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> Any | None:
    """
    按需构建 Langfuse CallbackHandler。
    若未安装 langfuse 包或未配置 LANGFUSE_PUBLIC_KEY，静默返回 None。
    """
    settings = _get_langfuse_settings()
    if settings is None:
        return None
    try:
        from langfuse.langchain import CallbackHandler

        accepted = set(signature(CallbackHandler.__init__).parameters.keys())

        # langfuse v3 的 CallbackHandler 不再接收 secret_key/host，需先初始化 client。
        if "secret_key" not in accepted and "host" not in accepted:
            try:
                _build_langfuse_client()
            except Exception:
                pass

        candidate_kwargs: dict[str, Any] = {
            "public_key": settings.public_key,
            "secret_key": settings.secret_key,
            "host": settings.host,
            "session_id": session_id,
            "user_id": user_id,
            "metadata": metadata,
        }
        kwargs: dict[str, Any] = {}
        for key, value in candidate_kwargs.items():
            if value is not None and key in accepted:
                kwargs[key] = value

        return CallbackHandler(**kwargs)
    except Exception as exc:
        _logging.getLogger(__name__).warning(
            "Langfuse callback handler unavailable; request tracing will be skipped: %s",
            exc,
            exc_info=True,
        )
        return None


def _build_langfuse_propagation_context(
    *,
    session_id: str | None = None,
    user_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    tags: list[str] | None = None,
    trace_name: str | None = None,
) -> Any:
    settings = _get_langfuse_settings()
    if settings is None:
        return nullcontext()

    sanitized_metadata: dict[str, str] = {}
    for key, value in (metadata or {}).items():
        if value is None:
            continue
        sanitized_metadata[str(key)] = str(value)

    normalized_tags = [str(tag) for tag in (tags or []) if str(tag).strip()]

    try:
        import langfuse

        kwargs: dict[str, Any] = {}
        if session_id is not None:
            kwargs["session_id"] = session_id
        if user_id is not None:
            kwargs["user_id"] = user_id
        if sanitized_metadata:
            kwargs["metadata"] = sanitized_metadata
        if normalized_tags:
            kwargs["tags"] = normalized_tags
        if trace_name is not None:
            kwargs["trace_name"] = trace_name
        return langfuse.propagate_attributes(**kwargs)
    except Exception:
        return nullcontext()


@dataclass(slots=True)
class RuntimeConfig:
    repo_root: Path
    env_file: Path
    runtime_name: str = "chat-api"
    vector_top_k: int = 8
    rag_max_iterations: int = 2
    checkpoint_path: Path | None = None


def _create_retriever(env_file: Path | str | None = None) -> VectorManager:
    """Construct the injected vector search backend used by the graph."""
    load_dotenv_file(env_file)
    return VectorManager()


async def _load_sqlite_checkpointer(db_path: Path) -> tuple[Any, Any | None]:
    try:
        from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency for async SQLite checkpoints. "
            "Install with: pip install langgraph-checkpoint-sqlite aiosqlite"
        ) from exc

    cm_or_saver = AsyncSqliteSaver.from_conn_string(str(db_path))
    aenter = getattr(cm_or_saver, "__aenter__", None)
    if callable(aenter):
        saver = await aenter()
        await saver.conn.execute("PRAGMA journal_mode=WAL")
        return saver, cm_or_saver
    if hasattr(cm_or_saver, "conn"):
        await cm_or_saver.conn.execute("PRAGMA journal_mode=WAL")
    return cm_or_saver, None


import logging as _logging

_startup_logger = _logging.getLogger("alaya.startup")

# 至少其一必须设置
_REQUIRED_ANY_ENV_GROUPS: tuple[tuple[str, ...], ...] = (
    (
        "QWEN_API_KEY",
        "DEEPSEEK_API_KEY",
        "INTENT_MODEL_API_KEY",
        "GENERATION_MODEL_API_KEY",
        "PLANNER_MODEL_API_KEY",
        "EVAL_MODEL_API_KEY",
    ),
    (
        "QWEN_BASE_URL",
        "DEEPSEEK_BASE_URL",
        "INTENT_MODEL_BASE_URL",
        "GENERATION_MODEL_BASE_URL",
        "PLANNER_MODEL_BASE_URL",
        "EVAL_MODEL_BASE_URL",
    ),
)

# 建议设置（缺失时 warning，不阻止启动）
_RECOMMENDED_ENV_VARS: tuple[str, ...] = (
    "API_SHARED_KEY",
    "MILVUS_URI",
    "AlayaData_URL",
)


def _env_enabled(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    return default


def _is_missing_env_var(name: str) -> bool:
    val = os.getenv(name, "").strip()
    return not val or val == "placeholder"


def _collect_required_rerank_env_vars() -> list[str]:
    if not _env_enabled("RERANK_ENABLED", True):
        return []

    provider = os.getenv("RERANK_PROVIDER", "qwen").strip().lower() or "qwen"
    if provider == "jina":
        return ["JINA_API_KEY"] if _is_missing_env_var("JINA_API_KEY") else []
    if provider == "qwen":
        if _is_missing_env_var("RERANK_API_KEY") and _is_missing_env_var("QWEN_API_KEY"):
            return ["RERANK_API_KEY | QWEN_API_KEY"]
        return []
    return [f"Unsupported RERANK_PROVIDER={provider!r}"]


def _validate_required_env_vars() -> None:
    """Fail fast if critical environment variables are missing."""
    missing: list[str] = _collect_required_rerank_env_vars()

    for group in _REQUIRED_ANY_ENV_GROUPS:
        if not any(os.getenv(name, "").strip() for name in group):
            missing.append(" | ".join(group))

    if missing:
        msg = "Missing required environment variables: " + ", ".join(missing)
        _startup_logger.error(msg)
        raise RuntimeError(msg)

    for name in _RECOMMENDED_ENV_VARS:
        val = os.getenv(name, "").strip()
        if not val:
            _startup_logger.warning("Recommended env var %s is not set", name)


class AdmissionGraphRuntime:
    STAGE_ORDER = (
        "intent_classify",      # 意图识别
        "direct_reply",         # 寒暄 / 超范围 / 低置信度短回复
        "agentic_rag",          # Agentic RAG（检索+评估循环）
        "generate",             # RAG 生成答案
    )

    _ANSWER_NODES = {"generate", "direct_reply"}

    def __init__(self, cfg: RuntimeConfig) -> None:
        self.cfg = cfg
        self._vector_store: Any | None = None
        self._checkpointer: Any | None = None
        self._checkpointer_cm: Any | None = None
        self._thread_registry: ThreadRegistry | None = None
        self._graph: Any | None = None
        self.runtime_root: Path | None = None
        self._checkpoint_db_path: Path | None = None
        self._threads = _LRUThreadCache(
            maxsize=int(os.getenv("THREAD_CACHE_MAX", str(_DEFAULT_THREAD_CACHE_MAX))),
            ttl=float(os.getenv("THREAD_CACHE_TTL", str(_DEFAULT_THREAD_CACHE_TTL))),
        )
        self._langfuse_public_key: str | None = None

    @staticmethod
    def _now_iso() -> str:
        return datetime.now(timezone.utc).isoformat()

    @staticmethod
    def _jsonable(value: Any) -> Any:
        from langchain_core.documents import Document
        from langchain_core.messages import BaseMessage

        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, BaseMessage):
            return {
                "type": getattr(value, "type", "unknown"),
                "content": getattr(value, "content", ""),
                "id": getattr(value, "id", None),
            }
        if isinstance(value, Document):
            return {
                "page_content": value.page_content,
                "metadata": dict(value.metadata or {}),
            }
        if isinstance(value, list):
            return [AdmissionGraphRuntime._jsonable(v) for v in value]
        if isinstance(value, tuple):
            return [AdmissionGraphRuntime._jsonable(v) for v in value]
        if isinstance(value, dict):
            return {str(k): AdmissionGraphRuntime._jsonable(v) for k, v in value.items()}
        if hasattr(value, "model_dump"):
            return AdmissionGraphRuntime._jsonable(value.model_dump())
        return str(value)

    async def startup(self) -> None:
        # 最先加载 .env，确保后续所有代码（含 Langfuse）能读到环境变量
        load_dotenv_file(self.cfg.env_file)
        _validate_required_env_vars()
        self._langfuse_public_key = None

        try:
            from ..graph.llm import reset_model_cache
            self.runtime_root = bootstrap_runtime_dirs(self.cfg.repo_root, runtime_name=self.cfg.runtime_name)
            from ..graph import create_graph

            reset_model_cache()
            retriever = _create_retriever(self.cfg.env_file)
            self._vector_store = retriever
            checkpoint_path = self.cfg.checkpoint_path or (self.runtime_root / "checkpoints.sqlite")
            self._checkpoint_db_path = checkpoint_path
            self._checkpointer, self._checkpointer_cm = await _load_sqlite_checkpointer(checkpoint_path)
            self._thread_registry = ThreadRegistry(self.runtime_root / "thread_registry.sqlite")

            # 检查 Langfuse 是否可用
            langfuse_settings = _get_langfuse_settings()
            langfuse_client = _build_langfuse_client()
            if langfuse_settings is not None and langfuse_client is not None:
                self._langfuse_public_key = langfuse_settings.public_key
                import sys
                print(
                    f"[AlayaEnrollment] Langfuse tracing enabled. host={langfuse_settings.host}",
                    file=sys.stderr,
                    flush=True,
                )
                import logging
                logging.getLogger(__name__).info(
                    "Langfuse tracing enabled. host=%s",
                    langfuse_settings.host,
                )

            self._graph = create_graph(
                {
                    "retriever": retriever,
                    "vector_top_k": self.cfg.vector_top_k,
                    "rag_max_iterations": self.cfg.rag_max_iterations,
                },
                checkpointer=self._checkpointer,
            )

        # 初始化系统数据库（会话 & 消息记录）
            SystemDB()

        # 初始化业务结构化数据管理器（registry 不存在时跳过，不影响启动）
            try:
                SQLManager()
            except Exception as _sql_err:
                import logging as _log
                _log.getLogger(__name__).warning(
                "SQLManager 初始化跳过（table_registry 未配置或数据库不可用）：%s", _sql_err
            )

        except Exception:
            await self.shutdown()
            raise

    async def shutdown(self) -> None:
        if self._vector_store is not None and hasattr(self._vector_store, "close"):
            self._vector_store.close()
        self._vector_store = None
        self._graph = None
        if self._thread_registry is not None:
            self._thread_registry.close()
            self._thread_registry = None
        if self._checkpointer_cm is not None:
            exit_fn = getattr(self._checkpointer_cm, "__aexit__", None)
            if callable(exit_fn):
                await exit_fn(None, None, None)
        self._checkpointer = None
        self._checkpointer_cm = None
        self._checkpoint_db_path = None
        _shutdown_langfuse_client(self._langfuse_public_key)
        self._langfuse_public_key = None

    def create_thread(self, *, thread_id: str | None = None, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
        tid = thread_id or str(uuid4())
        now = self._now_iso()
        existing = self._threads.get(tid)
        if existing is not None:
            if metadata:
                thread_meta = existing.get("metadata", {})
                if not isinstance(thread_meta, dict):
                    thread_meta = {}
                thread_meta.update(metadata)
                existing["metadata"] = thread_meta
                existing["updated_at"] = now
            if self._thread_registry is not None:
                self._thread_registry.create_or_update(
                    thread_id=tid,
                    created_at=existing.get("created_at", now),
                    updated_at=now,
                    metadata=existing.get("metadata"),
                )
            return existing

        thread = {
            "thread_id": tid,
            "created_at": now,
            "updated_at": now,
            "state_updated_at": now,
            "metadata": metadata or {},
            "status": "idle",
            "values": {},
            "interrupts": {},
        }
        self._threads.put(tid, thread)
        if self._thread_registry is not None:
            self._thread_registry.create_or_update(
                thread_id=tid,
                created_at=now,
                updated_at=now,
                metadata=thread["metadata"],
            )
        return thread

    def search_threads(
        self,
        *,
        metadata: dict[str, Any] | None = None,
        limit: int = 10,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        if self._thread_registry is not None:
            rows = self._thread_registry.list_threads(
                metadata_filter=metadata,
                limit=limit,
                offset=offset,
            )
            result: list[dict[str, Any]] = []
            for row in rows:
                tid = row["thread_id"]
                state = self.get_thread_state(thread_id=tid)
                values = state.get("values", {}) if isinstance(state, dict) else {}
                result.append({
                    "thread_id": tid,
                    "created_at": row["created_at"],
                    "updated_at": row["updated_at"],
                    "state_updated_at": row["updated_at"],
                    "metadata": row["metadata"],
                    "status": "idle",
                    "values": values,
                    "interrupts": {},
                })
            return result

        items = self._threads.values()
        if metadata:

            def _match(item: dict[str, Any]) -> bool:
                thread_meta = item.get("metadata", {})
                if not isinstance(thread_meta, dict):
                    return False
                for k, v in metadata.items():
                    if thread_meta.get(k) != v:
                        return False
                return True

            items = [it for it in items if _match(it)]

        items.sort(key=lambda x: str(x.get("updated_at", "")), reverse=True)
        start = max(0, int(offset))
        end = start + max(0, int(limit))
        return items[start:end]

    def count_threads(self, *, metadata: dict[str, Any] | None = None) -> int:
        if self._thread_registry is not None:
            return self._thread_registry.count_threads(metadata_filter=metadata)

        items = self._threads.values()
        if not metadata:
            return len(items)

        def _match(item: dict[str, Any]) -> bool:
            thread_meta = item.get("metadata", {})
            if not isinstance(thread_meta, dict):
                return False
            for key, value in metadata.items():
                if thread_meta.get(key) != value:
                    return False
            return True

        return sum(1 for item in items if _match(item))

    def count_distinct_thread_metadata_values(
        self,
        *,
        metadata_key: str,
        metadata_filter: dict[str, Any] | None = None,
    ) -> int:
        if self._thread_registry is not None:
            return self._thread_registry.count_distinct_metadata_values(
                metadata_key=metadata_key,
                metadata_filter=metadata_filter,
            )

        values: set[str] = set()
        for item in self._threads.values():
            thread_meta = item.get("metadata", {})
            if not isinstance(thread_meta, dict):
                continue
            if metadata_filter:
                for key, value in metadata_filter.items():
                    if thread_meta.get(key) != value:
                        break
                else:
                    normalized = str(thread_meta.get(metadata_key) or "").strip()
                    if normalized:
                        values.add(normalized)
                continue
            normalized = str(thread_meta.get(metadata_key) or "").strip()
            if normalized:
                values.add(normalized)
        return len(values)

    @staticmethod
    def _extract_query_from_input(input_payload: Any) -> str:
        if isinstance(input_payload, str):
            return input_payload.strip()
        if not isinstance(input_payload, dict):
            return ""
        query = input_payload.get("query")
        if isinstance(query, str) and query.strip():
            return query.strip()

        messages = input_payload.get("messages")
        if isinstance(messages, list):
            for msg in reversed(messages):
                if not isinstance(msg, dict):
                    continue
                if str(msg.get("type", "")).lower() not in ("human", "user"):
                    continue
                content = msg.get("content")
                if isinstance(content, str) and content.strip():
                    return content.strip()
                if isinstance(content, list):
                    parts: list[str] = []
                    for part in content:
                        if isinstance(part, str):
                            parts.append(part)
                        elif isinstance(part, dict) and part.get("type") == "text":
                            parts.append(str(part.get("text", "")))
                    text = " ".join([p for p in parts if p]).strip()
                    if text:
                        return text
        return ""

    @staticmethod
    def _message_type(message: Any) -> str:
        if isinstance(message, dict):
            return str(message.get("type", message.get("role", ""))).lower()
        return str(getattr(message, "type", "")).lower()

    @classmethod
    def _messages_match(cls, left: Any, right: Any) -> bool:
        left_id = str(getattr(left, "id", None) if not isinstance(left, dict) else left.get("id", "") or "").strip()
        right_id = str(getattr(right, "id", None) if not isinstance(right, dict) else right.get("id", "") or "").strip()
        if left_id and right_id:
            return left_id == right_id

        left_content = cls._jsonable(
            getattr(left, "content", None) if not isinstance(left, dict) else left.get("content")
        )
        right_content = cls._jsonable(
            getattr(right, "content", None) if not isinstance(right, dict) else right.get("content")
        )
        return cls._message_type(left) == cls._message_type(right) and left_content == right_content

    @classmethod
    def _select_input_messages_for_initial_state(
        cls,
        *,
        existing_messages: list[Any],
        pending_messages: list[Any],
        query: str,
    ) -> list[Any]:
        if pending_messages:
            if not existing_messages:
                return pending_messages
            if len(pending_messages) >= len(existing_messages):
                prefix_matches = all(
                    cls._messages_match(existing_messages[idx], pending_messages[idx])
                    for idx in range(len(existing_messages))
                )
                if prefix_matches:
                    return pending_messages[len(existing_messages) :]
            return [pending_messages[-1]]
        if query:
            return [HumanMessage(content=query)]
        return []

    def _resolve_thread_metadata(
        self,
        *,
        thread_id: str,
        fallback: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        merged = dict(fallback or {})

        thread_obj = self._threads.get(thread_id)
        if isinstance(thread_obj, dict):
            thread_meta = thread_obj.get("metadata", {})
            if isinstance(thread_meta, dict):
                merged.update(self._jsonable(thread_meta))

        if self._thread_registry is not None:
            row = self._thread_registry.get_thread(thread_id)
            if isinstance(row, dict):
                registry_meta = row.get("metadata", {})
                if isinstance(registry_meta, dict):
                    merged.update(self._jsonable(registry_meta))

        return merged

    def get_registry_thread(self, *, thread_id: str) -> dict[str, Any] | None:
        if self._thread_registry is None:
            return None

        row = self._thread_registry.get_thread(thread_id)
        if not isinstance(row, dict):
            return None

        metadata = row.get("metadata", {})
        normalized_metadata = self._jsonable(metadata if isinstance(metadata, dict) else {})
        return {
            "thread_id": thread_id,
            "created_at": row.get("created_at"),
            "updated_at": row.get("updated_at"),
            "metadata": normalized_metadata if isinstance(normalized_metadata, dict) else {},
        }

    def delete_thread(self, *, thread_id: str) -> dict[str, int | bool]:
        checkpoint_deleted = 0
        write_deleted = 0

        if self._checkpoint_db_path is not None:
            conn = sqlite3.connect(str(self._checkpoint_db_path))
            try:
                conn.execute("PRAGMA busy_timeout = 5000")
                cursor = conn.execute(
                    "DELETE FROM writes WHERE thread_id = ?",
                    (thread_id,),
                )
                write_deleted = max(0, int(cursor.rowcount or 0))
                cursor = conn.execute(
                    "DELETE FROM checkpoints WHERE thread_id = ?",
                    (thread_id,),
                )
                checkpoint_deleted = max(0, int(cursor.rowcount or 0))
                conn.commit()
            finally:
                conn.close()

        registry_deleted = 0
        if self._thread_registry is not None:
            registry_deleted = self._thread_registry.delete_thread(thread_id)

        cache_deleted = self._threads.delete(thread_id) is not None
        existed = any((checkpoint_deleted, write_deleted, registry_deleted)) or cache_deleted

        return {
            "existed": existed,
            "checkpoints": checkpoint_deleted,
            "writes": write_deleted,
            "registry_rows": registry_deleted,
            "cache_entries": 1 if cache_deleted else 0,
        }

    def get_thread_history(self, *, thread_id: str, limit: int = 10) -> list[dict[str, Any]]:
        if self._checkpointer is None:
            return []
        config = {"configurable": {"thread_id": thread_id}}
        rows = list(self._checkpointer.list(config, limit=limit))
        states: list[dict[str, Any]] = []
        for row in rows:
            checkpoint = row.checkpoint or {}
            channel_values = checkpoint.get("channel_values") or {}
            checkpoint_id = (
                row.config.get("configurable", {}).get("checkpoint_id")
                if isinstance(row.config, dict)
                else None
            ) or checkpoint.get("id")
            checkpoint_ns = (
                row.config.get("configurable", {}).get("checkpoint_ns")
                if isinstance(row.config, dict)
                else ""
            ) or ""
            states.append(
                {
                    "values": self._jsonable(channel_values),
                    "next": [],
                    "checkpoint": {
                        "thread_id": thread_id,
                        "checkpoint_ns": checkpoint_ns,
                        "checkpoint_id": checkpoint_id,
                        "checkpoint_map": None,
                    },
                    "metadata": self._resolve_thread_metadata(
                        thread_id=thread_id,
                        fallback=self._jsonable(row.metadata or {}),
                    ),
                    "created_at": checkpoint.get("ts"),
                    "parent_checkpoint": None,
                    "tasks": [],
                }
            )
        return states

    def get_thread_state(self, *, thread_id: str) -> dict[str, Any]:
        states = self.get_thread_history(thread_id=thread_id, limit=1)
        if states:
            return states[0]

        thread_obj = self._threads.get(thread_id)
        if isinstance(thread_obj, dict):
            thread_values = self._jsonable(thread_obj.get("values", {}) or {})
            return {
                "values": thread_values if isinstance(thread_values, dict) else {},
                "next": [],
                "checkpoint": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": None,
                    "checkpoint_map": None,
                },
                "metadata": self._resolve_thread_metadata(
                    thread_id=thread_id,
                    fallback=self._jsonable(thread_obj.get("metadata", {}) or {}),
                ),
                "created_at": thread_obj.get("state_updated_at"),
                "parent_checkpoint": None,
                "tasks": [],
            }

        registry_row = self.get_registry_thread(thread_id=thread_id)
        if isinstance(registry_row, dict):
            registry_metadata = self._jsonable(registry_row.get("metadata", {}) or {})
            return {
                "values": {},
                "next": [],
                "checkpoint": {
                    "thread_id": thread_id,
                    "checkpoint_ns": "",
                    "checkpoint_id": None,
                    "checkpoint_map": None,
                },
                "metadata": self._resolve_thread_metadata(
                    thread_id=thread_id,
                    fallback=registry_metadata if isinstance(registry_metadata, dict) else {},
                ),
                "created_at": registry_row.get("updated_at") or registry_row.get("created_at"),
                "parent_checkpoint": None,
                "tasks": [],
            }

        return {
            "values": {},
            "next": [],
            "checkpoint": {
                "thread_id": thread_id,
                "checkpoint_ns": "",
                "checkpoint_id": None,
                "checkpoint_map": None,
            },
            "metadata": {},
            "created_at": None,
            "parent_checkpoint": None,
            "tasks": [],
        }

    def stream_langgraph_events(
        self,
        *,
        thread_id: str,
        input_payload: Any,
        stream_mode: str | list[str] | None,
    ) -> tuple[str, AsyncIterator[tuple[str, Any]]]:
        if self._graph is None:
            raise RuntimeError("Runtime not started")

        thread = self.create_thread(thread_id=thread_id)
        thread["status"] = "running"
        thread["updated_at"] = self._now_iso()

        query = self._extract_query_from_input(input_payload)
        input_messages: list[Any] = []
        if isinstance(input_payload, dict) and isinstance(input_payload.get("messages"), list):
            input_messages = list(input_payload.get("messages") or [])

        run_id = str(uuid4())
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        lf_handler = None
        lf_trace_context = nullcontext()
        if _langfuse_enabled():
            lf_handler = _build_langfuse_handler(
                session_id=thread_id,
                metadata={"thread_id": thread_id, "run_id": run_id, "source": "langgraph_sdk"},
            )
            lf_trace_context = _build_langfuse_propagation_context(
                session_id=thread_id,
                metadata={"thread_id": thread_id, "run_id": run_id, "source": "langgraph_sdk"},
                tags=["langgraph_sdk"],
                trace_name=f"langgraph-sdk:{thread_id}",
            )
        if lf_handler is not None:
            config["callbacks"] = [lf_handler]
        mode = stream_mode or "values"

        async def _iter() -> AsyncIterator[tuple[str, Any]]:
            existing_values = thread.get("values", {}) if isinstance(thread, dict) else {}
            if not existing_values:
                persisted_state = await asyncio.to_thread(self.get_thread_state, thread_id=thread_id)
                persisted_values = persisted_state.get("values", {}) if isinstance(persisted_state, dict) else {}
                if isinstance(persisted_values, dict) and persisted_values:
                    existing_values = persisted_values
                    thread["values"] = persisted_values

            initial_state: dict[str, Any] = {"query": query}
            existing_raw = existing_values.get("messages", []) if isinstance(existing_values, dict) else []
            existing_json = self._jsonable(existing_raw)
            pending_json = self._jsonable(input_messages)
            base_messages = existing_json if isinstance(existing_json, list) else []
            pending_messages = pending_json if isinstance(pending_json, list) else []
            input_message_delta = self._select_input_messages_for_initial_state(
                existing_messages=base_messages,
                pending_messages=pending_messages,
                query=query,
            )
            if input_message_delta:
                initial_state["messages"] = input_message_delta

            latest_thread_values: dict[str, Any] | None = None

            try:
                with lf_trace_context:
                    async for chunk in self._graph.astream(initial_state, config=config, stream_mode=mode):
                        event_name: str
                        event_data: Any
                        if isinstance(chunk, tuple) and len(chunk) == 2:
                            event_name = str(chunk[0])
                            event_data = chunk[1]
                        else:
                            event_name = str(mode if isinstance(mode, str) else "values")
                            event_data = chunk

                        if event_name == "messages":
                            meta = None
                            if isinstance(event_data, (tuple, list)) and len(event_data) >= 2:
                                maybe_meta = event_data[1]
                                if isinstance(maybe_meta, dict):
                                    meta = maybe_meta
                            node_name = str((meta or {}).get("langgraph_node", "")).strip()
                            _answer_nodes = self._ANSWER_NODES
                            if node_name and node_name not in _answer_nodes:
                                continue

                        payload = self._jsonable(event_data)
                        if event_name == "messages":
                            yield (event_name, payload)
                            continue

                        if event_name == "values" and isinstance(payload, dict):
                            latest_thread_values = payload
                            # Do not expose internal pipeline state (intent/chunks/etc.) to chat UI.
                            # Keep only fields that the SDK UI consumes for rendering/conversation flow.
                            public_payload: dict[str, Any] = {}
                            if isinstance(payload.get("messages"), list):
                                public_payload["messages"] = payload.get("messages")
                            elif isinstance(initial_state.get("messages"), list):
                                public_payload["messages"] = initial_state.get("messages")
                            if "__interrupt__" in payload:
                                public_payload["__interrupt__"] = payload["__interrupt__"]
                            if "context" in payload:
                                public_payload["context"] = payload["context"]
                            if "ui" in payload:
                                public_payload["ui"] = payload["ui"]
                            payload = public_payload
                        yield (event_name, payload)
            finally:
                if latest_thread_values is None:
                    latest_thread_values = self._jsonable(thread.get("values", {}) or {})
                thread["values"] = latest_thread_values
                thread["status"] = "idle"
                thread["updated_at"] = self._now_iso()
                thread["state_updated_at"] = thread["updated_at"]
                if self._thread_registry is not None:
                    self._thread_registry.update_timestamp(
                        thread_id=thread_id,
                        updated_at=thread["updated_at"],
                    )
                # 确保 Langfuse 把本请求的 trace 上报
                if lf_handler is not None:
                    _flush_langfuse_client(self._langfuse_public_key)

        return run_id, _iter()

    def stream_stage_events(
        self,
        *,
        session_id: str,
        message: str,
        channel: str | None = None,
    ) -> AsyncIterator[dict[str, Any]]:
        if self._graph is None:
            raise RuntimeError("Runtime not started")

        config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
        lf_handler = None
        lf_trace_context = nullcontext()
        metadata = {"session_id": session_id, "source": "chat_stream"}
        if channel:
            metadata["channel"] = channel
        if _langfuse_enabled():
            lf_handler = _build_langfuse_handler(
                session_id=session_id,
                metadata=metadata,
            )
            lf_trace_context = _build_langfuse_propagation_context(
                session_id=session_id,
                metadata=metadata,
                tags=["chat_stream"],
                trace_name=f"chat-stream:{session_id}",
            )
        if lf_handler is not None:
            config["callbacks"] = [lf_handler]

        async def _iter() -> AsyncIterator[dict[str, Any]]:
            started: set[str] = set()
            result_answer = ""

            yield {
                "event": "session.started",
                "data": {"session_id": session_id},
            }

            start_ts = time.time()
            initial_state = {
                "query": message,
                "messages": [HumanMessage(content=message)],
            }
            if channel:
                initial_state["channel"] = channel
                rag_max_iterations = _read_channel_rag_max_iterations(channel)
                if rag_max_iterations is not None:
                    initial_state["rag_max_iterations"] = rag_max_iterations
            try:
                with lf_trace_context:
                    async for update in self._graph.astream(initial_state, config=config, stream_mode="updates"):
                        if not isinstance(update, dict):
                            continue
                        for node_name, payload in update.items():
                            if node_name not in self.STAGE_ORDER:
                                continue
                            if node_name not in started:
                                started.add(node_name)
                                yield {
                                    "event": "stage.started",
                                    "data": {"stage": node_name, "session_id": session_id},
                                }

                            summary: dict[str, Any] = {"stage": node_name, "session_id": session_id}
                            if isinstance(payload, dict):
                                if node_name == "intent_classify":
                                    summary["intent"] = payload.get("intent", "")
                                    summary["confidence"] = payload.get("confidence", 0.0)
                                elif node_name == "agentic_rag":
                                    chunks = payload.get("chunks", []) or []
                                    summary["chunks_count"] = len(chunks)
                                elif node_name in self._ANSWER_NODES:
                                    answer = str(payload.get("answer", "") or "")
                                    result_answer = answer
                                    summary["answer_len"] = len(answer)

                            yield {"event": "stage.completed", "data": summary}
            finally:
                if lf_handler is not None:
                    _flush_langfuse_client(self._langfuse_public_key)

            yield {
                "event": "message.completed",
                "data": {
                    "session_id": session_id,
                    "answer": result_answer,
                    "elapsed_ms": int((time.time() - start_ts) * 1000),
                },
            }
            yield {"event": "done", "data": {"session_id": session_id}}

        return _iter()
