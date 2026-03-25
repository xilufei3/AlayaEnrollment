from __future__ import annotations

from typing import Any

from ..schemas import RAGState


def create_merge_context_node():
    async def merge_context_node(state: RAGState) -> dict[str, Any]:
        reranked_vector_chunks = list(state.get("reranked_vector_chunks") or [])
        return {
            "chunks": reranked_vector_chunks,
        }

    return merge_context_node
