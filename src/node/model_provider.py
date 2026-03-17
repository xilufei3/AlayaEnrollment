from __future__ import annotations

import json
from typing import Any

from langchain_community.document_compressors import JinaRerank
from langchain_openai import ChatOpenAI

from .model_config import MODEL_KIND_ALIASES, build_model_configs


_MODEL_CACHE: dict[tuple[str, str], Any] = {}


def reset_model_cache() -> None:
    _MODEL_CACHE.clear()


def _freeze_overrides(overrides: dict[str, Any]) -> str:
    if not overrides:
        return ""
    return json.dumps(overrides, sort_keys=True, default=str)


def _resolve_kind(kind: str) -> str:
    resolved = MODEL_KIND_ALIASES.get(kind, kind)
    if resolved not in build_model_configs():
        supported = ", ".join(sorted(build_model_configs().keys()))
        raise KeyError(f"Unknown model kind '{kind}'. Supported kinds: {supported}")
    return resolved


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
    resolved_kind = _resolve_kind(kind)
    cache_key = (resolved_kind, _freeze_overrides(overrides))
    if cache_key in _MODEL_CACHE:
        return _MODEL_CACHE[cache_key]

    spec = dict(build_model_configs()[resolved_kind])
    spec.update(overrides)
    model = _build_model(spec)
    _MODEL_CACHE[cache_key] = model
    return model
