from __future__ import annotations

from copy import deepcopy
import json
import os
from threading import Lock
from typing import Any

from langchain_community.document_compressors import JinaRerank
from langchain_openai import ChatOpenAI


DEFAULT_QWEN_BASE_URL = "http://star.sustech.edu.cn/service/model/qwen35/v1"
DEFAULT_QWEN_MODEL_NAME = "qwen3"
DEFAULT_JINA_MODEL_NAME = "jina-reranker-v3"
DEFAULT_MODEL_KIND = "generation"

DISABLE_THINKING_EXTRA_BODY: dict[str, Any] = {
    "chat_template_kwargs": {"enable_thinking": False},
}

MODEL_KIND_ALIASES: dict[str, str] = {
    "qwen3-chat": "generation",
    "deepseek-chat": "generation",
    "deepseek-intent": "intent",
    "jina-reranker": "rerank",
}

# Graph node names -> model kinds used by the current workflow.
NODE_MODEL_KIND_MAP: dict[str, str] = {
    "intent_classify": "intent",
    "intent_classifier": "intent",
    "generate": "generation",
    "generation": "generation",
    "search_planner": "planner",
    "planner": "planner",
    "eval": "eval",
    "sufficiency_eval": "eval",
    "rerank": "rerank",
}

_MODEL_CACHE: dict[tuple[str, str], Any] = {}
_MODEL_CACHE_LOCK = Lock()
_MODEL_CONFIGS_CACHE: dict[str, dict[str, Any]] | None = None
_MODEL_CONFIGS_LOCK = Lock()


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


def _build_model_configs_from_env() -> dict[str, dict[str, Any]]:
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


def _get_cached_model_configs() -> dict[str, dict[str, Any]]:
    global _MODEL_CONFIGS_CACHE

    cached = _MODEL_CONFIGS_CACHE
    if cached is not None:
        return cached

    with _MODEL_CONFIGS_LOCK:
        cached = _MODEL_CONFIGS_CACHE
        if cached is None:
            cached = _build_model_configs_from_env()
            _MODEL_CONFIGS_CACHE = cached
    return cached


def build_model_configs() -> dict[str, dict[str, Any]]:
    return deepcopy(_get_cached_model_configs())


def get_model_configs() -> dict[str, dict[str, Any]]:
    return build_model_configs()


def reset_model_cache() -> None:
    global _MODEL_CONFIGS_CACHE

    with _MODEL_CACHE_LOCK:
        _MODEL_CACHE.clear()
    with _MODEL_CONFIGS_LOCK:
        _MODEL_CONFIGS_CACHE = None


def _freeze_overrides(overrides: dict[str, Any]) -> str:
    if not overrides:
        return ""
    return json.dumps(overrides, sort_keys=True, default=str)


def _resolve_model_kind_only(kind: str) -> str:
    resolved = MODEL_KIND_ALIASES.get(kind, kind)
    model_configs = _get_cached_model_configs()
    if resolved not in model_configs:
        supported = ", ".join(sorted(model_configs.keys()))
        raise KeyError(f"Unknown model kind '{kind}'. Supported kinds: {supported}")
    return resolved


def resolve_model_kind(node_name_or_kind: str | None = None) -> str:
    raw_value = (node_name_or_kind or DEFAULT_MODEL_KIND).strip()
    if not raw_value:
        raw_value = DEFAULT_MODEL_KIND

    normalized = raw_value.lower().replace("-", "_")

    if normalized in NODE_MODEL_KIND_MAP:
        return NODE_MODEL_KIND_MAP[normalized]

    model_configs = _get_cached_model_configs()
    if normalized in model_configs:
        return normalized

    alias_value = MODEL_KIND_ALIASES.get(raw_value, MODEL_KIND_ALIASES.get(normalized))
    if alias_value:
        return alias_value

    supported_names = sorted(set(NODE_MODEL_KIND_MAP) | set(model_configs) | set(MODEL_KIND_ALIASES))
    supported_text = ", ".join(supported_names)
    raise KeyError(
        f"Unknown node/model '{raw_value}'. Supported names: {supported_text}"
    )


def _build_model(spec: dict[str, Any]) -> Any:
    provider = spec["provider"]
    if provider == "openai":
        return ChatOpenAI(
            model=spec["model"],
            openai_api_key=spec["openai_api_key"],
            openai_api_base=spec["openai_api_base"],
            temperature=spec.get("temperature"),
            max_tokens=spec.get("max_tokens"),
            extra_body=spec.get("extra_body"),
        )
    if provider == "jina":
        return JinaRerank(
            model=spec["model"],
            jina_api_key=spec["jina_api_key"],
            top_n=spec.get("top_n"),
        )
    raise ValueError(f"Unsupported model provider: {provider}")


def get_model(kind: str, **overrides: Any) -> Any:
    resolved_kind = _resolve_model_kind_only(kind)
    cache_key = (resolved_kind, _freeze_overrides(overrides))
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            return cached

        spec = dict(_get_cached_model_configs()[resolved_kind])
        spec.update(overrides)
        model = _build_model(spec)
        _MODEL_CACHE[cache_key] = model
        return model


def get_llm(node_name_or_kind: str | None = None, **overrides: Any) -> Any:
    model_kind = resolve_model_kind(node_name_or_kind)
    return get_model(model_kind, **overrides)


def get_llm_for_node(node_name: str, **overrides: Any) -> Any:
    return get_llm(node_name, **overrides)


__all__ = [
    "DEFAULT_JINA_MODEL_NAME",
    "DEFAULT_MODEL_KIND",
    "DEFAULT_QWEN_BASE_URL",
    "DEFAULT_QWEN_MODEL_NAME",
    "DISABLE_THINKING_EXTRA_BODY",
    "MODEL_KIND_ALIASES",
    "NODE_MODEL_KIND_MAP",
    "build_model_configs",
    "get_llm",
    "get_llm_for_node",
    "get_model",
    "get_model_configs",
    "reset_model_cache",
    "resolve_model_kind",
]
