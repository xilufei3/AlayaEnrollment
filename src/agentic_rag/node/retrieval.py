from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

from alayaflow.utils.logger import AlayaFlowLogger

from packages.retriever.service import RetrieverService
from packages.vector_store.models import SearchHit

from ...config import INTENT_COLLECTION_MAP
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


def _do_vector_retrieve(
    retriever: RetrieverService,
    collection: str,
    query: str,
    top_k: int,
) -> list[Document]:
    try:
        result = retriever.retrieve(collection=collection, query=query, top_k=top_k)
        docs = [_hit_to_document(hit) for hit in result.hits]
        logger.debug(
            "VectorRetrieve done.\n"
            f"collection={collection}\n"
            f"top_k={top_k}\n"
            f"query={query}\n"
            f"docs={len(docs)}"
        )
        return docs
    except Exception as exc:
        logger.error(f"VectorRetrieve error {type(exc).__name__}: {exc}")
        return []


def _do_structured_retrieve(
    retriever: RetrieverService,
    collection: str,
    query: str,
    top_k: int,
    filters: dict[str, str],
) -> list[Document]:
    if not filters:
        return []
    clauses = [f'{k} == "{v.replace(chr(34), "")}"' for k, v in filters.items() if v]
    filter_expr = " AND ".join(clauses)
    try:
        result = retriever.retrieve(
            collection=collection,
            query=query,
            top_k=top_k,
            filter_expression=filter_expr,
        )
        docs = [_hit_to_document(hit) for hit in result.hits]
        logger.debug(
            "StructuredRetrieve done.\n"
            f"collection={collection}\n"
            f"filter={filter_expr}\n"
            f"docs={len(docs)}"
        )
        return docs
    except Exception as exc:
        logger.error(f"StructuredRetrieve error {type(exc).__name__}: {exc}")
        return []


def create_retrieval_node(*, retriever: RetrieverService, top_k: int = 8):
    def retrieval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        plan: SearchPlan = state.get("search_plan") or {}

        collection = INTENT_COLLECTION_MAP.get(intent, "")
        if not query or not collection:
            logger.debug(
                "Retrieval skipped.\n"
                f"query_empty={not query}\n"
                f"collection_empty={not collection}\n"
                f"intent={intent}"
            )
            return {"vector_chunks": [], "structured_results": []}

        strategy = str(plan.get("strategy") or "vector")
        plan_top_k = int(plan.get("top_k") or top_k)
        filters: dict[str, str] = dict(plan.get("structured_filters") or {})

        vector_docs: list[Document] = []
        structured_docs: list[Document] = []

        if strategy == "structured":
            structured_docs = _do_structured_retrieve(
                retriever, collection, query, plan_top_k, filters
            )
            # 结构化检索无结果时，自动降级向量检索
            if not structured_docs:
                logger.debug("Structured empty, fallback to vector.")
                vector_docs = _do_vector_retrieve(retriever, collection, query, plan_top_k)

        elif strategy == "hybrid":
            structured_docs = _do_structured_retrieve(
                retriever, collection, query, plan_top_k // 2 + 1, filters
            )
            # 向量检索补充剩余名额
            remaining = max(plan_top_k - len(structured_docs), plan_top_k // 2)
            vector_docs = _do_vector_retrieve(retriever, collection, query, remaining)

        else:  # "vector"
            vector_docs = _do_vector_retrieve(retriever, collection, query, plan_top_k)

        # 合并、去重（structured 优先放前面，权重更高）
        merged = _deduplicate(structured_docs + vector_docs)
        logger.debug(
            "Retrieval merged.\n"
            f"strategy={strategy}\n"
            f"structured={len(structured_docs)}\n"
            f"vector={len(vector_docs)}\n"
            f"merged={len(merged)}"
        )
        return {
            "vector_chunks": vector_docs,
            "structured_results": [
                {"page_content": d.page_content, "metadata": d.metadata}
                for d in structured_docs
            ],
            "chunks": merged,  # 临时保存，rerank 会覆盖
        }

    return retrieval_node
