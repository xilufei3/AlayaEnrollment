from __future__ import annotations

import asyncio
import logging
from typing import Any

from langchain_core.documents import Document

from ....knowledge.vector_manager import SEARCH_HYBRID, SEARCH_SPARSE, SEARCH_VECTOR
from ..schemas import RAGState, SearchPlan


logger = logging.getLogger(__name__)

_SEARCH_MODE_BY_STRATEGY: dict[str, str] = {
    "vector_keyword_hybrid": SEARCH_HYBRID,
    "hybrid": SEARCH_HYBRID,
    "vector": SEARCH_VECTOR,
    "sparse": SEARCH_SPARSE,
}


def _result_to_document(result: dict[str, Any]) -> Document:
    page_content = str(result.get("content") or "")
    metadata = {
        "id": result.get("id"),
        "score": result.get("score"),
        "source_file": result.get("source_file") or "",
        "category": result.get("category") or "",
    }
    return Document(page_content=page_content, metadata=metadata)


def _deduplicate(docs: list[Document]) -> list[Document]:
    seen: set[str] = set()
    result: list[Document] = []
    for doc in docs:
        doc_id = str(doc.metadata.get("id", "")) or doc.page_content[:80]
        if doc_id not in seen:
            seen.add(doc_id)
            result.append(doc)
    return result


def _resolve_search_mode(plan: SearchPlan) -> str:
    strategy = str(plan.get("strategy") or "").strip().lower()
    return _SEARCH_MODE_BY_STRATEGY.get(strategy, SEARCH_HYBRID)


def _resolve_search_backend(retriever: Any | None) -> Any:
    if retriever is None or not hasattr(retriever, "search"):
        raise ValueError("create_retrieval_node requires an injected search backend with a search(...) method")
    return retriever


def create_retrieval_node(*, retriever: Any | None = None, top_k: int = 8):
    search_backend = _resolve_search_backend(retriever)

    async def retrieval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        plan: SearchPlan = state.get("search_plan") or {}
        retrieval_query = str(plan.get("vector_query") or "").strip() or query

        if not retrieval_query:
            logger.debug(
                "Retrieval skipped.\n"
                f"query_empty={not retrieval_query}\n"
                f"intent={intent}"
            )
            return {"vector_chunks": []}

        plan_top_k = int(plan.get("top_k") or top_k)
        search_mode = _resolve_search_mode(plan)
        filter_expr = str(plan.get("filter_expr") or "").strip() or None

        try:
            hits = await asyncio.to_thread(
                lambda: search_backend.search(
                    query=retrieval_query,
                    top_k=plan_top_k,
                    filter_expr=filter_expr,
                    mode=search_mode,
                )
            )
            docs = [_result_to_document(hit) for hit in hits]
            logger.debug(
                "VectorManager retrieval done.\n"
                f"mode={search_mode}\n"
                f"top_k={plan_top_k}\n"
                f"docs={len(docs)}"
            )
        except Exception as exc:
            logger.error(f"VectorManager retrieval error {type(exc).__name__}: {exc}")
            docs = []

        docs = _deduplicate(docs)
        return {
            "vector_chunks": docs,
        }

    return retrieval_node
