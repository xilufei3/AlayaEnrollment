from __future__ import annotations

from typing import Any, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage


class WorkflowState(TypedDict, total=False):
    # Conversation basics
    thread_id: str
    turn_id: str
    messages: list[BaseMessage]

    query: str
    intent: str
    confidence: float

    # Slot extraction for policy questions
    slots: dict[str, str]
    missing_slots: list[str]

    # Retrieval + generation
    chunks: list[Document]
    structured_results: list[dict[str, Any]]
    citations: list[dict[str, str]]
    retrieval_skipped: bool

    answer: str
