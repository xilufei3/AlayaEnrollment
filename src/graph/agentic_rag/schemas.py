from __future__ import annotations

from typing import Annotated, Any, Literal, TypedDict

from langchain_core.documents import Document


def _overwrite(left: Any, right: Any) -> Any:
    """Reducer: last writer wins. Required for fan-out / fan-in merges."""
    return right


class SearchPlan(TypedDict, total=False):
    strategy: Literal["vector_keyword_hybrid"]
    vector_query: str
    sub_queries: list[str]
    filter_expr: str
    top_k: int


class SQLCandidate(TypedDict, total=False):
    enabled: bool
    selected_tables: list[str]
    reason: str


class TablePlan(TypedDict, total=False):
    table: str
    key_values: dict[str, list[str]]
    reason: str


class SQLPlan(TypedDict, total=False):
    enabled: bool
    table_plans: list[TablePlan]
    limit: int
    reason: str


class RAGState(TypedDict, total=False):
    # Inputs from WorkflowState
    query: Annotated[str, _overwrite]
    reply_mode: Annotated[str, _overwrite]
    intent: Annotated[str, _overwrite]
    slots: Annotated[dict[str, str], _overwrite]
    required_slots: Annotated[list[str], _overwrite]

    # Internal loop state
    search_plan: Annotated[SearchPlan, _overwrite]
    sql_candidate: Annotated[SQLCandidate, _overwrite]
    sql_plan: Annotated[SQLPlan, _overwrite]
    rag_iteration: Annotated[int, _overwrite]
    max_iterations: Annotated[int, _overwrite]

    # Retrieval intermediates
    vector_chunks: Annotated[list[Document], _overwrite]
    candidate_vector_chunks: Annotated[list[Document], _overwrite]
    reranked_vector_chunks: Annotated[list[Document], _overwrite]
    structured_chunks: Annotated[list[Document], _overwrite]
    structured_results: Annotated[list[dict[str, Any]], _overwrite]

    # Final chunks used by eval and returned to WorkflowState
    chunks: Annotated[list[Document], _overwrite]

    # Sufficiency result returned to WorkflowState
    eval_result: Annotated[Literal["sufficient", "missing_slots", "insufficient_docs"], _overwrite]
    missing_slots: Annotated[list[str], _overwrite]
    eval_reason: Annotated[str, _overwrite]
