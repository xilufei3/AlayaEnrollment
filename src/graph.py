from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

try:
    from .node.generation import create_generation_node
    from .node.intend_clasaify import create_intend_classify_node
    from .node.rerank import create_rerank_node
    from .node.vector_store_adapter import VectorStoreClientAdapter
    from .node.vector_retrieve import create_vector_retrieve_node
    from .schemas import WorkflowState
except ImportError:
    # fallback for direct script/module execution
    from node.generation import create_generation_node
    from node.intend_clasaify import create_intend_classify_node
    from node.rerank import create_rerank_node
    from node.vector_store_adapter import VectorStoreClientAdapter
    from node.vector_retrieve import create_vector_retrieve_node
    from schemas import WorkflowState


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

    vector_client = init_args.get("vector_client")
    if vector_client is None and init_args.get("vector_store") is not None:
        embed_query = init_args.get("embed_query")
        if embed_query is None:
            raise ValueError("create_graph requires init_args['embed_query'] when using vector_store")
        vector_client = VectorStoreClientAdapter(
            vector_store=init_args["vector_store"],
            embed_query=embed_query,
        )
    if vector_client is None:
        raise ValueError(
            "create_graph requires init_args['vector_client'] or "
            "init_args['vector_store'] + init_args['embed_query']"
        )

    vector_index = str(init_args.get("vector_index", "admission_index"))
    vector_top_k = int(init_args.get("vector_top_k", 5))
    vector_collection_id = init_args.get("vector_collection_id")
    intent_model_id = init_args.get("intent_model_id")
    generation_model_id = init_args.get("generation_model_id")

    g = StateGraph(WorkflowState)

    g.add_node("intent", create_intend_classify_node(model_id=intent_model_id))
    g.add_node(
        "retrieve",
        create_vector_retrieve_node(
            client=vector_client,
            index=vector_index,
            top_k=vector_top_k,
            collection_id=vector_collection_id,
        ),
    )
    g.add_node("rerank", create_rerank_node())
    g.add_node("generate", create_generation_node(model_id=generation_model_id))

    g.add_edge(START, "intent")
    g.add_edge("intent", "retrieve")
    g.add_edge("retrieve", "rerank")
    g.add_edge("rerank", "generate")
    g.add_edge("generate", END)

    final_checkpointer = checkpointer if checkpointer is not None else init_args.get("checkpointer")
    return g.compile(checkpointer=final_checkpointer)
