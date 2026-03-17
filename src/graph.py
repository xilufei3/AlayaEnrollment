from __future__ import annotations

from typing import Any, Dict

from langgraph.graph import END, START, StateGraph

try:
    from .config import CONFIDENCE_THRESHOLD, IntentType
    from .node.generation import create_generation_node
    from .node.intent_classify import create_intent_classify_node
    from .schemas import WorkflowState
    from .agentic_rag.graph import create_agentic_rag_node
except ImportError:
    from src.config import CONFIDENCE_THRESHOLD, IntentType
    from src.node.generation import create_generation_node
    from src.node.intent_classify import create_intent_classify_node
    from src.schemas import WorkflowState
    from src.agentic_rag.graph import create_agentic_rag_node


def route_after_intent(state: WorkflowState) -> str:
    intent = str(state.get("intent") or "").strip()
    confidence = float(state.get("confidence") or 0.0)
    missing_slots = state.get("missing_slots") or []

    if (
        intent in (IntentType.OUT_OF_SCOPE.value, IntentType.OTHER.value)
        or confidence < CONFIDENCE_THRESHOLD
    ):
        return "generate"
    return "agentic_rag"


def create_graph(
    init_args: Dict[str, Any] | None = None,
    *,
    checkpointer: Any | None = None,
):
    init_args = init_args or {}

    retriever = init_args.get("retriever")
    if retriever is None:
        raise ValueError(
            "create_graph requires init_args['retriever'] "
            "(a packages.retriever.service.RetrieverService instance)"
        )

    vector_top_k = int(init_args.get("vector_top_k", 8))
    rag_max_iterations = int(init_args.get("rag_max_iterations", 2))
    g = StateGraph(WorkflowState)
    g.add_node("intent_classify", create_intent_classify_node())
    g.add_node(
        "agentic_rag",
        create_agentic_rag_node(
            retriever=retriever,
            top_k=vector_top_k,
            max_iterations=rag_max_iterations,
            eval_model_id="eval",
            search_planner_model_id="planner",
        ),
    )
    g.add_node("generate", create_generation_node(model_id="generation"))

    g.add_edge(START, "intent_classify")
    g.add_conditional_edges(
        "intent_classify",
        route_after_intent,
        {
            "generate": "generate",
            "agentic_rag": "agentic_rag",
        },
    )
    g.add_edge("agentic_rag", "generate")
    g.add_edge("generate", END)

    final_checkpointer = checkpointer if checkpointer is not None else init_args.get("checkpointer")
    return g.compile(checkpointer=final_checkpointer)
