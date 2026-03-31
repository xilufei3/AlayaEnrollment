from __future__ import annotations

import json

from langchain_core.documents import Document

from src.graph.llm import build_model_configs, get_model, reset_model_cache


def _clear_rerank_envs(monkeypatch) -> None:
    for name in (
        "QWEN_API_KEY",
        "QWEN_BASE_URL",
        "QWEN_RERANK_MODEL_NAME",
        "RERANK_PROVIDER",
        "RERANK_MODEL_NAME",
        "RERANK_API_KEY",
        "RERANK_BASE_URL",
        "RERANK_TOP_N",
        "RERANK_MODEL_TIMEOUT_SECONDS",
        "RERANK_MODEL_MAX_RETRIES",
        "JINA_API_KEY",
        "JINA_MODEL_NAME",
    ):
        monkeypatch.delenv(name, raising=False)


class _FakeResponse:
    def __init__(self, payload: dict, status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code
        self.ok = 200 <= status_code < 300
        self.text = json.dumps(payload, ensure_ascii=False)

    def json(self) -> dict:
        return self._payload


def test_rerank_model_defaults_to_qwen(monkeypatch) -> None:
    _clear_rerank_envs(monkeypatch)
    monkeypatch.setenv("QWEN_API_KEY", "qwen-key")

    reset_model_cache()
    try:
        rerank = build_model_configs()["rerank"]
    finally:
        reset_model_cache()

    assert rerank["provider"] == "qwen"
    assert rerank["model"] == "qwen3-rerank"
    assert rerank["api_key"] == "qwen-key"
    assert (
        rerank["base_url"]
        == "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )


def test_qwen_rerank_compress_documents_maps_indices_and_scores(monkeypatch) -> None:
    _clear_rerank_envs(monkeypatch)
    monkeypatch.setenv("RERANK_PROVIDER", "qwen")
    monkeypatch.setenv("RERANK_API_KEY", "rerank-key")
    monkeypatch.setenv("RERANK_MODEL_NAME", "qwen3-rerank")
    monkeypatch.setenv("RERANK_TOP_N", "2")

    captured: dict[str, object] = {}

    def fake_post(url, *, headers, json, timeout):
        captured["url"] = url
        captured["headers"] = headers
        captured["json"] = json
        captured["timeout"] = timeout
        return _FakeResponse(
            {
                "output": {
                    "results": [
                        {"index": 1, "relevance_score": 0.91},
                        {"index": 0, "relevance_score": 0.12},
                    ]
                }
            }
        )

    monkeypatch.setattr("src.graph.llm.requests.post", fake_post)

    reset_model_cache()
    try:
        reranker = get_model("rerank")
        documents = [
            Document(page_content="old vector", metadata={"id": "old"}),
            Document(page_content="new vector", metadata={"id": "new"}),
        ]
        reranked = reranker.compress_documents(documents=documents, query="admission policy")
    finally:
        reset_model_cache()

    assert [doc.page_content for doc in reranked] == ["new vector", "old vector"]
    assert reranked[0].metadata["relevance_score"] == 0.91
    assert reranked[0].metadata["rerank_score"] == 0.91
    assert captured["url"] == (
        "https://dashscope.aliyuncs.com/api/v1/services/rerank/text-rerank/text-rerank"
    )
    assert captured["headers"] == {
        "Authorization": "Bearer rerank-key",
        "Content-Type": "application/json",
    }
    assert captured["timeout"] == 8.0
    assert captured["json"] == {
        "model": "qwen3-rerank",
        "input": {
            "query": "admission policy",
            "documents": ["old vector", "new vector"],
        },
        "parameters": {
            "return_documents": True,
            "top_n": 2,
        },
    }
