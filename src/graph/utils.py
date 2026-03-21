from __future__ import annotations

import re
from typing import Any, Mapping, Sequence

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage

_YEAR_RANGE_HINTS: tuple[str, ...] = (
    "近几年",
    "近年来",
    "历年",
    "往年",
    "最近几年",
)
_YEAR_RANGE_PATTERN = r"近\d+年"


def to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
                else:
                    parts.append(str(item))
            else:
                parts.append(str(item))
        return " ".join(part for part in parts if part).strip()
    if content is None:
        return ""
    return str(content).strip()


def to_stream_piece(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict):
                if "text" in item:
                    parts.append(str(item["text"]))
                elif item.get("type") == "text":
                    parts.append(str(item.get("text", "")))
        return "".join(parts)
    if content is None:
        return ""
    return str(content)


def extract_query_from_state(state: Mapping[str, Any]) -> str:
    query = state.get("query")
    if query:
        return str(query).strip()

    messages = state.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, BaseMessage):
            if getattr(msg, "type", "") in ("human", "user"):
                text = to_text(getattr(msg, "content", ""))
                if text:
                    return text
        elif isinstance(msg, dict):
            role = str(msg.get("role", msg.get("type", ""))).lower()
            if role in ("user", "human"):
                text = to_text(msg.get("content", ""))
                if text:
                    return text
    return ""


def normalize_messages(raw_messages: Sequence[Any]) -> list[BaseMessage]:
    normalized: list[BaseMessage] = []
    for msg in raw_messages:
        if isinstance(msg, BaseMessage):
            normalized.append(msg)
            continue
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", msg.get("type", ""))).lower()
        content = to_text(msg.get("content", ""))
        if not content:
            continue
        if role in ("user", "human"):
            normalized.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            normalized.append(AIMessage(content=content))
    return normalized


def chunk_texts(chunks: Sequence[Any]) -> list[str]:
    lines: list[str] = []
    for index, chunk in enumerate(chunks, start=1):
        if isinstance(chunk, Document):
            text = chunk.page_content
        elif isinstance(chunk, dict):
            text = str(chunk.get("page_content") or chunk.get("content") or chunk.get("text") or "")
        else:
            text = str(chunk)
        text = text.strip()
        if text:
            lines.append(f"[{index}] {text}")
    return lines


def query_prefers_year_range(
    query: str,
    *,
    hints: Sequence[str] = _YEAR_RANGE_HINTS,
    year_pattern: str = _YEAR_RANGE_PATTERN,
) -> bool:
    normalized = "".join(str(query).split())
    if not normalized:
        return False
    if any(hint in normalized for hint in hints):
        return True
    if not year_pattern:
        return False
    return bool(re.search(year_pattern, normalized))
