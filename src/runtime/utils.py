from __future__ import annotations

from datetime import datetime, timezone
from typing import Any


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def jsonable(value: Any) -> Any:
    """Recursively convert LangChain objects to JSON-serialisable primitives."""
    from langchain_core.documents import Document
    from langchain_core.messages import BaseMessage

    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, BaseMessage):
        return {
            "type": getattr(value, "type", "unknown"),
            "content": getattr(value, "content", ""),
            "id": getattr(value, "id", None),
        }
    if isinstance(value, Document):
        return {
            "page_content": value.page_content,
            "metadata": dict(value.metadata or {}),
        }
    if isinstance(value, list):
        return [jsonable(v) for v in value]
    if isinstance(value, tuple):
        return [jsonable(v) for v in value]
    if isinstance(value, dict):
        return {str(k): jsonable(v) for k, v in value.items()}
    if hasattr(value, "model_dump"):
        return jsonable(value.model_dump())
    return str(value)


def extract_query_from_input(input_payload: Any) -> str:
    """Extract user query from various input formats (str, dict, messages)."""
    if isinstance(input_payload, str):
        return input_payload.strip()
    if not isinstance(input_payload, dict):
        return ""
    query = input_payload.get("query")
    if isinstance(query, str) and query.strip():
        return query.strip()

    messages = input_payload.get("messages")
    if isinstance(messages, list):
        for msg in reversed(messages):
            if not isinstance(msg, dict):
                continue
            if str(msg.get("type", "")).lower() not in ("human", "user"):
                continue
            content = msg.get("content")
            if isinstance(content, str) and content.strip():
                return content.strip()
            if isinstance(content, list):
                parts: list[str] = []
                for part in content:
                    if isinstance(part, str):
                        parts.append(part)
                    elif isinstance(part, dict) and part.get("type") == "text":
                        parts.append(str(part.get("text", "")))
                text = " ".join([p for p in parts if p]).strip()
                if text:
                    return text
    return ""
