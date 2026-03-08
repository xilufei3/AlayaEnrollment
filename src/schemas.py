from __future__ import annotations

from typing import Any, Literal, TypedDict

from langchain_core.messages import BaseMessage
from langchain_core.documents import Document
from pydantic import BaseModel, Field


class WorkflowState(TypedDict, total=False):
    # 会话基础
    thread_id: str
    turn_id: str
    messages: list[BaseMessage]

    query: str
    intent: str
    
    chunks: list[Document]

    answer: str

