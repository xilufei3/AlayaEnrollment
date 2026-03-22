"""
Observability: structured access logs + Prometheus metrics.

Usage in chat_app.py:
    from .observability import attach_observability
    attach_observability(app)

Prometheus metrics are optional — if `prometheus_client` is not installed,
the /metrics endpoint returns 501 and request metrics are silently skipped.
"""
from __future__ import annotations

import json
import logging
import os
import time
from typing import Any

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse, PlainTextResponse

_access_logger = logging.getLogger("alaya.access")

# ── Prometheus (optional) ────────────────────────────────────

try:
    from prometheus_client import (
        CollectorRegistry,
        Counter,
        Histogram,
        generate_latest,
    )

    _REGISTRY = CollectorRegistry()

    HTTP_REQUESTS_TOTAL = Counter(
        "http_requests_total",
        "Total HTTP requests",
        ["method", "path_template", "status"],
        registry=_REGISTRY,
    )
    HTTP_REQUEST_DURATION = Histogram(
        "http_request_duration_seconds",
        "HTTP request latency",
        ["method", "path_template"],
        buckets=(0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0, 120.0),
        registry=_REGISTRY,
    )
    LLM_REQUESTS_TOTAL = Counter(
        "llm_requests_total",
        "Total LLM model requests",
        ["model_kind", "status"],
        registry=_REGISTRY,
    )
    LLM_REQUEST_DURATION = Histogram(
        "llm_request_duration_seconds",
        "LLM request latency",
        ["model_kind"],
        buckets=(0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0),
        registry=_REGISTRY,
    )
    RETRIEVAL_REQUESTS_TOTAL = Counter(
        "retrieval_requests_total",
        "Total vector retrieval requests",
        ["mode", "status"],
        registry=_REGISTRY,
    )
    RETRIEVAL_DURATION = Histogram(
        "retrieval_duration_seconds",
        "Vector retrieval latency",
        ["mode"],
        buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
        registry=_REGISTRY,
    )
    SQL_QUERY_TOTAL = Counter(
        "sql_query_total",
        "Total SQL query requests",
        ["status"],
        registry=_REGISTRY,
    )
    SQL_QUERY_DURATION = Histogram(
        "sql_query_duration_seconds",
        "SQL query latency",
        buckets=(0.01, 0.05, 0.1, 0.25, 0.5, 1.0),
        registry=_REGISTRY,
    )
    EMBEDDING_REQUESTS_TOTAL = Counter(
        "embedding_requests_total",
        "Total embedding requests",
        ["status"],
        registry=_REGISTRY,
    )
    EMBEDDING_DURATION = Histogram(
        "embedding_duration_seconds",
        "Embedding service latency",
        buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0),
        registry=_REGISTRY,
    )
    _HAS_PROMETHEUS = True
except ImportError:
    _HAS_PROMETHEUS = False
    _REGISTRY = None
    HTTP_REQUESTS_TOTAL = None
    HTTP_REQUEST_DURATION = None
    LLM_REQUESTS_TOTAL = None
    LLM_REQUEST_DURATION = None
    RETRIEVAL_REQUESTS_TOTAL = None
    RETRIEVAL_DURATION = None
    SQL_QUERY_TOTAL = None
    SQL_QUERY_DURATION = None
    EMBEDDING_REQUESTS_TOTAL = None
    EMBEDDING_DURATION = None


def record_llm_request(
    *,
    model_kind: str,
    duration_seconds: float,
    success: bool,
) -> None:
    """Called from LLM wrapper to record model call metrics."""
    if not _HAS_PROMETHEUS:
        return
    status = "ok" if success else "error"
    LLM_REQUESTS_TOTAL.labels(model_kind=model_kind, status=status).inc()
    LLM_REQUEST_DURATION.labels(model_kind=model_kind).observe(duration_seconds)


def record_retrieval(
    *,
    mode: str,
    duration_seconds: float,
    success: bool,
) -> None:
    if not _HAS_PROMETHEUS:
        return
    RETRIEVAL_REQUESTS_TOTAL.labels(mode=mode, status="ok" if success else "error").inc()
    RETRIEVAL_DURATION.labels(mode=mode).observe(duration_seconds)


