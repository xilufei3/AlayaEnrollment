from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import time
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Any, AsyncIterator, Callable
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field, field_validator

_logger = logging.getLogger("alaya.api")

_MAX_METADATA_BYTES = 4096
_MAX_REQUEST_BODY_BYTES = 64 * 1024  # 64 KiB


def _check_metadata_size(v: dict[str, Any] | None) -> dict[str, Any] | None:
    if v is None:
        return v
    raw = json.dumps(v, default=str)
    if len(raw) > _MAX_METADATA_BYTES:
        raise ValueError(f"metadata too large (max {_MAX_METADATA_BYTES // 1024} KiB)")
    return v


def _metadata_validator(cls: Any, v: dict[str, Any] | None) -> dict[str, Any] | None:
    return _check_metadata_size(v)

try:
    from packages.vector_store.errors import VectorStoreError
except ModuleNotFoundError:
    class VectorStoreError(Exception):
        """Compatibility fallback when the legacy packages module is absent."""
from ..graph.llm import ModelRequestTimeoutError
from ..runtime.graph_runtime import AdmissionGraphRuntime, RuntimeConfig


def _sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


def _format_seconds(seconds: float) -> str:
    return f"{seconds:g}"


def _read_positive_float_env(name: str, default: float) -> float:
    raw = os.getenv(name, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError:
        return default
    if value <= 0:
        return default
    return value


class ChatStreamRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    message: str = Field(..., min_length=1, max_length=4000)
    trace_id: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_\-]*$")


class ThreadCreateRequest(BaseModel):
    thread_id: str | None = Field(default=None, max_length=128, pattern=r"^[a-zA-Z0-9_\-]+$")
    metadata: dict[str, Any] | None = None
    if_exists: str | None = Field(default=None, max_length=32)

    _validate_metadata = field_validator("metadata")(_metadata_validator)


class ThreadSearchRequest(BaseModel):
    metadata: dict[str, Any] | None = None
    limit: int = 10
    offset: int = 0

    _validate_metadata = field_validator("metadata")(_metadata_validator)


class ThreadHistoryRequest(BaseModel):
    limit: int = 10
    before: Any | None = None
    metadata: dict[str, Any] | None = None
    checkpoint: dict[str, Any] | None = None


class RunStreamRequest(BaseModel):
    """LangGraph SDK compat: accepts both snake_case and camelCase."""
    input: Any | None = None
    stream_mode: Annotated[str | list[str] | None, Field(validation_alias="streamMode")] = None
    stream_subgraphs: bool | None = None
    stream_resumable: bool | None = None
    assistant_id: Annotated[str | None, Field(validation_alias="assistantId")] = None
    checkpoint: dict[str, Any] | None = None
    checkpoint_id: Annotated[str | None, Field(validation_alias="checkpointId")] = None
    config: dict[str, Any] | None = None
    context: dict[str, Any] | None = None
    command: dict[str, Any] | None = None
    metadata: dict[str, Any] | None = None

    model_config = {"populate_by_name": True}

    _validate_metadata = field_validator("metadata")(_metadata_validator)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _error_code(exc: Exception) -> str:
    if isinstance(exc, ModelRequestTimeoutError):
        return "REQUEST_TIMEOUT"
    if isinstance(exc, VectorStoreError):
        return "VECTOR_STORE_ERROR"
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    if "timeout" in msg or "timeout" in name:
        return "REQUEST_TIMEOUT"
    if "model" in msg or "api key" in msg:
        return "MODEL_UNAVAILABLE"
    return "INTERNAL_ERROR"


def _timeout_error_payload(
    *,
    timeout_kind: str,
    message: str,
    **extra: Any,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "code": "REQUEST_TIMEOUT",
        "timeout_kind": timeout_kind,
        "message": message,
    }
    payload.update(extra)
    return payload


_SAFE_MESSAGES: dict[str, str] = {
    "INTERNAL_ERROR": "服务内部异常，请稍后重试。",
    "MODEL_UNAVAILABLE": "AI 模型暂时不可用，请稍后重试。",
    "VECTOR_STORE_ERROR": "数据检索异常，请稍后重试。",
}


