from __future__ import annotations

import os
from typing import Any


DEFAULT_QWEN_BASE_URL = "http://star.sustech.edu.cn/service/model/qwen35/v1"
DEFAULT_QWEN_MODEL_NAME = "qwen3"
DEFAULT_JINA_MODEL_NAME = "jina-reranker-v3"

DISABLE_THINKING_EXTRA_BODY: dict[str, Any] = {
    "chat_template_kwargs": {"enable_thinking": False},
}

MODEL_KIND_ALIASES: dict[str, str] = {
    "qwen3-chat": "generation",
    "deepseek-chat": "generation",
    "deepseek-intent": "intent",
    "jina-reranker": "rerank",
}


def _env_str(name: str, default: str) -> str:
    value = os.getenv(name)
    return value.strip() if value and value.strip() else default


def _env_float(name: str, default: float) -> float:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return float(value)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    value = os.getenv(name)
    if value is None or not value.strip():
        return default
    try:
        return int(value)
    except ValueError:
        return default


def _build_openai_spec(
    *,
    prefix: str,
    default_temperature: float,
    default_max_tokens: int | None = None,
    disable_thinking: bool = True,
) -> dict[str, Any]:
    base_url = _env_str(f"{prefix}_BASE_URL", _env_str("QWEN_BASE_URL", DEFAULT_QWEN_BASE_URL))
    api_key = _env_str(f"{prefix}_API_KEY", _env_str("QWEN_API_KEY", "placeholder"))
    model_name = _env_str(f"{prefix}_MODEL_NAME", _env_str("QWEN_MODEL_NAME", DEFAULT_QWEN_MODEL_NAME))
    max_tokens = _env_int(f"{prefix}_MAX_TOKENS", default_max_tokens or 0)

    spec: dict[str, Any] = {
        "provider": "openai",
        "model": model_name,
        "openai_api_base": base_url,
        "openai_api_key": api_key,
        "temperature": _env_float(f"{prefix}_TEMPERATURE", default_temperature),
    }
    if max_tokens > 0:
        spec["max_tokens"] = max_tokens
    if disable_thinking:
        spec["extra_body"] = dict(DISABLE_THINKING_EXTRA_BODY)
    return spec


def build_model_configs() -> dict[str, dict[str, Any]]:
    return {
        "intent": _build_openai_spec(
            prefix="INTENT_MODEL",
            default_temperature=0.0,
            default_max_tokens=512,
        ),
        "generation": _build_openai_spec(
            prefix="GENERATION_MODEL",
            default_temperature=0.3,
            default_max_tokens=2048,
        ),
        "planner": _build_openai_spec(
            prefix="PLANNER_MODEL",
            default_temperature=0.0,
            default_max_tokens=1024,
        ),
        "eval": _build_openai_spec(
            prefix="EVAL_MODEL",
            default_temperature=0.0,
            default_max_tokens=1024,
        ),
        "rerank": {
            "provider": "jina",
            "model": _env_str("RERANK_MODEL_NAME", _env_str("JINA_MODEL_NAME", DEFAULT_JINA_MODEL_NAME)),
            "jina_api_key": _env_str("JINA_API_KEY", "placeholder"),
            "top_n": _env_int("RERANK_TOP_N", 5),
        },
    }
