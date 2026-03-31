from __future__ import annotations

from copy import deepcopy
import json
import os
import re
import time
from threading import Lock
from typing import Any, AsyncIterator, Sequence

from langchain_community.document_compressors import JinaRerank
from langchain_core.documents import Document
from langchain_openai import ChatOpenAI
import requests


def _record_llm_ok(model_kind: str, duration: float) -> None:
    try:
        from ..api.observability import record_llm_request
        record_llm_request(model_kind=model_kind, duration_seconds=duration, success=True)
    except Exception:
        pass


def _record_llm_err(model_kind: str, duration: float) -> None:
    try:
        from ..api.observability import record_llm_request
        record_llm_request(model_kind=model_kind, duration_seconds=duration, success=False)
    except Exception:
        pass


DEFAULT_DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
DEFAULT_DEEPSEEK_MODEL_NAME = "deepseek-chat"
DEFAULT_QWEN_BASE_URL = "https://star.sustech.edu.cn/service/model/qwen/v1"
DEFAULT_QWEN_MODEL_NAME = "qwen3.5-397b-a17b-fp8"
DEFAULT_QWEN35_BASE_URL = "https://star.sustech.edu.cn/service/model/qwen35/v1"
DEFAULT_QWEN35_MODEL_NAME = "qwen3.5-35b-a3b"
DEFAULT_MIROTHINKER_BASE_URL = "https://star.sustech.edu.cn/service/model/mirothinker/v1"
DEFAULT_MIROTHINKER_MODEL_NAME = "mirothinker-1.7-235b-fp8"
DEFAULT_QWEN_RERANK_BASE_URL = (
    "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
)
DEFAULT_QWEN_RERANK_MODEL_NAME = "qwen3-rerank"
DEFAULT_JINA_MODEL_NAME = "jina-reranker-v3"
DEFAULT_MODEL_KIND = "generation"
DEFAULT_INTENT_REQUEST_TIMEOUT = 8.0
DEFAULT_GENERATION_REQUEST_TIMEOUT = 25.0
DEFAULT_PLANNER_REQUEST_TIMEOUT = 12.0
DEFAULT_EVAL_REQUEST_TIMEOUT = 8.0
DEFAULT_RERANK_REQUEST_TIMEOUT = 8.0
DEFAULT_INTENT_MAX_RETRIES = 0
DEFAULT_GENERATION_MAX_RETRIES = 0
DEFAULT_PLANNER_MAX_RETRIES = 0
DEFAULT_EVAL_MAX_RETRIES = 0
DEFAULT_RERANK_MAX_RETRIES = 0

QWEN35_DISABLE_THINKING_EXTRA_BODY: dict[str, Any] = {
    "enable_thinking": False,
    "separate_reasoning": False,
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
    "direct_reply": "generation",
    "generate": "generation",
    "generation": "generation",
    "search_planner": "planner",
    "planner": "planner",
    "eval": "eval",
    "sufficiency_eval": "eval",
    "rerank": "rerank",
}

_MODEL_CACHE: dict[tuple[str, str, str], Any] = {}
_MODEL_CACHE_LOCK = Lock()
_MODEL_CONFIGS_CACHE: dict[str, dict[str, Any]] | None = None
_MODEL_CONFIGS_LOCK = Lock()


def _format_timeout_seconds(timeout_seconds: float | None) -> str:
    if timeout_seconds is None:
        return "unknown"
    return f"{timeout_seconds:g}"


def _timeout_kind_for_model(model_kind: str) -> str:
    return f"model_{model_kind}_timeout"


class ModelRequestTimeoutError(Exception):
    def __init__(
        self,
        *,
        model_kind: str,
        provider: str,
        timeout_seconds: float | None,
    ) -> None:
        self.model_kind = model_kind
        self.provider = provider
        self.timeout_seconds = timeout_seconds
        self.timeout_kind = _timeout_kind_for_model(model_kind)
        super().__init__(
            "Upstream "
            f"{model_kind} model request timed out after "
            f"{_format_timeout_seconds(timeout_seconds)}s"
        )


def _is_timeout_exception(exc: Exception) -> bool:
    if isinstance(exc, ModelRequestTimeoutError):
        return True
    msg = str(exc).lower()
    name = type(exc).__name__.lower()
    return "timeout" in msg or "timeout" in name


