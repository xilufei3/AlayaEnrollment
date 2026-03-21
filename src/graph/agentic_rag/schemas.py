from __future__ import annotations

from typing import Any, Literal, TypedDict

from langchain_core.documents import Document


class SearchPlan(TypedDict, total=False):
    strategy: Literal["vector_keyword_hybrid"]
    vector_query: str
    top_k: int


class SQLPlan(TypedDict, total=False):
    enabled: bool
    province: str
    year: str
    limit: int
    reason: str


class RAGState(TypedDict, total=False):
    # Inputs from WorkflowState
    query: str
    intent: str
    slots: dict[str, str]
    required_slots: list[str]

    # Internal loop state
    search_plan: SearchPlan
    sql_plan: SQLPlan
    rag_iteration: int
    max_iterations: int

    # Retrieval intermediates
    vector_chunks: list[Document]
    candidate_vector_chunks: list[Document]
    structured_chunks: list[Document]
    structured_results: list[dict[str, Any]]

    # Final chunks used by rerank/eval and returned to WorkflowState
    chunks: list[Document]

    # Sufficiency result returned to WorkflowState
    eval_result: Literal["sufficient", "missing_slots", "insufficient_docs"]
    missing_slots: list[str]
    eval_reason: str
