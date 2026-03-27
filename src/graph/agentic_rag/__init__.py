from __future__ import annotations

from .schemas import RAGState, SearchPlan

__all__ = ["RAGState", "SearchPlan", "create_agentic_rag_node"]


def __getattr__(name: str):
    if name == "create_agentic_rag_node":
        from .graph import create_agentic_rag_node

        return create_agentic_rag_node
    raise AttributeError(name)
