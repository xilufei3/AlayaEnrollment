from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

try:
    from .node.generation import create_generation_node
    from .node.intend_clasaify import create_intend_classify_node
    from .node.rerank import create_rerank_node
    from .node.vector_retrieve import create_vector_retrieve_node
    from .schemas import WorkflowState
except ImportError:
    # fallback when run from repo root (e.g. uvicorn src.api.chat_app:app)
    from src.node.generation import create_generation_node
    from src.node.intend_clasaify import create_intend_classify_node
    from src.node.rerank import create_rerank_node
    from src.node.vector_retrieve import create_vector_retrieve_node
    from src.schemas import WorkflowState


def create_graph(
    init_args: Dict[str, Any] | None = None,
    *,
    checkpointer: Any | None = None,
):
    """
    4-step pipeline:
    intent classify -> vector retrieve -> rerank -> generation
    """
    init_args = init_args or {}

    retriever = init_args.get("retriever")
    if retriever is None:
        raise ValueError(
            "create_graph requires init_args['retriever'] "
            "(a packages.retriever.service.RetrieverService instance)"
        )

    vector_top_k = int(init_args.get("vector_top_k", 5))
    intent_model_id = init_args.get("intent_model_id")
    generation_model_id = init_args.get("generation_model_id")

    g = StateGraph(WorkflowState)

    g.add_node("intent", create_intend_classify_node(model_id=intent_model_id))
    g.add_node("retrieve",create_vector_retrieve_node(retriever=retriever, top_k=vector_top_k))
    g.add_node("rerank", create_rerank_node())
    g.add_node("generate", create_generation_node(model_id=generation_model_id))

    g.add_edge(START, "intent")
    g.add_edge("intent", "retrieve")
    g.add_edge("retrieve", "rerank")
    g.add_edge("rerank", "generate")
    g.add_edge("generate", END)

    final_checkpointer = checkpointer if checkpointer is not None else init_args.get("checkpointer")
    return g.compile(checkpointer=final_checkpointer)