def _error_payload(exc: Exception) -> dict[str, Any]:
    if isinstance(exc, ModelRequestTimeoutError):
        return _timeout_error_payload(
            timeout_kind=exc.timeout_kind,
            message=str(exc),
            model_kind=exc.model_kind,
            provider=exc.provider,
            timeout_seconds=exc.timeout_seconds,
        )

    if _error_code(exc) == "REQUEST_TIMEOUT":
        return _timeout_error_payload(
            timeout_kind="upstream_timeout",
            message="Upstream request timed out",
        )

    code = _error_code(exc)
    _logger.exception("Request error [%s]", code)
    return {
        "code": code,
        "message": _SAFE_MESSAGES.get(code, _SAFE_MESSAGES["INTERNAL_ERROR"]),
    }


class _ThreadRunLeaseRegistry:
    def __init__(self) -> None:
        self._active_thread_ids: set[str] = set()
        self._lock = asyncio.Lock()

    async def try_acquire(self, thread_id: str) -> bool:
        async with self._lock:
            if thread_id in self._active_thread_ids:
                return False
            self._active_thread_ids.add(thread_id)
            return True

    async def release(self, thread_id: str) -> None:
        async with self._lock:
            self._active_thread_ids.discard(thread_id)

    async def is_active(self, thread_id: str) -> bool:
        async with self._lock:
            return thread_id in self._active_thread_ids


class _DeviceRateLimiter:
    """In-memory sliding-window counter per device ID."""

    def __init__(self, max_requests: int, window_seconds: float) -> None:
        self._max_requests = max(1, max_requests)
        self._window_seconds = max(1.0, window_seconds)
        self._timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check(self, device_id: str) -> bool:
        now = time.monotonic()
        cutoff = now - self._window_seconds
        async with self._lock:
            ts_list = self._timestamps[device_id]
            self._timestamps[device_id] = [t for t in ts_list if t > cutoff]
            if len(self._timestamps[device_id]) >= self._max_requests:
                return False
            self._timestamps[device_id].append(now)
            return True


async def _close_async_iterator(iterator: Any) -> None:
    aclose = getattr(iterator, "aclose", None)
    if aclose is None:
        return
    try:
        await aclose()
    except Exception:
        return


async def _guard_sse_events(
    event_source: AsyncIterator[tuple[str, Any]],
    *,
    idle_timeout_seconds: float,
    max_duration_seconds: float,
    idle_events_factory: Callable[[], list[tuple[str, Any]]],
    max_duration_events_factory: Callable[[], list[tuple[str, Any]]],
    exception_events_factory: Callable[[Exception], list[tuple[str, Any]]],
) -> AsyncIterator[str]:
    loop = asyncio.get_running_loop()
    started_at = loop.time()
    iterator = event_source.__aiter__()

    try:
        while True:
            elapsed = loop.time() - started_at
            remaining = max_duration_seconds - elapsed
            if remaining <= 0:
                for event_name, payload in max_duration_events_factory():
                    yield _sse(event_name, payload)
                return

            wait_timeout = min(idle_timeout_seconds, remaining)
            try:
                event_name, payload = await asyncio.wait_for(iterator.__anext__(), timeout=wait_timeout)
            except StopAsyncIteration:
                return
            except asyncio.TimeoutError:
                elapsed = loop.time() - started_at
                if elapsed >= max_duration_seconds:
                    timeout_events = max_duration_events_factory()
                else:
                    timeout_events = idle_events_factory()
                for timeout_event_name, timeout_payload in timeout_events:
                    yield _sse(timeout_event_name, timeout_payload)
                return

            yield _sse(event_name, payload)
    except Exception as exc:
        for event_name, payload in exception_events_factory(exc):
            yield _sse(event_name, payload)
    finally:
        await _close_async_iterator(iterator)


_DEVICE_ID_RE = re.compile(r"^[a-zA-Z0-9_\-]+$")
_DEVICE_ID_MAX_LEN = 128


def _get_device_id(request: Request) -> str:
    raw = request.headers.get("x-device-id", "").strip()
    if not raw:
        raise HTTPException(status_code=400, detail="X-Device-Id header is required")
    if len(raw) > _DEVICE_ID_MAX_LEN or not _DEVICE_ID_RE.match(raw):
        raise HTTPException(status_code=400, detail="Invalid device ID")
    return raw


