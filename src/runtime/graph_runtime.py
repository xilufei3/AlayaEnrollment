from __future__ import annotations

import os
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from inspect import signature
from pathlib import Path
from typing import Any, Iterator
from uuid import uuid4

from pymilvus import MilvusClient

from packages.alayadata.client import AlayaDataClient
from packages.retriever.service import RetrieverService
from packages.vector_store.milvus_store import MilvusVectorStore
from ..knowledge import SQLManager, SystemDB
from ..node.runtime_resources import bootstrap_runtime_dirs, load_dotenv_file
from .thread_registry import ThreadRegistry


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
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY", "").strip()
    secret_key = os.getenv("LANGFUSE_SECRET_KEY", "").strip()
    host = (
        os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
    ).strip().rstrip("/")
    if not public_key or not secret_key or public_key.endswith("-"):
        return None
    try:
        from langfuse.langchain import CallbackHandler

        accepted = set(signature(CallbackHandler.__init__).parameters.keys())

        # langfuse v3 的 CallbackHandler 不再接收 secret_key/host，需先初始化 client。
        if "secret_key" not in accepted and "host" not in accepted:
            try:
                from langfuse import Langfuse

                Langfuse(
                    public_key=public_key,
                    secret_key=secret_key,
                    host=host,
                )
            except Exception:
                pass

        candidate_kwargs: dict[str, Any] = {
            "public_key": public_key,
            "secret_key": secret_key,
            "host": host,
            "session_id": session_id,
            "user_id": user_id,
            "metadata": metadata,
        }
        kwargs: dict[str, Any] = {}
        for key, value in candidate_kwargs.items():
            if value is not None and key in accepted:
                kwargs[key] = value

        return CallbackHandler(**kwargs)
    except Exception:
        return None


@dataclass(slots=True)
class RuntimeConfig:
    repo_root: Path
    env_file: Path
    runtime_name: str = "chat-api"
    vector_top_k: int = 8
    rag_max_iterations: int = 2
    checkpoint_path: Path | None = None


def _create_retriever(env_file: Path | str | None = None) -> tuple[MilvusVectorStore, RetrieverService]:
    """Construct MilvusVectorStore + AlayaDataClient and wrap in RetrieverService."""
    load_dotenv_file(env_file)
    milvus_uri = os.getenv("MILVUS_URI", "http://localhost:19530")
    milvus_token = os.getenv("MILVUS_TOKEN") or ""
    milvus_db = os.getenv("MILVUS_DB_NAME") or "default"
    # support both naming conventions: AlayaData_URL (current .env) and ETL_SERVER_URL (legacy)
    etl_url = (
        os.getenv("AlayaData_URL")
    )

    milvus_client = MilvusClient(uri=milvus_uri, token=milvus_token, db_name=milvus_db)
    vector_store = MilvusVectorStore(milvus_client)
    alaya_client = AlayaDataClient(base_url=etl_url)
    retriever = RetrieverService(store=vector_store, alaya_client=alaya_client)
    return vector_store, retriever


def _load_sqlite_checkpointer(db_path: Path) -> tuple[Any, Any | None]:
    try:
        from langgraph.checkpoint.sqlite import SqliteSaver
    except ImportError as exc:
        raise RuntimeError(
            "Missing dependency: langgraph-checkpoint-sqlite. "
            "Install with: pip install langgraph-checkpoint-sqlite"
        ) from exc

    cm_or_saver = SqliteSaver.from_conn_string(str(db_path))
    enter = getattr(cm_or_saver, "__enter__", None)
    if callable(enter):
        saver = enter()
        return saver, cm_or_saver
    return cm_or_saver, None


