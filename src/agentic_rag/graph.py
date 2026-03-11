from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from alayaflow.utils.logger import AlayaFlowLogger

from packages.retriever.service import RetrieverService

from .node.rerank import create_rerank_node
from .node.retrieval import create_retrieval_node
from .node.search_planner import create_search_planner_node
from .node.sufficiency_eval import create_sufficiency_eval_node
from .schemas import RAGState


logger = AlayaFlowLogger()


def _route_after_eval(state: RAGState) -> str:
    """
    评估节点三分支路由：
    - sufficient           → END（携带 chunks 返回）
    - missing_slots        → build_clarify（子图内生成反问话术）→ END
    - insufficient_docs    + 未超限 → search_planner 重试
    - insufficient_docs    + 超限   → END（交由生成节点处理空文档）
    """
    eval_result = str(state.get("eval_result") or "sufficient")
    iteration = int(state.get("rag_iteration") or 0)
    max_iter = int(state.get("max_iterations") or 2)

    if eval_result == "missing_slots":
        return "__end__"
    if eval_result == "sufficient":
        return "__end__"

    # insufficient_docs
    if iteration >= max_iter:
        logger.debug(f"RAG max_iterations reached ({iteration}/{max_iter}), stopping.")
        return "__end__"

    logger.debug(f"RAG retry: iteration={iteration} max={max_iter}")
    return "search_planner"


def _compile_rag_graph(
    retriever: RetrieverService,
    top_k: int,
    eval_model_id: str | None,
) -> Any:
    g = StateGraph(RAGState)

    g.add_node("search_planner", create_search_planner_node())
    g.add_node("retrieval", create_retrieval_node(retriever=retriever, top_k=top_k))
    g.add_node("rerank", create_rerank_node())
    g.add_node("eval", create_sufficiency_eval_node(model_id=eval_model_id))

    g.add_edge(START, "search_planner")
    g.add_edge("search_planner", "retrieval")
    g.add_edge("retrieval", "rerank")
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
    retriever: RetrieverService,
    top_k: int = 8,
    max_iterations: int = 2,
    eval_model_id: str | None = None,
):
    """
    工厂函数：返回一个节点函数，供顶层 graph.py 使用。
    该节点将启动 agentic_rag 子图并将结果（chunks, missing_slots）写回 WorkflowState。
    """
    rag_graph = _compile_rag_graph(retriever=retriever, top_k=top_k, eval_model_id=eval_model_id)

    def agentic_rag_node(state: Any) -> dict[str, Any]:
        rag_input: RAGState = {
            "query": str(state.get("query") or "").strip(),
            "intent": str(state.get("intent") or "").strip(),
            "slots": dict(state.get("slots") or {}),
            "rag_iteration": 0,
            "max_iterations": max_iterations,
            "chunks": [],
            "eval_result": "",
            "missing_slots": [],
            "eval_reason": "",
        }

        try:
            final_state: RAGState = rag_graph.invoke(rag_input)
        except Exception as exc:
            logger.error(f"AgenticRAG sub-graph error {type(exc).__name__}: {exc}")
            return {"chunks": [], "missing_slots": []}

        chunks = list(final_state.get("chunks") or [])
        missing_slots = list(final_state.get("missing_slots") or [])
        eval_result = str(final_state.get("eval_result") or "sufficient")

        logger.debug(
            "AgenticRAG done.\n"
            f"eval_result={eval_result}\n"
            f"chunks={len(chunks)}\n"
            f"missing_slots={missing_slots}"
        )
        return {
            "chunks": chunks,
            "missing_slots": missing_slots,
        }

    return agentic_rag_node
