from typing import Any, Dict, List, Optional, Sequence, Union

from langchain_core.documents import Document
from langgraph.runtime import Runtime

from alayaflow.component.model import ModelManager
from alayaflow.utils.logger import AlayaFlowLogger

from ..schemas import WorkflowState


logger = AlayaFlowLogger()


class JinaRerankerComponent:
    def __init__(self, *, model_id: str, top_n: Optional[int] = None) -> None:
        self.model_id = model_id
        self.top_n = top_n
        self._model_manager = ModelManager()

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
        return self._model_manager.get_model(self.model_id, runtime_config=bind_kwargs)

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
            "Invoke JinaReranker.\n"
            f"reranker: {self.model_id}\n"
            f"top_n: {self.top_n}\n"
            f"query: {query}\n"
            f"in_docs: {len(documents)}\n"
            f"out_docs: {len(reranked_docs)}"
        )
        return reranked_docs


def create_rerank_node():
    rerank_model_id = "jina-reranker"
    top_n = 5

    def rerank_node(state: WorkflowState, runtime: Runtime[Any]):
        query = state.get("query")
        chunks = state.get("chunks", [])

        if not query or not chunks:
            logger.debug(
                f"Rerank node skipped: query_empty={not bool(query)}, chunks_empty={not bool(chunks)}"
            )
            return {"chunks": chunks}

        model_id = rerank_model_id or getattr(getattr(runtime, "context", None), "rerank_model_id", None)
        if model_id is None:
            logger.warning("Rerank model id missing, skip rerank")
            return {"chunks": chunks}

        try:
            reranker = JinaRerankerComponent(model_id=model_id, top_n=top_n)
            reranked_chunks = reranker(query=query, docs=chunks)
            logger.debug(
                "Rerank done. "
                f"in_chunks={len(chunks)}, out_chunks={len(reranked_chunks)}, model_id={model_id}"
            )
            return {"chunks": reranked_chunks}
        except Exception as e:
            logger.error(f"Rerank error {type(e).__name__}: {e}")
            return {"chunks": chunks}

    return rerank_node
