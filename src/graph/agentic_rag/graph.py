from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from ..llm import ModelRequestTimeoutError
from .node.rerank import create_rerank_node
from .node.retrieval import create_retrieval_node
from .node.search_planner import create_search_planner_node
from .node.sql_plan_builder import create_sql_plan_builder_node
from .node.sql_query import create_sql_query_node
from .schemas import RAGState

logger = logging.getLogger(__name__)


def _compile_rag_graph(
    retriever: Any,
    top_k: int,
    search_planner_model_id: str | None = None,
) -> Any:
    g = StateGraph(RAGState)

    g.add_node("search_planner", create_search_planner_node(model_id=search_planner_model_id))
    g.add_node("retrieval", create_retrieval_node(retriever=retriever, top_k=top_k))
    g.add_node("sql_plan_builder", create_sql_plan_builder_node(model_id=search_planner_model_id))
    g.add_node("sql_query", create_sql_query_node())
    g.add_node("rerank", create_rerank_node())

    g.add_edge(START, "search_planner")
    g.add_edge("search_planner", "retrieval")
    g.add_edge("search_planner", "sql_plan_builder")
    g.add_edge("retrieval", "rerank")
    g.add_edge("sql_plan_builder", "sql_query")
    g.add_edge(["rerank", "sql_query"], END)

    return g.compile()


def create_agentic_rag_node(
    *,
    retriever: Any,
    top_k: int = 8,
    search_planner_model_id: str | None = None,
):
    rag_graph = _compile_rag_graph(
        retriever=retriever,
        top_k=top_k,
        search_planner_model_id=search_planner_model_id,
    )

    async def agentic_rag_node(state: Any) -> dict[str, Any]:
        rag_input: RAGState = {
            "query": str(state.get("query") or "").strip(),
            "intent": str(state.get("intent") or "").strip(),
            "query_mode": str(state.get("query_mode") or "").strip(),
            "slots": dict(state.get("slots") or {}),
            "search_plan": {},
            "sql_candidate": {},
            "sql_plan": {},
            "vector_chunks": [],
            "structured_results": [],
            "chunks": [],
        }

        try:
            final_state: RAGState = await rag_graph.ainvoke(rag_input)
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            logger.error(f"AgenticRAG sub-graph error {type(exc).__name__}: {exc}")
            return {"chunks": [], "structured_results": []}

        chunks = list(final_state.get("chunks") or [])
        structured_results = list(final_state.get("structured_results") or [])

        logger.debug(
            "AgenticRAG done.\n"
            f"chunks={len(chunks)}\n"
            f"structured_results={len(structured_results)}"
        )
        return {
            "chunks": chunks,
            "structured_results": structured_results,
        }

    return agentic_rag_node
