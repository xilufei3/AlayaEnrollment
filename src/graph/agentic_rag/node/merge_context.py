from __future__ import annotations

from typing import Any

from ..schemas import RAGState


def create_merge_context_node():
    def merge_context_node(state: RAGState) -> dict[str, Any]:
        structured_chunks = list(state.get("structured_chunks") or [])
        vector_chunks = list(state.get("vector_chunks") or [])
        return {"chunks": structured_chunks + vector_chunks}

    return merge_context_node
