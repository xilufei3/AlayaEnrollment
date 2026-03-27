from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from .agentic_rag.graph import create_agentic_rag_node
from .node.generation import create_generation_node
from .node.intent_classify import create_intent_classify_node
from .state import WorkflowState


def route_after_scope(state: WorkflowState) -> str:
    in_scope = state.get("in_scope")
    if in_scope is False:
        return "generate"
    return "agentic_rag"


def create_graph(
    init_args: dict[str, Any] | None = None,
    *,
    checkpointer: Any | None = None,
):
    init_args = init_args or {}

    retriever = init_args.get("retriever")
    if retriever is None:
        raise ValueError(
            "create_graph requires init_args['retriever'] "
            "(an injected search backend with a search(...) method)"
        )

    vector_top_k = int(init_args.get("vector_top_k", 8))
    rag_max_iterations = int(init_args.get("rag_max_iterations", 2))

    graph = StateGraph(WorkflowState)
    graph.add_node("intent_classify", create_intent_classify_node())
    graph.add_node(
        "agentic_rag",
        create_agentic_rag_node(
            retriever=retriever,
            top_k=vector_top_k,
            max_iterations=rag_max_iterations,
            eval_model_id="eval",
            search_planner_model_id="planner",
        ),
    )
    graph.add_node("generate", create_generation_node(model_id="generation"))

    graph.add_edge(START, "intent_classify")
    graph.add_conditional_edges(
        "intent_classify",
        route_after_scope,
        {
            "generate": "generate",
            "agentic_rag": "agentic_rag",
        },
    )
    graph.add_edge("agentic_rag", "generate")
    graph.add_edge("generate", END)

    final_checkpointer = checkpointer if checkpointer is not None else init_args.get("checkpointer")
    return graph.compile(checkpointer=final_checkpointer)
