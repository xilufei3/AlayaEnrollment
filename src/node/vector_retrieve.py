from __future__ import annotations

from typing import Any

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage
from langgraph.runtime import Runtime

from alayaflow.utils.logger import AlayaFlowLogger

from ..config import INTENT_COLLECTION_MAP
from ..schemas import WorkflowState


logger = AlayaFlowLogger()


class VectorRetrieveComponent:
    """
    Duck-typing vector retrieval component.
    Assumes injected client provides: client.search(...)
    """

    def __init__(
        self,
        *,
        client: Any,
        index: str,
        top_k: int = 5,
        collection_id: str | None = None,
    ) -> None:
        self.client = client
        self.index = index
        self.top_k = int(top_k)
        self.collection_id = collection_id

    @staticmethod
    def _to_text(content: Any) -> str:
        if isinstance(content, str):
            return content
        if content is None:
            return ""
        return str(content)

    @classmethod
    def _to_document(cls, item: Any) -> Document:
        if isinstance(item, Document):
            return item

        if isinstance(item, dict):
            payload = dict(item.get("payload") or {})
            page_content = (
                item.get("page_content")
                or item.get("content")
                or item.get("text")
                or payload.get("page_content")
                or payload.get("content")
                or payload.get("text")
                or ""
            )
            metadata = dict(payload)
            if "id" in item:
                metadata.setdefault("id", item["id"])
            if "score" in item:
                metadata.setdefault("score", item["score"])
            return Document(
                page_content=cls._to_text(page_content),
                metadata=metadata,
            )

        payload = getattr(item, "payload", None) or {}
        if isinstance(payload, dict):
            page_content = (
                getattr(item, "page_content", None)
                or getattr(item, "content", None)
                or getattr(item, "text", None)
                or payload.get("page_content")
                or payload.get("content")
                or payload.get("text")
                or ""
            )
            metadata = dict(payload)
            if hasattr(item, "id"):
                metadata.setdefault("id", getattr(item, "id"))
            if hasattr(item, "score"):
                metadata.setdefault("score", getattr(item, "score"))
            return Document(
                page_content=cls._to_text(page_content),
                metadata=metadata,
            )

        return Document(page_content=cls._to_text(item), metadata={})

    @staticmethod
    def _extract_hits(result: Any) -> list[Any]:
        if result is None:
            return []
        if isinstance(result, list):
            return result
        if isinstance(result, dict):
            hits = result.get("hits")
            if isinstance(hits, list):
                return hits
            results = result.get("results")
            if isinstance(results, list):
                return results
            return []
        hits = getattr(result, "hits", None)
        if isinstance(hits, list):
            return hits
        return []

    def __call__(
        self,
        *,
        query: str,
        user_id: str | None = None,
        collection_id: str | None = None,
    ) -> list[Document]:
        try:
            active_collection_id = collection_id or self.collection_id
            kwargs = {
                "query": query,
                "index": self.index,
                "top_k": self.top_k,
                "user_id": user_id,
            }
            if active_collection_id:
                kwargs["collection_id"] = active_collection_id
            raw = self.client.search(
                **kwargs,
            )
            hits = self._extract_hits(raw)
            return [self._to_document(hit) for hit in hits]
        except Exception as exc:
            logger.error(f"VectorRetrieveComponent error: {type(exc).__name__}: {exc}")
            return []


def create_vector_retrieve_node(
    *,
    client: Any,
    index: str,
    top_k: int = 5,
    collection_id: str | None = None,
):
    component = VectorRetrieveComponent(
        client=client,
        index=index,
        top_k=top_k,
        collection_id=collection_id,
    )

    def _extract_query(state: WorkflowState) -> str:
        query = state.get("query")
        if query:
            return str(query).strip()
        messages = state.get("messages") or []
        for message in reversed(messages):
            if isinstance(message, BaseMessage):
                if getattr(message, "type", "") in ("human", "user"):
                    content = getattr(message, "content", "")
                    if isinstance(content, str):
                        text = content.strip()
                        if text:
                            return text
            elif isinstance(message, dict):
                role = str(message.get("role", "")).lower()
                if role in ("user", "human"):
                    text = str(message.get("content", "")).strip()
                    if text:
                        return text
        return ""

    def vector_retrieve_node(state: WorkflowState, runtime: Runtime[Any]):
        query = _extract_query(state)
        if not query:
            logger.debug("Vector retrieve skipped: query is empty")
            return {"chunks": []}

        intent = str(state.get("intent") or "").strip()
        mapped_collection_id = INTENT_COLLECTION_MAP.get(intent)
        resolved_collection_id = collection_id or mapped_collection_id
        if not resolved_collection_id:
            logger.debug(
                "Vector retrieve skipped: collection not found for intent.\n"
                f"intent={intent}"
            )
            return {"chunks": []}

        user_id = getattr(getattr(runtime, "context", None), "user_id", None)
        chunks = component(
            query=query,
            user_id=user_id,
            collection_id=resolved_collection_id,
        )
        logger.debug(
            "Vector retrieve done.\n"
            f"index={index}\n"
            f"intent={intent}\n"
            f"collection_id={resolved_collection_id}\n"
            f"top_k={top_k}\n"
            f"query={query}\n"
            f"chunks={len(chunks)}"
        )
        return {"chunks": chunks}

    return vector_retrieve_node