class _TimeoutAwareChatModel:
    def __init__(
        self,
        *,
        inner: Any,
        model_kind: str,
        provider: str,
        timeout_seconds: float | None,
    ) -> None:
        self._inner = inner
        self._model_kind = model_kind
        self._provider = provider
        self._timeout_seconds = timeout_seconds

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _raise_timeout(self, exc: Exception) -> None:
        if _is_timeout_exception(exc):
            raise ModelRequestTimeoutError(
                model_kind=self._model_kind,
                provider=self._provider,
                timeout_seconds=self._timeout_seconds,
            ) from exc
        raise exc

    async def ainvoke(self, *args: Any, **kwargs: Any) -> Any:
        start = time.monotonic()
        try:
            result = await self._inner.ainvoke(*args, **kwargs)
            _record_llm_ok(self._model_kind, time.monotonic() - start)
            return result
        except Exception as exc:
            _record_llm_err(self._model_kind, time.monotonic() - start)
            self._raise_timeout(exc)

    async def astream(self, *args: Any, **kwargs: Any) -> AsyncIterator[Any]:
        start = time.monotonic()
        try:
            async for chunk in self._inner.astream(*args, **kwargs):
                yield chunk
            _record_llm_ok(self._model_kind, time.monotonic() - start)
        except Exception as exc:
            _record_llm_err(self._model_kind, time.monotonic() - start)
            self._raise_timeout(exc)


class _TimeoutAwareRerankModel:
    def __init__(
        self,
        *,
        inner: Any,
        model_kind: str,
        provider: str,
        timeout_seconds: float | None,
        max_retries: int,
    ) -> None:
        self._inner = inner
        self._model_kind = model_kind
        self._provider = provider
        self._timeout_seconds = timeout_seconds
        self._max_retries = max(0, int(max_retries))

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)

    def _call_with_retry(self, func: Any, /, *args: Any, **kwargs: Any) -> Any:
        attempts = self._max_retries + 1
        start = time.monotonic()
        for attempt in range(attempts):
            try:
                result = func(*args, **kwargs)
                _record_llm_ok(self._model_kind, time.monotonic() - start)
                return result
            except Exception as exc:
                if _is_timeout_exception(exc):
                    if attempt + 1 < attempts:
                        continue
                    _record_llm_err(self._model_kind, time.monotonic() - start)
                    raise ModelRequestTimeoutError(
                        model_kind=self._model_kind,
                        provider=self._provider,
                        timeout_seconds=self._timeout_seconds,
                    ) from exc
                _record_llm_err(self._model_kind, time.monotonic() - start)
                raise

        raise RuntimeError("unreachable")

    def rerank(
        self,
        documents: Sequence[str | Document | dict[str, Any]],
        query: str,
        *,
        model: str | None = None,
        top_n: int | None = -1,
        max_chunks_per_doc: int | None = None,
    ) -> list[dict[str, Any]]:
        return self._call_with_retry(
            self._inner.rerank,
            documents=documents,
            query=query,
            model=model,
            top_n=top_n,
            max_chunks_per_doc=max_chunks_per_doc,
        )

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Any | None = None,
    ) -> Sequence[Document]:
        kwargs: dict[str, Any] = {
            "documents": documents,
            "query": query,
        }
        if callbacks is not None:
            kwargs["callbacks"] = callbacks
        return self._call_with_retry(self._inner.compress_documents, **kwargs)


