from __future__ import annotations

import logging
from typing import Any

from langgraph.graph import END, START, StateGraph

from .node.merge_context import create_merge_context_node
from .node.rerank import create_rerank_node
from .node.retrieval import create_retrieval_node
from .node.search_planner import create_search_planner_node
from .node.sql_query import create_sql_query_node
from .node.sufficiency_eval import create_sufficiency_eval_node
from .schemas import RAGState

logger = logging.getLogger(__name__)


def _route_after_eval(state: RAGState) -> str:
    eval_result = str(state.get("eval_result") or "sufficient")
    iteration = int(state.get("rag_iteration") or 0)
    max_iter = int(state.get("max_iterations") or 2)

    if eval_result in ("missing_slots", "sufficient"):
        return "__end__"

    if iteration >= max_iter:
        logger.debug(f"RAG max_iterations reached ({iteration}/{max_iter}), stopping.")
        return "__end__"

    logger.debug(f"RAG retry: iteration={iteration} max={max_iter}")
    return "search_planner"


def _compile_rag_graph(
    retriever: Any,
    top_k: int,
    eval_model_id: str | None,
    search_planner_model_id: str | None = None,
) -> Any:
    g = StateGraph(RAGState)

    g.add_node("search_planner", create_search_planner_node(model_id=search_planner_model_id))
    g.add_node("retrieval", create_retrieval_node(retriever=retriever, top_k=top_k))
    g.add_node("sql_query", create_sql_query_node())
    g.add_node("merge_context", create_merge_context_node())
    g.add_node("rerank", create_rerank_node())
    g.add_node("eval", create_sufficiency_eval_node(model_id=eval_model_id))

    g.add_edge(START, "search_planner")
    g.add_edge("search_planner", "retrieval")
    g.add_edge("search_planner", "sql_query")
    g.add_edge("retrieval", "merge_context")
    g.add_edge("sql_query", "merge_context")
    g.add_edge("merge_context", "rerank")
    g.add_edge("rerank", "eval")
    g.add_conditional_edges(
        "eval",
        _route_after_eval,
        {
            "__end__": END,
            "search_planner": "search_planner",
        },
    )

    return g.compile()


def create_agentic_rag_node(
    *,
    retriever: Any,
    top_k: int = 8,
    max_iterations: int = 2,
    eval_model_id: str | None = None,
    search_planner_model_id: str | None = None,
):
    rag_graph = _compile_rag_graph(
        retriever=retriever,
        top_k=top_k,
        eval_model_id=eval_model_id,
        search_planner_model_id=search_planner_model_id,
    )

    async def agentic_rag_node(state: Any) -> dict[str, Any]:
        rag_input: RAGState = {
            "query": str(state.get("query") or "").strip(),
            "intent": str(state.get("intent") or "").strip(),
            "slots": dict(state.get("slots") or {}),
            "required_slots": list(state.get("required_slots") or []),
            "rag_iteration": 0,
            "max_iterations": max_iterations,
            "search_plan": {},
            "sql_plan": {},
            "vector_chunks": [],
            "candidate_vector_chunks": [],
            "structured_chunks": [],
            "structured_results": [],
            "chunks": [],
            "eval_result": "",
            "missing_slots": [],
            "eval_reason": "",
        }

        try:
            final_state: RAGState = await rag_graph.ainvoke(rag_input)
        except Exception as exc:
            logger.error(f"AgenticRAG sub-graph error {type(exc).__name__}: {exc}")
            return {"chunks": [], "missing_slots": [], "structured_results": []}

        chunks = list(final_state.get("chunks") or [])
        missing_slots = list(final_state.get("missing_slots") or [])
        structured_results = list(final_state.get("structured_results") or [])
        eval_result = str(final_state.get("eval_result") or "sufficient")

        logger.debug(
            "AgenticRAG done.\n"
            f"eval_result={eval_result}\n"
            f"chunks={len(chunks)}\n"
            f"structured_results={len(structured_results)}\n"
            f"missing_slots={missing_slots}"
        )
        return {
            "chunks": chunks,
            "missing_slots": missing_slots,
            "structured_results": structured_results,
        }

    return agentic_rag_node
