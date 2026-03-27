from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.documents import Document

from ....config.settings import config
from ...llm import ModelRequestTimeoutError, get_model
from ..schemas import RAGState

logger = logging.getLogger(__name__)


class JinaRerankerComponent:
    def __init__(self, *, model_id: str, top_n: Optional[int] = None) -> None:
        self.model_id = model_id
        self.top_n = top_n
        self._bind_kwargs: Dict[str, Any] = {}
        if self.top_n is not None:
            self._bind_kwargs["top_n"] = int(self.top_n)
        self._reranker: Any | None = None

    def _to_documents(
        self,
        docs: Sequence[Union[Document, Dict[str, Any], str]],
    ) -> List[Document]:
        out: List[Document] = []
        for d in docs:
            if isinstance(d, Document):
                out.append(d)
            elif isinstance(d, dict):
                out.append(
                    Document(
                        page_content=str(d.get("page_content") or d.get("content") or ""),
                        metadata=dict(d.get("metadata") or {}),
                    )
                )
            else:
                out.append(Document(page_content=str(d), metadata={}))
        return out

    def _get_reranker(self) -> Any:
        if self._reranker is None:
            self._reranker = get_model(self.model_id, **self._bind_kwargs)
        return self._reranker

    async def __call__(
        self,
        *,
        query: str,
        docs: Sequence[Union[Document, Dict[str, Any], str]],
    ) -> List[Document]:
        reranker = self._get_reranker()
        documents = self._to_documents(docs)

        if not query or not documents:
            logger.debug(
                "JinaReranker short-circuit.\n"
                f"query_empty={not bool(query)} docs_empty={not bool(documents)}"
            )
            return documents

        reranked_docs: List[Document] = await asyncio.to_thread(
            lambda: reranker.compress_documents(
                documents=documents,
                query=query,
            )
        )
        logger.debug(
            "JinaReranker done.\n"
            f"model={self.model_id}\n"
            f"top_n={self.top_n}\n"
            f"in={len(documents)}\n"
            f"out={len(reranked_docs)}"
        )
        return reranked_docs


def create_rerank_node():
    reranker = JinaRerankerComponent(
        model_id=config.rerank.model_id,
        top_n=config.rerank.top_n,
    )

    async def rerank_node(state: RAGState) -> dict[str, Any]:
        search_plan = state.get("search_plan") or {}
        rewritten_query = str(search_plan.get("vector_query") or "").strip()
        query = rewritten_query or str(state.get("query") or "").strip()
        vector_chunks = list(state.get("vector_chunks") or [])

        if not query or not vector_chunks:
            logger.debug(
                f"Rerank skipped: query_empty={not query}, "
                f"vector_chunks_empty={not vector_chunks}"
            )
            return {"reranked_vector_chunks": vector_chunks}

        try:
            reranked = await reranker(query=query, docs=vector_chunks)
            logger.debug(f"Rerank done. in={len(vector_chunks)} out={len(reranked)}")
            return {"reranked_vector_chunks": reranked}
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            logger.error(f"Rerank error {type(exc).__name__}: {exc}")
            return {"reranked_vector_chunks": vector_chunks}

    return rerank_node
