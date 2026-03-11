from __future__ import annotations

import os
from pathlib import Path

from packages.alayadata.client import AlayaDataClient
from packages.retriever.bm25_utils import BM25SparseEncoder
from packages.vector_store.interfaces import VectorStore
from packages.vector_store.models import SearchRequest, SearchResult, SearchSparseRequest


def _default_bm25_state_dir() -> Path:
    return Path(os.environ.get("BM25_STATE_DIR", "data/bm25_state"))


class RetrieverService:
    """Query -> Alaya embedding -> vector search；可选 hybrid（向量 + BM25）检索。"""

    def __init__(
        self,
        store: VectorStore,
        alaya_client: AlayaDataClient,
        bm25_state_dir: str | Path | None = None,
    ) -> None:
        self._store = store
        self._alaya_client = alaya_client
        self._bm25_state_dir = Path(bm25_state_dir) if bm25_state_dir else _default_bm25_state_dir()

    def retrieve(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        filter_expression: str | None = None,
    ) -> SearchResult:
        embedding = self._alaya_client.embed_query(query)

        return self._store.search(
            SearchRequest(
                collection=collection,
                query_vector=embedding.embedding_vector,
                top_k=top_k,
                filter_expression=filter_expression,
            )
        )

    def retrieve_hybrid(
        self,
        collection: str,
        query: str,
        top_k: int = 5,
        filter_expression: str | None = None,
        bm25_state_dir: str | Path | None = None,
    ) -> SearchResult:
        """混合检索：向量 + BM25 稀疏，RRF 融合。需 collection 为 hybrid 且已保存 BM25 状态。"""
        state_path = Path(bm25_state_dir or self._bm25_state_dir) / f"{collection}.json"
        if not state_path.exists() or not hasattr(self._store, "search_sparse"):
            return self.retrieve(collection=collection, query=query, top_k=top_k, filter_expression=filter_expression)
        encoder = BM25SparseEncoder.load(state_path)
        query_sparse = encoder.encode_query(query)
        if not query_sparse:
            return self.retrieve(collection=collection, query=query, top_k=top_k, filter_expression=filter_expression)
        embedding = self._alaya_client.embed_query(query)
        vector_result = self._store.search(
            SearchRequest(
                collection=collection,
                query_vector=embedding.embedding_vector,
                top_k=top_k * 2,
                filter_expression=filter_expression,
            )
        )
        sparse_result = self._store.search_sparse(
            SearchSparseRequest(
                collection=collection,
                query_sparse=query_sparse,
                top_k=top_k * 2,
                filter_expression=filter_expression,
            )
        )
        fused = self._store._rrf_fuse(vector_result.hits, sparse_result.hits, k=60)
        return SearchResult(hits=fused[:top_k])
