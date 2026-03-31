from __future__ import annotations

import pytest

from src.runtime.graph_runtime import _validate_required_env_vars


def _clear_runtime_envs(monkeypatch) -> None:
    for name in (
        "RERANK_ENABLED",
        "RERANK_PROVIDER",
        "RERANK_API_KEY",
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
        "DEEPSEEK_API_KEY",
        "DEEPSEEK_BASE_URL",
        "INTENT_MODEL_API_KEY",
        "INTENT_MODEL_BASE_URL",
        "GENERATION_MODEL_API_KEY",
        "GENERATION_MODEL_BASE_URL",
        "PLANNER_MODEL_API_KEY",
        "PLANNER_MODEL_BASE_URL",
        "EVAL_MODEL_API_KEY",
        "EVAL_MODEL_BASE_URL",
        "JINA_API_KEY",
    ):
        monkeypatch.delenv(name, raising=False)


def test_validate_required_env_vars_accepts_qwen_rerank_with_qwen_api_key(monkeypatch) -> None:
    _clear_runtime_envs(monkeypatch)
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")
    monkeypatch.setenv("QWEN_BASE_URL", "https://example.local/qwen/v1")
    monkeypatch.setenv("RERANK_PROVIDER", "qwen")

    _validate_required_env_vars()


def test_validate_required_env_vars_rejects_qwen_rerank_without_any_rerank_key(monkeypatch) -> None:
    _clear_runtime_envs(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.local/deepseek/v1")
    monkeypatch.setenv("RERANK_PROVIDER", "qwen")

    with pytest.raises(RuntimeError, match="RERANK_API_KEY \\| QWEN_API_KEY"):
        _validate_required_env_vars()


def test_validate_required_env_vars_skips_rerank_key_when_rerank_disabled(monkeypatch) -> None:
    _clear_runtime_envs(monkeypatch)
    monkeypatch.setenv("DEEPSEEK_API_KEY", "deepseek-key")
    monkeypatch.setenv("DEEPSEEK_BASE_URL", "https://example.local/deepseek/v1")
    monkeypatch.setenv("RERANK_ENABLED", "false")

    _validate_required_env_vars()
