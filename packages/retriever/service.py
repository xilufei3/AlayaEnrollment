from __future__ import annotations

from packages.vector_store.interfaces import VectorStore
from packages.vector_store.models import SearchRequest, SearchResult
from packages.alayadata.client import AlayaDataClient


class RetrieverService:
    """Query -> Alaya embedding -> vector search."""

    def __init__(
        self,
        store: VectorStore,
        alaya_client: AlayaDataClient,
    ) -> None:
        self._store = store
        self._alaya_client = alaya_client

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
