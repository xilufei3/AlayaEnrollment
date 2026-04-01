from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.documents import Document

from ..structured_results import StructuredTableResult


def _overwrite(left: Any, right: Any) -> Any:
    """Reducer: last writer wins. Required for fan-out / fan-in merges."""
    return right


class SearchPlan(TypedDict, total=False):
    strategy: Literal["vector_keyword_hybrid"]
    vector_query: str
    top_k: int


class SQLCandidate(TypedDict, total=False):
    enabled: bool
    selected_tables: list[str]


class TablePlan(TypedDict, total=False):
    table: str
    key_values: dict[str, list[str]]


class SQLPlan(TypedDict, total=False):
    enabled: bool
    table_plans: list[TablePlan]
    limit: int


class RAGState(TypedDict, total=False):
    # Inputs from WorkflowState
    query: Annotated[str, _overwrite]
    intent: Annotated[str, _overwrite]
    query_mode: Annotated[str, _overwrite]
    slots: Annotated[dict[str, str], _overwrite]

    # Internal state
    search_plan: Annotated[SearchPlan, _overwrite]
    sql_candidate: Annotated[SQLCandidate, _overwrite]
    sql_plan: Annotated[SQLPlan, _overwrite]

    # Retrieval intermediates
    vector_chunks: Annotated[list[Document], _overwrite]
    structured_results: Annotated[list[StructuredTableResult], _overwrite]

    # Final chunks returned to WorkflowState
    chunks: Annotated[list[Document], _overwrite]
