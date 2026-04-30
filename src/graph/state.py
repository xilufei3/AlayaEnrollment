from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages

from .structured_results import StructuredTableResult


class WorkflowState(TypedDict, total=False):
    # Conversation basics
    thread_id: str
    turn_id: str
    messages: Annotated[list[BaseMessage], add_messages]
    channel: str

    query: str
    intent: str
    query_mode: str
    confidence: float
    rag_max_iterations: int

    # Global slot memory + turn-specific slot needs
    slots: dict[str, str]

    # Retrieval + generation
    chunks: list[Document]
    structured_results: list[StructuredTableResult]
    eval_result: str
    eval_reason: str
    qa_doc: Document | None

    answer: str
