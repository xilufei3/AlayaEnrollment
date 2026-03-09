from __future__ import annotations

from langchain_core.documents import Document
from langchain_core.messages import BaseMessage

from alayaflow.utils.logger import AlayaFlowLogger

from packages.retriever.service import RetrieverService
from packages.vector_store.models import SearchHit

from ..config import INTENT_COLLECTION_MAP
from ..schemas import WorkflowState


logger = AlayaFlowLogger()


def _hit_to_document(hit: SearchHit) -> Document:
    metadata = dict(hit.metadata or {})
    page_content = (
        metadata.pop("page_content", None)
        or metadata.pop("content", None)
        or metadata.pop("text", None)
        or ""
    )
    metadata["id"] = hit.id
    metadata["score"] = hit.score
    return Document(page_content=str(page_content), metadata=metadata)


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


def create_vector_retrieve_node(
    *,
    retriever: RetrieverService,
    top_k: int = 5,
):
    def vector_retrieve_node(state: WorkflowState):
        query = _extract_query(state)
        if not query:
            logger.debug("Vector retrieve skipped: query is empty")
            return {"chunks": []}

        intent = str(state.get("intent") or "").strip()
        collection = INTENT_COLLECTION_MAP.get(intent)
        if not collection:
            logger.debug(
                "Vector retrieve skipped: collection not found for intent.\n"
                f"intent={intent}"
            )
            return {"chunks": []}

        result = retriever.retrieve(collection=collection, query=query, top_k=top_k)
        chunks = [_hit_to_document(hit) for hit in result.hits]
        logger.debug(
            "Vector retrieve done.\n"
            f"intent={intent}\n"
            f"collection={collection}\n"
            f"top_k={top_k}\n"
            f"query={query}\n"
            f"chunks={len(chunks)}"
        )
        return {"chunks": chunks}

    return vector_retrieve_node