def _thread_metadata_for_request(
    request: Request,
    assistant_id: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    merged = dict(metadata or {})
    merged["graph_id"] = assistant_id
    merged["device_id"] = _get_device_id(request)
    return merged


def _thread_metadata(state: dict[str, Any] | None) -> dict[str, Any]:
    if not isinstance(state, dict):
        return {}
    metadata = state.get("metadata", {})
    return metadata if isinstance(metadata, dict) else {}


def _thread_exists(state: dict[str, Any] | None) -> bool:
    if not isinstance(state, dict):
        return False
    return bool(state.get("created_at") or _thread_metadata(state) or state.get("values"))


def _get_owned_thread_state(
    rt: AdmissionGraphRuntime,
    request: Request,
    thread_id: str,
) -> dict[str, Any]:
    state = rt.get_thread_state(thread_id=thread_id)
    if not _thread_exists(state):
        raise HTTPException(status_code=404, detail="Thread not found")

    metadata = _thread_metadata(state)
    if metadata.get("device_id") != _get_device_id(request):
        raise HTTPException(status_code=404, detail="Thread not found")

    return state


def _assert_thread_create_allowed(
    rt: AdmissionGraphRuntime,
    request: Request,
    thread_id: str,
) -> None:
    state = rt.get_thread_state(thread_id=thread_id)
    if not _thread_exists(state):
        return

    metadata = _thread_metadata(state)
    if metadata.get("device_id") != _get_device_id(request):
        raise HTTPException(status_code=404, detail="Thread not found")


def _stringify_message_content(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if not isinstance(item, dict):
                continue
            if item.get("type") == "text":
                text = str(item.get("text", "")).strip()
                if text:
                    parts.append(text)
                continue
            text = str(item.get("content", "")).strip()
            if text:
                parts.append(text)
        return " ".join(part for part in parts if part).strip()
    if isinstance(content, dict):
        text = str(content.get("text") or content.get("content") or "").strip()
        if text:
            return text
    return str(content or "").strip()


def _messages_from_state(state: dict[str, Any] | None) -> list[dict[str, Any]]:
    if not isinstance(state, dict):
        return []
    values = state.get("values", {})
    if not isinstance(values, dict):
        return []
    messages = values.get("messages", [])
    if not isinstance(messages, list):
        return []
    return [msg for msg in messages if isinstance(msg, dict)]


def _message_role(message_type: str) -> str:
    normalized = str(message_type or "").strip().lower()
    if normalized in {"human", "user"}:
        return "user"
    if normalized in {"ai", "assistant"}:
        return "assistant"
    if normalized == "tool":
        return "tool"
    if normalized == "system":
        return "system"
    return normalized or "unknown"


def _conversation_title(messages: list[dict[str, Any]], fallback: str) -> str:
    for message in messages:
        if _message_role(str(message.get("type", ""))) != "user":
            continue
        text = _stringify_message_content(message.get("content"))
        if text:
            return text[:80]
    return fallback


def _conversation_preview(messages: list[dict[str, Any]]) -> str:
    for message in reversed(messages):
        text = _stringify_message_content(message.get("content"))
        if text:
            return text[:140]
    return ""


def _normalize_admin_message(message: dict[str, Any], index: int) -> dict[str, Any]:
    message_type = str(message.get("type", "")).strip().lower()
    return {
        "id": message.get("id") or f"message-{index}",
        "index": index,
        "type": message_type or "unknown",
        "role": _message_role(message_type),
        "text": _stringify_message_content(message.get("content")),
        "content": message.get("content"),
    }


def _admin_thread_summary(thread: dict[str, Any]) -> dict[str, Any]:
    messages = _messages_from_state(thread)
    metadata = thread.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    normalized_messages = [
        _normalize_admin_message(message, index)
        for index, message in enumerate(messages)
    ]
    return {
        "thread_id": thread.get("thread_id"),
        "user_id": str(metadata.get("device_id") or "unknown"),
        "assistant_id": str(metadata.get("graph_id") or "agent"),
        "created_at": thread.get("created_at"),
        "updated_at": thread.get("updated_at") or thread.get("state_updated_at"),
        "title": _conversation_title(messages, str(thread.get("thread_id") or "未命名会话")),
        "preview": _conversation_preview(messages),
        "message_count": len(normalized_messages),
        "user_message_count": sum(1 for item in normalized_messages if item["role"] == "user"),
        "assistant_message_count": sum(1 for item in normalized_messages if item["role"] == "assistant"),
        "metadata": metadata,
    }


def _build_admin_conversation_overview(
    threads: list[dict[str, Any]],
    *,
    total_threads: int,
    total_users: int,
    limit: int,
    offset: int,
) -> dict[str, Any]:
    grouped_users: dict[str, dict[str, Any]] = {}
    total_messages = 0

    for thread in threads:
        summary = _admin_thread_summary(thread)
        user_id = summary["user_id"]
        user_entry = grouped_users.setdefault(
            user_id,
            {
                "user_id": user_id,
                "thread_count": 0,
                "message_count": 0,
                "last_active_at": summary["updated_at"],
                "threads": [],
            },
        )
        user_entry["thread_count"] += 1
        user_entry["message_count"] += int(summary["message_count"])
        total_messages += int(summary["message_count"])

        last_active_at = str(user_entry.get("last_active_at") or "")
        updated_at = str(summary.get("updated_at") or "")
        if updated_at > last_active_at:
            user_entry["last_active_at"] = updated_at

        user_entry["threads"].append(summary)

    users = list(grouped_users.values())
    for user_entry in users:
        user_entry["threads"].sort(
            key=lambda item: str(item.get("updated_at") or ""),
            reverse=True,
        )

    users.sort(key=lambda item: str(item.get("last_active_at") or ""), reverse=True)

    return {
        "users": users,
        "stats": {
            "user_count": len(users),
            "thread_count": len(threads),
            "message_count": total_messages,
        },
        "totals": {
            "user_count": total_users,
            "thread_count": total_threads,
        },
        "pagination": {
            "limit": limit,
            "offset": offset,
            "page": (offset // limit) + 1 if limit > 0 else 1,
            "page_count": ((total_threads - 1) // limit) + 1 if limit > 0 and total_threads > 0 else 1,
            "has_prev": offset > 0,
            "has_next": offset + len(threads) < total_threads,
        },
    }


def _build_admin_conversation_detail(
    *,
    thread_id: str,
    thread: dict[str, Any],
) -> dict[str, Any]:
    metadata = thread.get("metadata", {})
    metadata = metadata if isinstance(metadata, dict) else {}
    messages = [
        _normalize_admin_message(message, index)
        for index, message in enumerate(_messages_from_state(thread))
    ]
    return {
        "thread_id": thread_id,
        "user_id": str(metadata.get("device_id") or "unknown"),
        "assistant_id": str(metadata.get("graph_id") or "agent"),
        "created_at": thread.get("created_at"),
        "updated_at": thread.get("updated_at") or thread.get("state_updated_at"),
        "title": _conversation_title(_messages_from_state(thread), thread_id),
        "message_count": len(messages),
        "metadata": metadata,
        "messages": messages,
    }


def create_app() -> FastAPI:
    app = FastAPI(title="AlayaAgent Chat API", version="0.2.0")

    cors_origins_raw = os.getenv("CORS_ALLOWED_ORIGINS", "").strip()
    if cors_origins_raw:
        origins = [o.strip() for o in cors_origins_raw.split(",") if o.strip()]
        if origins:
            app.add_middleware(
                CORSMiddleware,
                allow_origins=origins,
                allow_credentials=False,
                allow_methods=["GET", "POST", "OPTIONS"],
                allow_headers=["Content-Type", "X-Device-Id"],
            )

    repo_root = _repo_root()
    env_file = repo_root / ".env"
    runtime = AdmissionGraphRuntime(
        RuntimeConfig(
            repo_root=repo_root,
            env_file=env_file,
        )
    )
    app.state.runtime = runtime
    app.state.startup_error = None
    app.state.api_shared_key = ""
    app.state.thread_run_leases = _ThreadRunLeaseRegistry()
    app.state.stream_idle_timeout_seconds = _read_positive_float_env(
        "STREAM_IDLE_TIMEOUT_SECONDS",
        30.0,
    )
    app.state.stream_max_duration_seconds = _read_positive_float_env(
        "STREAM_MAX_DURATION_SECONDS",
        120.0,
    )
    app.state.device_rate_limiter = _DeviceRateLimiter(
        max_requests=int(os.getenv("DEVICE_RATE_LIMIT_MAX", "30")),
        window_seconds=float(os.getenv("DEVICE_RATE_LIMIT_WINDOW", "60")),
    )

    def _runtime_or_503() -> AdmissionGraphRuntime:
        if app.state.startup_error is not None:
            raise HTTPException(status_code=503, detail="Service unavailable")
        return app.state.runtime

    @app.on_event("startup")
    async def _startup() -> None:
        app.state.api_shared_key = os.getenv("API_SHARED_KEY", "").strip()
        try:
            await runtime.startup()
            app.state.startup_error = None
        except Exception as exc:
            app.state.startup_error = exc

    @app.on_event("shutdown")
    async def _shutdown() -> None:
        await runtime.shutdown()

    @app.middleware("http")
    async def limit_request_body(request: Request, call_next):
        cl = request.headers.get("content-length")
        if cl:
            try:
                if int(cl) > _MAX_REQUEST_BODY_BYTES:
                    return JSONResponse(
                        status_code=413,
                        content={"detail": "Request body too large"},
                    )
            except ValueError:
                pass
        return await call_next(request)

    @app.middleware("http")
    async def require_shared_key(request: Request, call_next):
        shared_key = app.state.api_shared_key
        if not shared_key:
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        if request.url.path in {"/health", "/info", "/metrics"} or request.url.path.startswith("/wx"):
            return await call_next(request)

        if request.headers.get("x-api-key", "") != shared_key:
            return JSONResponse(
                status_code=401,
                content={"detail": "Unauthorized"},
            )

        return await call_next(request)

    @app.middleware("http")
    async def enforce_device_rate_limit(request: Request, call_next):
        if request.method == "OPTIONS":
            return await call_next(request)
        if request.url.path in {"/health", "/info", "/metrics"} or request.url.path.startswith("/wx"):
            return await call_next(request)
        device_id = request.headers.get("x-device-id", "").strip()
        if device_id and not await app.state.device_rate_limiter.check(device_id):
            return JSONResponse(
                status_code=429,
                content={"detail": "Too many requests"},
            )
        return await call_next(request)

    @app.get("/health")
    def health() -> JSONResponse:
        runtime_ready = app.state.startup_error is None
        return JSONResponse(
            status_code=200 if runtime_ready else 503,
            content={
                "ok": runtime_ready,
                "runtime_ready": runtime_ready,
            },
        )

    @app.get("/info")
    def info() -> dict[str, Any]:
        return {
            "name": "alayagent-langgraph-compat",
            "version": "0.2.0",
            "runtime_ready": app.state.startup_error is None,
            "assistant_id": "agent",
            "api_key_required": bool(app.state.api_shared_key),
        }

    # ── Admin: knowledge base hot reload ──────────────────────

    _ALLOWED_INGEST_EXTENSIONS = {".md", ".txt", ".doc", ".docx", ".pdf", ".xlsx"}

    @app.get("/admin/collection/stats")
    def collection_stats() -> dict[str, Any]:
        """Return vector collection row count (no restart needed)."""
        _runtime_or_503()
        from ..knowledge.vector_manager import VectorManager
        return VectorManager().collection_stats()

    @app.post("/admin/ingest")
    async def admin_ingest(
        file: UploadFile,
        category: str | None = None,
    ) -> dict[str, Any]:
        """Ingest a file into the vector store without restarting the service.

        Requires X-API-Key header (same as all other endpoints).
        Accepts multipart/form-data with a single file upload.
        """
        _runtime_or_503()

        # Validate file extension
        import tempfile
        suffix = Path(file.filename or "").suffix.lower()
        if suffix not in _ALLOWED_INGEST_EXTENSIONS:
            raise HTTPException(
                status_code=400,
                detail=f"Unsupported file type '{suffix}'. Allowed: {', '.join(sorted(_ALLOWED_INGEST_EXTENSIONS))}",
            )

        # Save to temp file, run ETL → embed → insert (blocking), then clean up
        tmp_path: str | None = None
        try:
            with tempfile.NamedTemporaryFile(
                delete=False, suffix=suffix, prefix="ingest_",
            ) as tmp:
                content = await file.read()
                tmp.write(content)
                tmp_path = tmp.name

            from ..knowledge.manage import ingest_vector
            from ..knowledge.vector_manager import VectorManager

            inserted = await asyncio.to_thread(
                lambda: _run_ingest(tmp_path, category),
            )
            stats = VectorManager().collection_stats()
            _logger.info("Admin ingest: file=%s category=%s inserted=%d", file.filename, category, inserted)
            return {"inserted": inserted, "collection": stats}
        except HTTPException:
            raise
        except FileNotFoundError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        except Exception as exc:
            _logger.exception("Admin ingest failed: %s", exc)
            raise HTTPException(status_code=500, detail="Ingest failed") from exc
        finally:
            if tmp_path:
                try:
                    os.unlink(tmp_path)
                except OSError:
                    pass

    @app.get("/admin/conversations")
    def admin_conversations(
        limit: int = 200,
        offset: int = 0,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        rt = _runtime_or_503()
        normalized_limit = max(1, min(limit, 1000))
        normalized_offset = max(0, offset)
        metadata = {"device_id": user_id} if user_id else None
        threads = rt.search_threads(
            metadata=metadata,
            limit=normalized_limit,
            offset=normalized_offset,
        )
        return _build_admin_conversation_overview(
            threads,
            total_threads=rt.count_threads(metadata=metadata),
            total_users=rt.count_distinct_thread_metadata_values(
                metadata_key="device_id",
                metadata_filter=metadata,
            ),
            limit=normalized_limit,
            offset=normalized_offset,
        )

    @app.get("/admin/conversations/{thread_id}")
    def admin_conversation_detail(thread_id: str) -> dict[str, Any]:
        rt = _runtime_or_503()
        state = rt.get_thread_state(thread_id=thread_id)
        if not _thread_exists(state):
            raise HTTPException(status_code=404, detail="Thread not found")

        registry_row = rt.get_registry_thread(thread_id=thread_id)
        if isinstance(registry_row, dict):
            enriched_thread = {
                "thread_id": thread_id,
                "created_at": registry_row.get("created_at"),
                "updated_at": registry_row.get("updated_at"),
                "state_updated_at": state.get("created_at"),
                "metadata": _thread_metadata(state),
                "values": state.get("values", {}) if isinstance(state.get("values"), dict) else {},
            }
        else:
            enriched_thread = {
                "thread_id": thread_id,
                "created_at": state.get("created_at"),
                "updated_at": state.get("created_at"),
                "state_updated_at": state.get("created_at"),
                "metadata": _thread_metadata(state),
                "values": state.get("values", {}) if isinstance(state.get("values"), dict) else {},
            }

        return _build_admin_conversation_detail(thread_id=thread_id, thread=enriched_thread)

    @app.delete("/admin/conversations/{thread_id}")
    async def admin_delete_conversation(thread_id: str) -> dict[str, Any]:
        rt = _runtime_or_503()
        lease_registry: _ThreadRunLeaseRegistry = app.state.thread_run_leases
        if await lease_registry.is_active(thread_id):
            raise HTTPException(
                status_code=409,
                detail="Thread is currently running and cannot be deleted",
            )

        deleted = await asyncio.to_thread(rt.delete_thread, thread_id=thread_id)
        if not bool(deleted.get("existed")):
            raise HTTPException(status_code=404, detail="Thread not found")

        _logger.info("Admin deleted thread %s: %s", thread_id, deleted)
        return {
            "ok": True,
            "thread_id": thread_id,
            "deleted": deleted,
        }

    def _run_ingest(file_path: str, category: str | None) -> int:
        """Synchronous wrapper — called via asyncio.to_thread."""
        from ..knowledge.manage import ingest_vector
        return ingest_vector(file_path, category)

    # ── End admin endpoints ───────────────────────────────────

    @app.exception_handler(Exception)
    async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        _logger.exception("Unhandled exception on %s %s", request.method, request.url.path)
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    @app.post("/threads")
    def create_thread(req: ThreadCreateRequest, request: Request) -> dict[str, Any]:
        rt = _runtime_or_503()
        thread_id = (req.thread_id or "").strip() or None
        if thread_id is not None:
            _assert_thread_create_allowed(rt, request, thread_id)
        metadata = _thread_metadata_for_request(request, "agent", req.metadata)
        return rt.create_thread(thread_id=thread_id, metadata=metadata)

    @app.get("/threads/{thread_id}")
    def get_thread(thread_id: str, request: Request) -> dict[str, Any]:
        rt = _runtime_or_503()
        state = _get_owned_thread_state(rt, request, thread_id)
        get_registry_thread = getattr(rt, "get_registry_thread", None)
        registry_row = (
            get_registry_thread(thread_id=thread_id)
            if callable(get_registry_thread)
            else None
        )
        created_at = (
            registry_row.get("created_at")
            if isinstance(registry_row, dict)
            else state.get("created_at")
        )
        updated_at = (
            registry_row.get("updated_at")
            if isinstance(registry_row, dict)
            else state.get("created_at")
        )
        state_updated_at = state.get("created_at") or updated_at
        return {
            "thread_id": thread_id,
            "created_at": created_at,
            "updated_at": updated_at,
            "state_updated_at": state_updated_at,
            "metadata": _thread_metadata(state),
            "status": "idle",
            "values": state.get("values", {}) if isinstance(state.get("values"), dict) else {},
            "interrupts": {},
        }

    @app.post("/threads/search")
    def search_threads(req: ThreadSearchRequest, request: Request) -> list[dict[str, Any]]:
        rt = _runtime_or_503()
        metadata = dict(req.metadata or {})
        metadata["device_id"] = _get_device_id(request)
        return rt.search_threads(metadata=metadata, limit=req.limit, offset=req.offset)

    @app.get("/threads/{thread_id}/state")
    def get_thread_state(thread_id: str, request: Request) -> dict[str, Any]:
        rt = _runtime_or_503()
        _get_owned_thread_state(rt, request, thread_id)
        return rt.get_thread_state(thread_id=thread_id)

    @app.post("/threads/{thread_id}/history")
    def get_thread_history(
        thread_id: str,
        req: ThreadHistoryRequest,
        request: Request,
    ) -> list[dict[str, Any]]:
        rt = _runtime_or_503()
        _get_owned_thread_state(rt, request, thread_id)
        return rt.get_thread_history(thread_id=thread_id, limit=req.limit)

    @app.post("/threads/{thread_id}/runs/stream")
    async def stream_run_with_thread(
        thread_id: str,
        req: RunStreamRequest,
        request: Request,
    ) -> StreamingResponse:
        rt = _runtime_or_503()
        assistant_id = (req.assistant_id or "agent").strip() or "agent"
        metadata = _thread_metadata_for_request(request, assistant_id, req.metadata)
        await asyncio.to_thread(_get_owned_thread_state, rt, request, thread_id)
        lease_registry: _ThreadRunLeaseRegistry = app.state.thread_run_leases
        if not await lease_registry.try_acquire(thread_id):
            return JSONResponse(
                status_code=409,
                content={
                    "code": "THREAD_BUSY",
                    "message": "A run is already active for this thread",
                },
            )
        rt.create_thread(thread_id=thread_id, metadata=metadata)
        run_id, event_source = rt.stream_langgraph_events(
            thread_id=thread_id,
            input_payload=req.input,
            stream_mode=req.stream_mode,
        )
        idle_timeout_seconds = app.state.stream_idle_timeout_seconds
        max_duration_seconds = app.state.stream_max_duration_seconds

        async def event_iter() -> AsyncIterator[str]:
            try:
                async for chunk in _guard_sse_events(
                    event_source,
                    idle_timeout_seconds=idle_timeout_seconds,
                    max_duration_seconds=max_duration_seconds,
                    idle_events_factory=lambda: [
                        (
                            "error",
                            _timeout_error_payload(
                                timeout_kind="stream_idle_timeout",
                                message="Stream closed after "
                                f"{_format_seconds(idle_timeout_seconds)}s without events",
                            ),
                        )
                    ],
                    max_duration_events_factory=lambda: [
                        (
                            "error",
                            _timeout_error_payload(
                                timeout_kind="stream_max_duration_timeout",
                                message="Stream exceeded max duration of "
                                f"{_format_seconds(max_duration_seconds)}s",
                            ),
                        )
                    ],
                    exception_events_factory=lambda exc: [
                        (
                            "error",
                            _error_payload(exc),
                        )
                    ],
                ):
                    yield chunk
            finally:
                await lease_registry.release(thread_id)

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Location": f"/threads/{thread_id}/runs/{run_id}",
        }
        return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)

    @app.post("/runs/stream")
    async def stream_run_without_thread(
        req: RunStreamRequest,
        request: Request,
    ) -> StreamingResponse:
        rt = _runtime_or_503()
        assistant_id = (req.assistant_id or "agent").strip() or "agent"
        thread = rt.create_thread(
            thread_id=str(uuid4()),
            metadata=_thread_metadata_for_request(request, assistant_id, req.metadata),
        )
        thread_id = str(thread["thread_id"])
        run_id, event_source = rt.stream_langgraph_events(
            thread_id=thread_id,
            input_payload=req.input,
            stream_mode=req.stream_mode,
        )
        idle_timeout_seconds = app.state.stream_idle_timeout_seconds
        max_duration_seconds = app.state.stream_max_duration_seconds

        async def event_iter() -> AsyncIterator[str]:
            async for chunk in _guard_sse_events(
                event_source,
                idle_timeout_seconds=idle_timeout_seconds,
                max_duration_seconds=max_duration_seconds,
                idle_events_factory=lambda: [
                    (
                        "error",
                        _timeout_error_payload(
                            timeout_kind="stream_idle_timeout",
                            message="Stream closed after "
                            f"{_format_seconds(idle_timeout_seconds)}s without events",
                        ),
                    )
                ],
                max_duration_events_factory=lambda: [
                    (
                        "error",
                        _timeout_error_payload(
                            timeout_kind="stream_max_duration_timeout",
                            message="Stream exceeded max duration of "
                            f"{_format_seconds(max_duration_seconds)}s",
                        ),
                    )
                ],
                exception_events_factory=lambda exc: [
                    (
                        "error",
                        _error_payload(exc),
                    )
                ],
            ):
                yield chunk

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Location": f"/threads/{thread_id}/runs/{run_id}",
        }
        return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)

    @app.post("/api/chat/stream")
    async def chat_stream(req: ChatStreamRequest) -> StreamingResponse:
        rt = _runtime_or_503()
        session_id = req.session_id.strip()
        message = req.message.strip()
        trace_id = (req.trace_id or "").strip()
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")
        idle_timeout_seconds = app.state.stream_idle_timeout_seconds
        max_duration_seconds = app.state.stream_max_duration_seconds

        async def event_source() -> AsyncIterator[tuple[str, Any]]:
            async for evt in rt.stream_stage_events(session_id=session_id, message=message):
                data = dict(evt["data"])
                if trace_id:
                    data["trace_id"] = trace_id
                yield evt["event"], data

        async def event_iter() -> AsyncIterator[str]:
            async for chunk in _guard_sse_events(
                event_source(),
                idle_timeout_seconds=idle_timeout_seconds,
                max_duration_seconds=max_duration_seconds,
                idle_events_factory=lambda: [
                    (
                        "error",
                        _timeout_error_payload(
                            timeout_kind="stream_idle_timeout",
                            message="Stream closed after "
                            f"{_format_seconds(idle_timeout_seconds)}s without events",
                            session_id=session_id,
                        ),
                    ),
                    ("done", {"session_id": session_id}),
                ],
                max_duration_events_factory=lambda: [
                    (
                        "error",
                        _timeout_error_payload(
                            timeout_kind="stream_max_duration_timeout",
                            message="Stream exceeded max duration of "
                            f"{_format_seconds(max_duration_seconds)}s",
                            session_id=session_id,
                        ),
                    ),
                    ("done", {"session_id": session_id}),
                ],
                exception_events_factory=lambda exc: [
                    (
                        "error",
                        (
                            {
                                "code": "RUNTIME_NOT_READY",
                                "message": "服务正在启动，请稍后重试。",
                                "session_id": session_id,
                            }
                            if isinstance(exc, RuntimeError)
                            else {
                                **_error_payload(exc),
                                "session_id": session_id,
                            }
                        ),
                    ),
                    ("done", {"session_id": session_id}),
                ],
            ):
                yield chunk

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)


    # ── WeChat Official Account adapter ───────────────────────
    if os.getenv("WECHAT_ENABLED", "").strip().lower() in ("1", "true", "yes"):
        from .wechat import mount_wechat_routes
        wx_router = mount_wechat_routes(app.state)
        app.include_router(wx_router)
        _logger.info("WeChat adapter enabled — /wx endpoints registered")
    # Observability must be attached last — Starlette runs last-registered
    # middleware first, so access log wraps everything.
    from .observability import attach_observability
    attach_observability(app)

    return app


app = create_app()
