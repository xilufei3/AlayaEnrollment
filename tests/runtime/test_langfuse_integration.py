from __future__ import annotations

from src.runtime.graph_runtime import _build_langfuse_handler


def test_build_langfuse_handler_returns_callback_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("LANGFUSE_ENABLED", "true")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-test")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-test")
    monkeypatch.setenv("LANGFUSE_HOST", "https://cloud.langfuse.com")

    handler = _build_langfuse_handler(
        session_id="session-1",
        metadata={"source": "pytest"},
    )

    assert handler is not None
