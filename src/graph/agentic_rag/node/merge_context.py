from __future__ import annotations

from typing import Any

from langchain_core.documents import Document

from ..schemas import RAGState

_MAX_CANDIDATE_VECTOR_CHUNKS = 25


def _doc_key(doc: Document) -> tuple[str, str]:
    doc_id = str(doc.metadata.get("id", "")).strip()
    if doc_id:
        return ("id", doc_id)
    return ("content", doc.page_content)


def _merge_candidate_vector_chunks(
    existing: list[Document],
    incoming: list[Document],
    *,
    limit: int = _MAX_CANDIDATE_VECTOR_CHUNKS,
) -> list[Document]:
    merged: list[Document] = []
    seen: set[tuple[str, str]] = set()

    for doc in [*existing, *incoming]:
        key = _doc_key(doc)
        if key in seen:
            continue
        seen.add(key)
        merged.append(doc)
        if len(merged) >= limit:
            break

    return merged


def create_merge_context_node():
    async def merge_context_node(state: RAGState) -> dict[str, Any]:
        candidate_vector_chunks = list(state.get("candidate_vector_chunks") or [])
        structured_chunks = list(state.get("structured_chunks") or [])
        vector_chunks = list(state.get("vector_chunks") or [])
        merged_vectors = _merge_candidate_vector_chunks(candidate_vector_chunks, vector_chunks)
        return {
            "candidate_vector_chunks": merged_vectors,
            "chunks": structured_chunks + merged_vectors,
        }

    return merge_context_node
