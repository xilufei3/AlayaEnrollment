from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Iterator
from uuid import uuid4

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

try:
    from packages.vector_store.errors import VectorStoreError
except ModuleNotFoundError:
    class VectorStoreError(Exception):
        """Compatibility fallback when the legacy packages module is absent."""
from ..runtime.graph_runtime import AdmissionGraphRuntime, RuntimeConfig


def _sse(event: str, data: Any) -> str:
    payload = json.dumps(data, ensure_ascii=False)
    return f"event: {event}\ndata: {payload}\n\n"


class ChatStreamRequest(BaseModel):
    session_id: str = Field(..., min_length=8, max_length=128)
    message: str = Field(..., min_length=1, max_length=4000)
    trace_id: str | None = Field(default=None, max_length=128)


class ThreadCreateRequest(BaseModel):
    thread_id: str | None = None
    metadata: dict[str, Any] | None = None
    if_exists: str | None = None


class ThreadSearchRequest(BaseModel):
    metadata: dict[str, Any] | None = None
    limit: int = 10
    offset: int = 0


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


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[2]


def _error_code(exc: Exception) -> str:
    if isinstance(exc, VectorStoreError):
        return "VECTOR_STORE_ERROR"
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    if "timeout" in msg or "timeout" in name:
        return "UPSTREAM_TIMEOUT"
    if "model" in msg or "api key" in msg:
        return "MODEL_UNAVAILABLE"
    return "INTERNAL_ERROR"


def _get_device_id(request: Request) -> str:
    raw = request.headers.get("x-device-id", "").strip()
    return raw or "anonymous"


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


def create_app() -> FastAPI:
    app = FastAPI(title="AlayaAgent Chat API", version="0.2.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
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

    def _runtime_or_503() -> AdmissionGraphRuntime:
        if app.state.startup_error is not None:
            raise HTTPException(status_code=503, detail=str(app.state.startup_error))
        return app.state.runtime

    @app.on_event("startup")
    def _startup() -> None:
        app.state.api_shared_key = os.getenv("API_SHARED_KEY", "").strip()
        try:
            runtime.startup()
            app.state.startup_error = None
        except Exception as exc:
            app.state.startup_error = exc

    @app.on_event("shutdown")
    def _shutdown() -> None:
        runtime.shutdown()

    @app.middleware("http")
    async def require_shared_key(request: Request, call_next):
        shared_key = app.state.api_shared_key
        if not shared_key:
            return await call_next(request)

        if request.method == "OPTIONS":
            return await call_next(request)

        if request.url.path in {"/health", "/info"}:
            return await call_next(request)

        if request.headers.get("x-api-key", "") != shared_key:
            return JSONResponse(status_code=401, content={"detail": "Unauthorized"})

        return await call_next(request)

    @app.get("/health")
    def health() -> dict[str, Any]:
        out: dict[str, Any] = {"ok": True, "runtime_ready": app.state.startup_error is None}
        if app.state.startup_error is not None:
            out["startup_error"] = str(app.state.startup_error)
        return out

    @app.get("/info")
    def info() -> dict[str, Any]:
        return {
            "name": "alayagent-langgraph-compat",
            "version": "0.2.0",
            "runtime_ready": app.state.startup_error is None,
            "assistant_id": "agent",
        }

    @app.post("/threads")
    def create_thread(req: ThreadCreateRequest, request: Request) -> dict[str, Any]:
        rt = _runtime_or_503()
        metadata = _thread_metadata_for_request(request, "agent", req.metadata)
        return rt.create_thread(thread_id=req.thread_id, metadata=metadata)

    @app.get("/threads/{thread_id}")
    def get_thread(thread_id: str, request: Request) -> dict[str, Any]:
        rt = _runtime_or_503()
        state = _get_owned_thread_state(rt, request, thread_id)
        return {
            "thread_id": thread_id,
            "created_at": state.get("created_at"),
            "updated_at": state.get("created_at"),
            "state_updated_at": state.get("created_at"),
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
    def stream_run_with_thread(
        thread_id: str,
        req: RunStreamRequest,
        request: Request,
    ) -> StreamingResponse:
        rt = _runtime_or_503()
        assistant_id = (req.assistant_id or "agent").strip() or "agent"
        metadata = _thread_metadata_for_request(request, assistant_id, req.metadata)
        _get_owned_thread_state(rt, request, thread_id)
        rt.create_thread(thread_id=thread_id, metadata=metadata)
        run_id, event_source = rt.stream_langgraph_events(
            thread_id=thread_id,
            input_payload=req.input,
            stream_mode=req.stream_mode,
        )

        def event_iter() -> Iterator[str]:
            try:
                for event_name, payload in event_source:
                    yield _sse(event_name, payload)
            except Exception as exc:
                yield _sse("error", {"code": _error_code(exc), "message": str(exc)})

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Location": f"/threads/{thread_id}/runs/{run_id}",
        }
        return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)

    @app.post("/runs/stream")
    def stream_run_without_thread(
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

        def event_iter() -> Iterator[str]:
            try:
                for event_name, payload in event_source:
                    yield _sse(event_name, payload)
            except Exception as exc:
                yield _sse("error", {"code": _error_code(exc), "message": str(exc)})

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "Content-Location": f"/threads/{thread_id}/runs/{run_id}",
        }
        return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)

    @app.post("/api/chat/stream")
    def chat_stream(req: ChatStreamRequest) -> StreamingResponse:
        rt = _runtime_or_503()
        session_id = req.session_id.strip()
        message = req.message.strip()
        trace_id = (req.trace_id or "").strip()
        if not session_id:
            raise HTTPException(status_code=400, detail="session_id is required")
        if not message:
            raise HTTPException(status_code=400, detail="message is required")

        def event_iter() -> Iterator[str]:
            try:
                for evt in rt.stream_stage_events(session_id=session_id, message=message):
                    data = dict(evt["data"])
                    if trace_id:
                        data["trace_id"] = trace_id
                    yield _sse(evt["event"], data)
            except RuntimeError as exc:
                yield _sse(
                    "error",
                    {"code": "RUNTIME_NOT_READY", "message": str(exc), "session_id": session_id},
                )
                yield _sse("done", {"session_id": session_id})
            except Exception as exc:
                yield _sse(
                    "error",
                    {"code": _error_code(exc), "message": str(exc), "session_id": session_id},
                )
                yield _sse("done", {"session_id": session_id})

        headers = {
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        }
        return StreamingResponse(event_iter(), media_type="text/event-stream", headers=headers)

    return app


app = create_app()