def record_sql_query(*, duration_seconds: float, success: bool) -> None:
    if not _HAS_PROMETHEUS:
        return
    SQL_QUERY_TOTAL.labels(status="ok" if success else "error").inc()
    SQL_QUERY_DURATION.observe(duration_seconds)


def record_embedding(*, duration_seconds: float, success: bool) -> None:
    if not _HAS_PROMETHEUS:
        return
    EMBEDDING_REQUESTS_TOTAL.labels(status="ok" if success else "error").inc()
    EMBEDDING_DURATION.observe(duration_seconds)


# ── Path normalization ───────────────────────────────────────

_THREAD_ID_SEGMENT = "/threads/"


def _normalize_path(path: str) -> str:
    """Replace thread IDs with {thread_id} to avoid high-cardinality labels."""
    if _THREAD_ID_SEGMENT not in path:
        return path
    parts = path.split("/")
    result = []
    for i, part in enumerate(parts):
        if i > 0 and result and result[-1] == "threads" and part:
            result.append("{thread_id}")
        else:
            result.append(part)
    return "/".join(result)


# ── Device ID masking ────────────────────────────────────────

def _mask_device_id(device_id: str) -> str:
    """Show first 8 chars, mask the rest. Enough to correlate, not to identify."""
    if len(device_id) <= 8:
        return device_id
    return device_id[:8] + "***"


# ── Wiring ───────────────────────────────────────────────────

def attach_observability(app: FastAPI) -> None:
    """Register access log middleware, /metrics endpoint, and configure logging."""

    _configure_logging()

    @app.middleware("http")
    async def access_log_and_metrics(request: Request, call_next: Any) -> Response:
        start = time.monotonic()
        response: Response | None = None
        try:
            response = await call_next(request)
            return response
        finally:
            duration = time.monotonic() - start
            status = response.status_code if response else 500
            path = request.url.path
            method = request.method
            path_template = _normalize_path(path)

            # Prometheus metrics
            if _HAS_PROMETHEUS and path != "/metrics":
                HTTP_REQUESTS_TOTAL.labels(
                    method=method,
                    path_template=path_template,
                    status=str(status),
                ).inc()
                HTTP_REQUEST_DURATION.labels(
                    method=method,
                    path_template=path_template,
                ).observe(duration)

            # Structured access log
            if path not in {"/health", "/metrics"}:
                device_id = request.headers.get("x-device-id", "")
                log_entry = {
                    "method": method,
                    "path": path,
                    "status": status,
                    "duration_ms": round(duration * 1000, 1),
                    "device_id": _mask_device_id(device_id) if device_id else "",
                    "ip": request.headers.get("x-real-ip", request.client.host if request.client else ""),
                }
                if status >= 400:
                    _access_logger.warning(json.dumps(log_entry, ensure_ascii=False))
                else:
                    _access_logger.info(json.dumps(log_entry, ensure_ascii=False))

    @app.get("/metrics")
    def metrics() -> Response:
        if not _HAS_PROMETHEUS:
            return JSONResponse(
                status_code=501,
                content={"detail": "prometheus_client not installed"},
            )
        body = generate_latest(_REGISTRY)
        return PlainTextResponse(content=body, media_type="text/plain; version=0.0.4; charset=utf-8")


# ── Logging configuration ───────────────────────────────────

def _configure_logging() -> None:
    """Set up structured JSON logging for access logs.

    Application logs (alaya.api, alaya.access) go to stderr as JSON lines.
    """
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()

    class _JsonFormatter(logging.Formatter):
        def format(self, record: logging.LogRecord) -> str:
            entry: dict[str, Any] = {
                "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
                "level": record.levelname,
                "logger": record.name,
                "msg": record.getMessage(),
            }
            if record.exc_info and record.exc_info[0] is not None:
                entry["exc"] = self.formatException(record.exc_info)
            return json.dumps(entry, ensure_ascii=False)

    handler = logging.StreamHandler()
    handler.setFormatter(_JsonFormatter())

    for name in ("alaya.api", "alaya.access"):
        logger = logging.getLogger(name)
        if not logger.handlers:
            logger.addHandler(handler)
            logger.setLevel(getattr(logging, log_level, logging.INFO))
            logger.propagate = False
