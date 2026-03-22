from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph

from ..config.settings import CONFIDENCE_THRESHOLD, IntentType
from .agentic_rag.graph import create_agentic_rag_node
from .node.chitchat import create_chitchat_node
from .node.generation import create_generation_node
from .node.intent_classify import create_intent_classify_node
from .node.out_of_scope import create_out_of_scope_node
from .node.slot_followup import create_slot_followup_node
from .state import WorkflowState


def route_after_intent(state: WorkflowState) -> str:
    intent = str(state.get("intent") or "").strip()
    confidence = float(state.get("confidence") or 0.0)

    if intent == IntentType.OUT_OF_SCOPE.value:
        return "out_of_scope_reply"
    if intent == IntentType.OTHER.value or confidence < CONFIDENCE_THRESHOLD:
        return "chitchat_reply"
    return "agentic_rag"


def route_after_rag(state: WorkflowState) -> str:
    if state.get("missing_slots"):
        return "slot_followup"
    return "generate"


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
    graph.add_node("out_of_scope_reply", create_out_of_scope_node(model_id="generation"))
    graph.add_node("chitchat_reply", create_chitchat_node(model_id="generation"))
    graph.add_node("slot_followup", create_slot_followup_node(model_id="generation"))
    graph.add_node("generate", create_generation_node(model_id="generation"))

    graph.add_edge(START, "intent_classify")
    graph.add_conditional_edges(
        "intent_classify",
        route_after_intent,
        {
            "out_of_scope_reply": "out_of_scope_reply",
            "chitchat_reply": "chitchat_reply",
            "agentic_rag": "agentic_rag",
        },
    )
    graph.add_conditional_edges(
        "agentic_rag",
        route_after_rag,
        {
            "slot_followup": "slot_followup",
            "generate": "generate",
        },
    )
    graph.add_edge("out_of_scope_reply", END)
    graph.add_edge("chitchat_reply", END)
    graph.add_edge("slot_followup", END)
    graph.add_edge("generate", END)

    final_checkpointer = checkpointer if checkpointer is not None else init_args.get("checkpointer")
    return graph.compile(checkpointer=final_checkpointer)
