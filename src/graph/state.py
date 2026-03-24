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

    query: str
    intent: str
    query_mode: str
    confidence: float

    # Global slot memory + turn-specific slot needs
    slots: dict[str, str]
    required_slots: list[str]
    missing_slots: list[str]

    # Retrieval + generation
    chunks: list[Document]
    structured_results: list[StructuredTableResult]
    citations: list[dict[str, str]]
    retrieval_skipped: bool

    answer: str