class _QwenRerank:
    def __init__(
        self,
        *,
        model: str,
        api_key: str,
        base_url: str,
        top_n: int | None = None,
        request_timeout: float | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._top_n = top_n
        self._request_timeout = request_timeout

    @staticmethod
    def _doc_text(doc: str | Document | dict[str, Any]) -> str:
        if isinstance(doc, Document):
            return doc.page_content
        if isinstance(doc, dict):
            return str(
                doc.get("page_content")
                or doc.get("content")
                or doc.get("text")
                or ""
            )
        return str(doc)

    def rerank(
        self,
        documents: Sequence[str | Document | dict[str, Any]],
        query: str,
        *,
        model: str | None = None,
        top_n: int | None = -1,
        max_chunks_per_doc: int | None = None,
    ) -> list[dict[str, Any]]:
        del max_chunks_per_doc

        payload: dict[str, Any] = {
            "model": model or self._model,
            "input": {
                "query": query,
                "documents": [self._doc_text(doc) for doc in documents],
            },
            "parameters": {
                "return_documents": True,
            },
        }
        resolved_top_n = top_n if top_n is not None and top_n > 0 else self._top_n
        if resolved_top_n is not None and resolved_top_n > 0:
            payload["parameters"]["top_n"] = int(resolved_top_n)

        response = requests.post(
            self._base_url,
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=self._request_timeout,
        )
        if not response.ok:
            body = response.text.strip()
            if len(body) > 500:
                body = body[:500] + "..."
            raise RuntimeError(
                f"Qwen rerank request failed with HTTP {response.status_code}: {body}"
            )

        data = response.json()
        results = data.get("output", {}).get("results")
        if not isinstance(results, list):
            raise ValueError("Qwen rerank response missing output.results")
        return list(results)

    def compress_documents(
        self,
        documents: Sequence[Document],
        query: str,
        callbacks: Any | None = None,
    ) -> Sequence[Document]:
        del callbacks

        rerank_results = self.rerank(
            documents=documents,
            query=query,
            top_n=self._top_n,
        )
        reranked_documents: list[Document] = []
        total_documents = len(documents)

        for result in rerank_results:
            index = result.get("index")
            if not isinstance(index, int) or not (0 <= index < total_documents):
                raise ValueError(f"Qwen rerank returned invalid document index: {index!r}")

            source_doc = documents[index]
            metadata = dict(source_doc.metadata)
            score = result.get("relevance_score")
            if score is not None:
                metadata.setdefault("relevance_score", score)
                metadata.setdefault("rerank_score", score)
            reranked_documents.append(
                Document(
                    page_content=source_doc.page_content,
                    metadata=metadata,
                )
            )

        return reranked_documents


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


def _env_optional_str(name: str) -> str | None:
    value = os.getenv(name)
    if value is None:
        return None
    cleaned = value.strip()
    return cleaned if cleaned else None


def _channel_env_value(*, channel: str, model_kind: str, suffix: str) -> str | None:
    channel_key = channel.strip().upper()
    kind_key = model_kind.strip().upper()
    if not channel_key:
        return None
    for env_name in (f"{channel_key}_{kind_key}_{suffix}", f"{channel_key}_{suffix}"):
        value = _env_optional_str(env_name)
        if value is not None:
            return value
    return None


def _channel_spec_overrides(
    *,
    channel: str,
    model_kind: str,
    spec: dict[str, Any],
) -> dict[str, Any]:
    normalized_channel = str(channel or "").strip().lower()
    if not normalized_channel:
        return {}

    provider = str(spec.get("provider") or "").strip().lower()
    if provider == "openai":
        overrides: dict[str, Any] = {}
        direct_map = {
            "MODEL_NAME": "model",
            "BASE_URL": "openai_api_base",
            "API_KEY": "openai_api_key",
        }
        for env_suffix, spec_key in direct_map.items():
            if value := _channel_env_value(
                channel=normalized_channel,
                model_kind=model_kind,
                suffix=env_suffix,
            ):
                overrides[spec_key] = value

        if value := _channel_env_value(
            channel=normalized_channel,
            model_kind=model_kind,
            suffix="TEMPERATURE",
        ):
            try:
                overrides["temperature"] = float(value)
            except ValueError:
                pass
        if value := _channel_env_value(
            channel=normalized_channel,
            model_kind=model_kind,
            suffix="MAX_TOKENS",
        ):
            try:
                parsed = int(value)
                if parsed > 0:
                    overrides["max_tokens"] = parsed
            except ValueError:
                pass
        if value := _channel_env_value(
            channel=normalized_channel,
            model_kind=model_kind,
            suffix="TIMEOUT_SECONDS",
        ):
            try:
                overrides["request_timeout"] = float(value)
            except ValueError:
                pass
        if value := _channel_env_value(
            channel=normalized_channel,
            model_kind=model_kind,
            suffix="MAX_RETRIES",
        ):
            try:
                parsed = int(value)
                if parsed >= 0:
                    overrides["max_retries"] = parsed
            except ValueError:
                pass
        return overrides

    if provider == "jina":
        overrides = {}
        if value := _channel_env_value(
            channel=normalized_channel,
            model_kind=model_kind,
            suffix="MODEL_NAME",
        ):
            overrides["model"] = value
        if value := _channel_env_value(
            channel=normalized_channel,
            model_kind=model_kind,
            suffix="API_KEY",
        ):
            overrides["jina_api_key"] = value
        if value := _channel_env_value(
            channel=normalized_channel,
            model_kind=model_kind,
            suffix="TOP_N",
        ):
            try:
                parsed = int(value)
                if parsed > 0:
                    overrides["top_n"] = parsed
            except ValueError:
                pass
        return overrides

    return {}


def _apply_request_budget(
    *,
    spec: dict[str, Any],
    prefix: str,
    default_request_timeout: float,
    default_max_retries: int,
) -> dict[str, Any]:
    spec["request_timeout"] = _env_float(
        f"{prefix}_TIMEOUT_SECONDS",
        default_request_timeout,
    )
    spec["max_retries"] = _env_int(
        f"{prefix}_MAX_RETRIES",
        default_max_retries,
    )
    return spec


def _normalize_model_source(raw_value: str) -> str:
    normalized = re.sub(r"[^a-z0-9]+", "_", raw_value.strip().lower())
    return re.sub(r"_+", "_", normalized).strip("_")


def _source_env_prefix(source_name: str) -> str:
    return _normalize_model_source(source_name).upper()


def _should_disable_thinking_by_default(*, model_name: str) -> bool:
    return True


def _resolve_model_source_defaults(source_name: str) -> dict[str, str]:
    normalized = _normalize_model_source(source_name)
    if not normalized:
        return {}

    if normalized == "qwen":
        return {
            "base_url": _env_str(
                "QWEN_BASE_URL",
                _env_str("DEEPSEEK_BASE_URL", DEFAULT_QWEN_BASE_URL),
            ),
            "api_key": _env_str(
                "QWEN_API_KEY",
                _env_str("DEEPSEEK_API_KEY", "placeholder"),
            ),
            "model": _env_str(
                "QWEN_MODEL_NAME",
                _env_str("DEEPSEEK_MODEL_NAME", DEFAULT_QWEN_MODEL_NAME),
            ),
        }

    if normalized == "deepseek":
        return {
            "base_url": _env_str("DEEPSEEK_BASE_URL", DEFAULT_DEEPSEEK_BASE_URL),
            "api_key": _env_str(
                "DEEPSEEK_API_KEY",
                _env_str("QWEN_API_KEY", "placeholder"),
            ),
            "model": _env_str("DEEPSEEK_MODEL_NAME", DEFAULT_DEEPSEEK_MODEL_NAME),
        }

    prefix = _source_env_prefix(normalized)

    known_defaults: dict[str, tuple[str, str]] = {
        "qwen35": (DEFAULT_QWEN35_BASE_URL, DEFAULT_QWEN35_MODEL_NAME),
        "mirothinker": (DEFAULT_MIROTHINKER_BASE_URL, DEFAULT_MIROTHINKER_MODEL_NAME),
    }
    default_base_url, default_model_name = known_defaults.get(normalized, ("", ""))

    base_url = _env_str(f"{prefix}_BASE_URL", default_base_url)
    api_key = _env_str(f"{prefix}_API_KEY", "")
    model_name = _env_str(f"{prefix}_MODEL_NAME", default_model_name)

    missing: list[str] = []
    if not base_url:
        missing.append(f"{prefix}_BASE_URL")
    if not model_name:
        missing.append(f"{prefix}_MODEL_NAME")

    if missing:
        missing_text = ", ".join(missing)
        raise ValueError(
            f"Model source '{source_name}' is selected but missing env vars: {missing_text}"
        )

    resolved = {
        "base_url": base_url,
        "model": model_name,
    }
    if api_key:
        resolved["api_key"] = api_key
    return resolved


def _build_openai_spec(
    *,
    prefix: str,
    default_temperature: float,
    default_max_tokens: int | None = None,
    default_request_timeout: float,
    default_max_retries: int,
    disable_thinking: bool = True,
) -> dict[str, Any]:
    source_defaults = _resolve_model_source_defaults(_env_str(f"{prefix}_SOURCE", ""))
    fallback_base_url = source_defaults.get(
        "base_url",
        _env_str(
            "QWEN_BASE_URL",
            _env_str("DEEPSEEK_BASE_URL", DEFAULT_QWEN_BASE_URL),
        ),
    )
    fallback_api_key = source_defaults.get(
        "api_key",
        _env_str("QWEN_API_KEY", _env_str("DEEPSEEK_API_KEY", "placeholder")),
    )
    fallback_model_name = source_defaults.get(
        "model",
        _env_str(
            "QWEN_MODEL_NAME",
            _env_str("DEEPSEEK_MODEL_NAME", DEFAULT_QWEN_MODEL_NAME),
        ),
    )
    base_url = _env_str(
        f"{prefix}_BASE_URL",
        fallback_base_url,
    )
    api_key = _env_str(
        f"{prefix}_API_KEY",
        fallback_api_key,
    )
    model_name = _env_str(
        f"{prefix}_MODEL_NAME",
        fallback_model_name,
    )
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
    needs_disable_thinking = (
        disable_thinking
        and _should_disable_thinking_by_default(model_name=spec["model"])
    )
    if needs_disable_thinking:
        spec["extra_body"] = deepcopy(QWEN35_DISABLE_THINKING_EXTRA_BODY)
    return _apply_request_budget(
        spec=spec,
        prefix=prefix,
        default_request_timeout=default_request_timeout,
        default_max_retries=default_max_retries,
    )


def _get_rerank_provider() -> str:
    return _env_str("RERANK_PROVIDER", "qwen").lower()


def _build_rerank_spec() -> dict[str, Any]:
    provider = _get_rerank_provider()
    top_n = _env_int("RERANK_TOP_N", 5)

    if provider == "qwen":
        spec = {
            "provider": "qwen",
            "model": _env_str(
                "RERANK_MODEL_NAME",
                _env_str("QWEN_RERANK_MODEL_NAME", DEFAULT_QWEN_RERANK_MODEL_NAME),
            ),
            "api_key": _env_str("RERANK_API_KEY", _env_str("QWEN_API_KEY", "placeholder")),
            "base_url": _env_str("RERANK_BASE_URL", DEFAULT_QWEN_RERANK_BASE_URL),
            "top_n": top_n,
        }
    elif provider == "jina":
        spec = {
            "provider": "jina",
            "model": _env_str(
                "RERANK_MODEL_NAME",
                _env_str("JINA_MODEL_NAME", DEFAULT_JINA_MODEL_NAME),
            ),
            "jina_api_key": _env_str("JINA_API_KEY", "placeholder"),
            "top_n": top_n,
        }
    else:
        raise ValueError(f"Unsupported rerank provider: {provider}")

    return _apply_request_budget(
        spec=spec,
        prefix="RERANK_MODEL",
        default_request_timeout=DEFAULT_RERANK_REQUEST_TIMEOUT,
        default_max_retries=DEFAULT_RERANK_MAX_RETRIES,
    )


def _build_model_configs_from_env() -> dict[str, dict[str, Any]]:
    return {
        "intent": _build_openai_spec(
            prefix="INTENT_MODEL",
            default_temperature=0.0,
            default_max_tokens=512,
            default_request_timeout=DEFAULT_INTENT_REQUEST_TIMEOUT,
            default_max_retries=DEFAULT_INTENT_MAX_RETRIES,
        ),
        "generation": _build_openai_spec(
            prefix="GENERATION_MODEL",
            default_temperature=0.3,
            default_max_tokens=2048,
            default_request_timeout=DEFAULT_GENERATION_REQUEST_TIMEOUT,
            default_max_retries=DEFAULT_GENERATION_MAX_RETRIES,
        ),
        "planner": _build_openai_spec(
            prefix="PLANNER_MODEL",
            default_temperature=0.0,
            default_max_tokens=1024,
            default_request_timeout=DEFAULT_PLANNER_REQUEST_TIMEOUT,
            default_max_retries=DEFAULT_PLANNER_MAX_RETRIES,
        ),
        "eval": _build_openai_spec(
            prefix="EVAL_MODEL",
            default_temperature=0.0,
            default_max_tokens=1024,
            default_request_timeout=DEFAULT_EVAL_REQUEST_TIMEOUT,
            default_max_retries=DEFAULT_EVAL_MAX_RETRIES,
        ),
        "rerank": _build_rerank_spec(),
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


def _build_model(*, model_kind: str, spec: dict[str, Any]) -> Any:
    provider = spec["provider"]
    if provider == "openai":
        chat_model = ChatOpenAI(
            model=spec["model"],
            openai_api_key=spec["openai_api_key"],
            openai_api_base=spec["openai_api_base"],
            temperature=spec.get("temperature"),
            max_tokens=spec.get("max_tokens"),
            extra_body=spec.get("extra_body"),
            request_timeout=spec.get("request_timeout"),
            max_retries=spec.get("max_retries"),
        )
        return _TimeoutAwareChatModel(
            inner=chat_model,
            model_kind=model_kind,
            provider=provider,
            timeout_seconds=spec.get("request_timeout"),
        )
    if provider == "jina":
        reranker = JinaRerank(
            model=spec["model"],
            jina_api_key=spec["jina_api_key"],
            top_n=spec.get("top_n"),
        )
        return _TimeoutAwareRerankModel(
            inner=reranker,
            model_kind=model_kind,
            provider=provider,
            timeout_seconds=spec.get("request_timeout"),
            max_retries=int(spec.get("max_retries") or 0),
        )
    if provider == "qwen":
        reranker = _QwenRerank(
            model=spec["model"],
            api_key=spec["api_key"],
            base_url=spec["base_url"],
            top_n=spec.get("top_n"),
            request_timeout=spec.get("request_timeout"),
        )
        return _TimeoutAwareRerankModel(
            inner=reranker,
            model_kind=model_kind,
            provider=provider,
            timeout_seconds=spec.get("request_timeout"),
            max_retries=int(spec.get("max_retries") or 0),
        )
    raise ValueError(f"Unsupported model provider: {provider}")


def get_model(kind: str, channel: str | None = None, **overrides: Any) -> Any:
    resolved_kind = _resolve_model_kind_only(kind)
    normalized_channel = str(channel or "").strip().lower()
    cache_key = (resolved_kind, normalized_channel, _freeze_overrides(overrides))
    cached = _MODEL_CACHE.get(cache_key)
    if cached is not None:
        return cached

    with _MODEL_CACHE_LOCK:
        cached = _MODEL_CACHE.get(cache_key)
        if cached is not None:
            return cached

        spec = dict(_get_cached_model_configs()[resolved_kind])
        if normalized_channel:
            spec.update(
                _channel_spec_overrides(
                    channel=normalized_channel,
                    model_kind=resolved_kind,
                    spec=spec,
                )
            )
        spec.update(overrides)
        model = _build_model(model_kind=resolved_kind, spec=spec)
        _MODEL_CACHE[cache_key] = model
        return model


def get_llm(node_name_or_kind: str | None = None, **overrides: Any) -> Any:
    model_kind = resolve_model_kind(node_name_or_kind)
    return get_model(model_kind, **overrides)


def get_llm_for_node(node_name: str, **overrides: Any) -> Any:
    return get_llm(node_name, **overrides)


__all__ = [
    "DEFAULT_DEEPSEEK_BASE_URL",
    "DEFAULT_DEEPSEEK_MODEL_NAME",
    "DEFAULT_JINA_MODEL_NAME",
    "DEFAULT_MODEL_KIND",
    "DEFAULT_QWEN_BASE_URL",
    "DEFAULT_QWEN_MODEL_NAME",
    "DEFAULT_QWEN_RERANK_BASE_URL",
    "DEFAULT_QWEN_RERANK_MODEL_NAME",
    "ModelRequestTimeoutError",
    "MODEL_KIND_ALIASES",
    "NODE_MODEL_KIND_MAP",
    "QWEN35_DISABLE_THINKING_EXTRA_BODY",
    "build_model_configs",
    "get_llm",
    "get_llm_for_node",
    "get_model",
    "get_model_configs",
    "reset_model_cache",
    "resolve_model_kind",
]
