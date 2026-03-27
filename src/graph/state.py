from __future__ import annotations

from typing import Annotated, TypedDict

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.graph import add_messages


class WorkflowState(TypedDict, total=False):
    # Conversation basics
    thread_id: str
    turn_id: str
    messages: Annotated[list[BaseMessage], add_messages]

    query: str
    in_scope: bool

    # Retrieval + generation
    chunks: list[Document]
    citations: list[dict[str, str]]

    answer: str
