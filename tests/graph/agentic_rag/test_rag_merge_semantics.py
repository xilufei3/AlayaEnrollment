from __future__ import annotations

import asyncio

from langchain_core.documents import Document

from src.graph.agentic_rag.graph import create_agentic_rag_node
from src.graph.agentic_rag.node.merge_context import create_merge_context_node
from src.graph.agentic_rag.node.rerank import create_rerank_node


def _run_async(coro):
    return asyncio.run(coro)


def test_rerank_node_only_reranks_vector_candidates(monkeypatch) -> None:
    old_vector = Document(page_content="old vector", metadata={"id": "old"})
    new_vector = Document(page_content="new vector", metadata={"id": "new"})
    sql_doc = Document(page_content="sql result", metadata={"id": "sql"})
    captured: dict[str, object] = {}

    class FakeReranker:
        def compress_documents(self, *, documents, query):
            captured["query"] = query
            captured["documents"] = list(documents)
            return list(reversed(list(documents)))

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.rerank.get_model",
        lambda *args, **kwargs: FakeReranker(),
    )

    node = create_rerank_node()
    result = _run_async(
        node(
            {
                "query": "admission policy",
                "vector_chunks": [new_vector],
                "candidate_vector_chunks": [old_vector],
                "chunks": [sql_doc, old_vector, new_vector],
            }
        )
    )

    seen_docs = captured["documents"]
    assert [doc.page_content for doc in seen_docs] == ["old vector", "new vector"]
    assert [doc.page_content for doc in result["candidate_vector_chunks"]] == [
        "old vector",
        "new vector",
    ]
    assert [doc.page_content for doc in result["reranked_vector_chunks"]] == [
        "new vector",
        "old vector",
    ]
    assert "chunks" not in result


def test_merge_context_only_keeps_reranked_vectors() -> None:
    reranked_vector = Document(page_content="reranked vector", metadata={"id": "vec"})
    raw_vector = Document(page_content="raw vector", metadata={"id": "raw"})

    node = create_merge_context_node()
    result = _run_async(
        node(
            {
                "reranked_vector_chunks": [reranked_vector],
                "vector_chunks": [raw_vector],
            }
        )
    )

    assert [doc.page_content for doc in result["chunks"]] == ["reranked vector"]


def test_agentic_rag_graph_merges_after_rerank(monkeypatch) -> None:
    vector_doc = Document(page_content="vector doc", metadata={"id": "vec"})
    reranked_doc = Document(page_content="reranked vector", metadata={"id": "vec-r"})

    async def search_planner_node(_state):
        return {
            "search_plan": {"strategy": "vector_keyword_hybrid", "vector_query": "query", "top_k": 4},
            "sql_candidate": {"enabled": True, "selected_tables": ["admission_scores"], "reason": "selected"},
            "sql_plan": {"enabled": True, "table_plans": [], "limit": 2, "reason": "planned"},
            "rag_iteration": 1,
        }

    async def retrieval_node(_state):
        return {"vector_chunks": [vector_doc]}

    async def sql_plan_builder_node(_state):
        return {
            "sql_plan": {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "admission_scores",
                        "key_values": {"province": ["guangdong"]},
                        "reason": "test plan",
                    }
                ],
                "limit": 2,
                "reason": "planned",
            }
        }

    async def sql_query_node(_state):
        return {
            "structured_results": [
                {
                    "table": "admission_scores",
                    "description": "scores",
                    "query_key": ["province"],
                    "columns": {"province": "省份"},
                    "items": [{"province": "guangdong"}],
                }
            ],
        }

    async def rerank_node(state):
        assert [doc.page_content for doc in state.get("vector_chunks") or []] == ["vector doc"]
        return {
            "candidate_vector_chunks": [vector_doc],
            "reranked_vector_chunks": [reranked_doc],
        }

    async def merge_context_node(state):
        assert [doc.page_content for doc in state.get("reranked_vector_chunks") or []] == [
            "reranked vector"
        ]
        return {"chunks": list(state.get("reranked_vector_chunks") or [])}

    async def eval_node(_state):
        return {
            "eval_result": "sufficient",
            "missing_slots": [],
            "eval_reason": "enough context",
        }

    monkeypatch.setattr(
        "src.graph.agentic_rag.graph.create_search_planner_node",
        lambda model_id=None: search_planner_node,
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.graph.create_retrieval_node",
        lambda retriever=None, top_k=8: retrieval_node,
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.graph.create_sql_plan_builder_node",
        lambda model_id=None: sql_plan_builder_node,
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.graph.create_sql_query_node",
        lambda: sql_query_node,
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.graph.create_rerank_node",
        lambda: rerank_node,
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.graph.create_merge_context_node",
        lambda: merge_context_node,
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.graph.create_sufficiency_eval_node",
        lambda model_id=None: eval_node,
    )

    node = create_agentic_rag_node(retriever=object())
    result = _run_async(
        node(
            {
                "query": "query",
                "intent": "admission_policy",
                "slots": {},
                "required_slots": [],
                "missing_slots": [],
            }
        )
    )

    assert [doc.page_content for doc in result["chunks"]] == ["reranked vector"]
    assert result["structured_results"] == [
        {
            "table": "admission_scores",
            "description": "scores",
            "query_key": ["province"],
            "columns": {"province": "省份"},
            "items": [{"province": "guangdong"}],
        }
    ]
    assert result["missing_slots"] == []
