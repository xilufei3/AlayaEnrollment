from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.documents import Document

from alayaflow.utils.logger import AlayaFlowLogger

from ...config import RERANK_MODEL_ID, RERANK_TOP_N
from ...node.model_provider import get_model
from ..schemas import RAGState


logger = AlayaFlowLogger()


class JinaRerankerComponent:
    def __init__(self, *, model_id: str, top_n: Optional[int] = None) -> None:
        self.model_id = model_id
        self.top_n = top_n

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
        bind_kwargs: Dict[str, Any] = {}
        if self.top_n is not None:
            bind_kwargs["top_n"] = int(self.top_n)
        return get_model(self.model_id, **bind_kwargs)

    def __call__(
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

        reranked_docs: List[Document] = reranker.compress_documents(
            documents=documents,
            query=query,
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
    def rerank_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        chunks = list(state.get("chunks") or [])

        if not query or not chunks:
            logger.debug(
                f"Rerank skipped: query_empty={not query}, chunks_empty={not chunks}"
            )
            return {"chunks": chunks}

        try:
            reranker = JinaRerankerComponent(model_id=RERANK_MODEL_ID, top_n=RERANK_TOP_N)
            reranked = reranker(query=query, docs=chunks)
            logger.debug(f"Rerank done. in={len(chunks)} out={len(reranked)}")
            return {"chunks": reranked}
        except Exception as exc:
            logger.error(f"Rerank error {type(exc).__name__}: {exc}")
            return {"chunks": chunks}

    return rerank_node