class AdmissionGraphRuntime:
    STAGE_ORDER = (
        "intent_classify",   # 意图识别
        "agentic_rag",      # Agentic RAG（检索+评估循环）
        "generate",         # 生成答案（含 out_of_scope / 缺槽位追问 / other / RAG 回答）
    )

    def __init__(self, cfg: RuntimeConfig) -> None:
        self.cfg = cfg
        self._vector_store: Any | None = None
        self._checkpointer: Any | None = None
        self._checkpointer_cm: Any | None = None
        self._thread_registry: ThreadRegistry | None = None
        self._graph: Any | None = None
        self.runtime_root: Path | None = None
        self._threads: dict[str, dict[str, Any]] = {}

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

    def startup(self) -> None:
        # 最先加载 .env，确保后续所有代码（含 Langfuse）能读到环境变量
        load_dotenv_file(self.cfg.env_file)

        self.runtime_root = bootstrap_runtime_dirs(self.cfg.repo_root, runtime_name=self.cfg.runtime_name)
        from ..graph import create_graph

        self._vector_store, retriever = _create_retriever(self.cfg.env_file)
        checkpoint_path = self.cfg.checkpoint_path or (self.runtime_root / "checkpoints.sqlite")
        self._checkpointer, self._checkpointer_cm = _load_sqlite_checkpointer(checkpoint_path)
        self._thread_registry = ThreadRegistry(self.runtime_root / "thread_registry.sqlite")

        # 检查 Langfuse 是否可用
        _probe = _build_langfuse_handler()
        if _probe is not None:
            import sys
            host = os.getenv("LANGFUSE_HOST") or os.getenv("LANGFUSE_BASE_URL") or "https://cloud.langfuse.com"
            print(f"[AlayaEnrollment] Langfuse tracing enabled. host={host}", file=sys.stderr, flush=True)
            import logging
            logging.getLogger(__name__).info(
                "Langfuse tracing enabled. host=%s",
                host,
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

    def shutdown(self) -> None:
        if self._vector_store is not None and hasattr(self._vector_store, "close"):
            self._vector_store.close()
        self._vector_store = None
        self._graph = None
        if self._thread_registry is not None:
            self._thread_registry.close()
            self._thread_registry = None
        if self._checkpointer_cm is not None:
            exit_fn = getattr(self._checkpointer_cm, "__exit__", None)
            if callable(exit_fn):
                exit_fn(None, None, None)
        self._checkpointer = None
        self._checkpointer_cm = None

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
        self._threads[tid] = thread
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

        items = list(self._threads.values())
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
                    "metadata": self._jsonable(row.metadata or {}),
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
                "metadata": self._jsonable(thread_obj.get("metadata", {}) or {}),
                "created_at": thread_obj.get("state_updated_at"),
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
    ) -> tuple[str, Iterator[tuple[str, Any]]]:
        if self._graph is None:
            raise RuntimeError("Runtime not started")

        thread = self.create_thread(thread_id=thread_id)
        thread["status"] = "running"
        thread["updated_at"] = self._now_iso()

        query = self._extract_query_from_input(input_payload)
        input_messages: list[Any] = []
        if isinstance(input_payload, dict) and isinstance(input_payload.get("messages"), list):
            input_messages = list(input_payload.get("messages") or [])

        def _merge_for_initial_state(base: list[Any], pending: list[Any]) -> list[Any]:
            merged = list(base)
            seen_ids = {
                str(m.get("id", "")).strip()
                for m in merged
                if isinstance(m, dict) and str(m.get("id", "")).strip()
            }
            for msg in pending:
                if not isinstance(msg, dict):
                    continue
                mid = str(msg.get("id", "")).strip()
                if mid and mid in seen_ids:
                    continue
                merged.append(msg)
                if mid:
                    seen_ids.add(mid)
            return merged

        initial_state: dict[str, Any] = {"query": query}
        if input_messages:
            existing_state = self.get_thread_state(thread_id=thread_id)
            existing_values = existing_state.get("values", {}) if isinstance(existing_state, dict) else {}
            existing_raw = existing_values.get("messages", []) if isinstance(existing_values, dict) else []
            existing_json = self._jsonable(existing_raw)
            pending_json = self._jsonable(input_messages)
            base_messages = existing_json if isinstance(existing_json, list) else []
            pending_messages = pending_json if isinstance(pending_json, list) else []
            merged_messages = _merge_for_initial_state(base_messages, pending_messages)
            if merged_messages:
                initial_state["messages"] = merged_messages

        run_id = str(uuid4())
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        lf_handler = _build_langfuse_handler(
            session_id=thread_id,
            metadata={"run_id": run_id, "source": "langgraph_sdk"},
        )
        if lf_handler is not None:
            config["callbacks"] = [lf_handler]
        mode = stream_mode or "values"

        def _iter() -> Iterator[tuple[str, Any]]:
            latest_thread_values: dict[str, Any] | None = None

            for chunk in self._graph.stream(initial_state, config=config, stream_mode=mode):
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
                    _answer_nodes = {"generate"}
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

            if latest_thread_values is None:
                latest_thread_values = self._jsonable(
                    self.get_thread_state(thread_id=thread_id).get("values", {})
                )
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
            if lf_handler is not None and hasattr(lf_handler, "flush"):
                try:
                    lf_handler.flush()
                except Exception:
                    pass

        return run_id, _iter()

    def stream_stage_events(self, *, session_id: str, message: str) -> Iterator[dict[str, Any]]:
        if self._graph is None:
            raise RuntimeError("Runtime not started")

        started: set[str] = set()
        result_answer = ""
        config: dict[str, Any] = {"configurable": {"thread_id": session_id}}
        lf_handler = _build_langfuse_handler(
            session_id=session_id,
            metadata={"source": "chat_stream"},
        )
        if lf_handler is not None:
            config["callbacks"] = [lf_handler]

        yield {
            "event": "session.started",
            "data": {"session_id": session_id},
        }

        start_ts = time.time()
        for update in self._graph.stream({"query": message}, config=config, stream_mode="updates"):
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
                        missing = payload.get("missing_slots") or []
                        if missing:
                            summary["missing_slots"] = missing
                    elif node_name == "generate":
                        answer = str(payload.get("answer", "") or "")
                        result_answer = answer
                        summary["answer_len"] = len(answer)

                yield {"event": "stage.completed", "data": summary}

        if lf_handler is not None and hasattr(lf_handler, "flush"):
            try:
                lf_handler.flush()
            except Exception:
                pass

        yield {
            "event": "message.completed",
            "data": {
                "session_id": session_id,
                "answer": result_answer,
                "elapsed_ms": int((time.time() - start_ts) * 1000),
            },
        }
        yield {"event": "done", "data": {"session_id": session_id}}
