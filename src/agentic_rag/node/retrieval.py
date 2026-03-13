from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

from alayaflow.utils.logger import AlayaFlowLogger

from packages.retriever.service import RetrieverService
from packages.vector_store.models import SearchHit

from ...config import COLLECTION_NAME
from ..schemas import RAGState, SearchPlan


logger = AlayaFlowLogger()


def _hit_to_document(hit: SearchHit) -> Document:
    metadata = dict(hit.metadata or {})
    page_content = (
        metadata.pop("page_content", None)
        or metadata.pop("content", None)
        or metadata.pop("text", None)
        or ""
    )
    metadata["id"] = hit.id
    metadata["score"] = hit.score
    return Document(page_content=str(page_content), metadata=metadata)


def _deduplicate(docs: list[Document]) -> list[Document]:
    seen: set[str] = set()
    result: list[Document] = []
    for doc in docs:
        doc_id = str(doc.metadata.get("id", "")) or doc.page_content[:80]
        if doc_id not in seen:
            seen.add(doc_id)
            result.append(doc)
    return result


def create_retrieval_node(*, retriever: RetrieverService, top_k: int = 8):
    def retrieval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        plan: SearchPlan = state.get("search_plan") or {}
        retrieval_query = str(plan.get("vector_query") or "").strip() or query

        collection = COLLECTION_NAME
        if not retrieval_query:
            logger.debug(
                "Retrieval skipped.\n"
                f"query_empty={not retrieval_query}\n"
                f"intent={intent}"
            )
            return {"vector_chunks": [], "structured_results": []}

        plan_top_k = int(plan.get("top_k") or top_k)

        try:
            result = retriever.retrieve(
                collection=collection,
                query=retrieval_query,
                top_k=plan_top_k,
            )
            docs = [_hit_to_document(hit) for hit in result.hits]
            logger.debug(
                "VectorRetrieve done.\n"
                f"collection={collection}\n"
                f"top_k={plan_top_k}\n"
                f"docs={len(docs)}"
            )
        except Exception as exc:
            logger.error(f"VectorRetrieve error {type(exc).__name__}: {exc}")
            docs = []

        docs = _deduplicate(docs)
        return {
            "vector_chunks": docs,
            "structured_results": [],
            "chunks": docs,
        }

    return retrieval_node
