from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Sequence


@dataclass(slots=True)
class _SearchRequestCompat:
    index: str
    query_vector: Sequence[float]
    top_k: int = 8
    filter_expr: str | None = None


class VectorStoreClientAdapter:
    """
    Adapter for packages/vector_store style client:
      store.search(req: SearchRequest) -> SearchResult

    Adapts to retrieval-node expected signature:
      search(query=..., index=..., top_k=..., user_id=..., collection_id=...)
    """

    def __init__(
        self,
        *,
        vector_store: Any,
        embed_query: Callable[[str], Sequence[float]],
    ) -> None:
        self.vector_store = vector_store
        self.embed_query = embed_query

    @staticmethod
    def _hit_to_dict(hit: Any) -> dict[str, Any]:
        if isinstance(hit, dict):
            return {
                "id": str(hit.get("id", "")),
                "score": float(hit.get("score", 0.0)),
                "payload": dict(hit.get("payload") or {}),
            }

        return {
            "id": str(getattr(hit, "id", "")),
            "score": float(getattr(hit, "score", 0.0)),
            "payload": dict(getattr(hit, "payload", {}) or {}),
        }

    def search(
        self,
        *,
        query: str,
        index: str,
        top_k: int = 5,
        user_id: str | None = None,  # kept for compatibility; unused
        collection_id: str | None = None,
    ) -> dict[str, Any]:
        _ = user_id
        target_index = str(collection_id or index)
        query_vector = list(self.embed_query(query))

        req = _SearchRequestCompat(
            index=target_index,
            query_vector=query_vector,
            top_k=int(top_k),
        )
        result = self.vector_store.search(req)

        hits = []
        if isinstance(result, dict):
            hits = result.get("hits", []) or []
        else:
            hits = getattr(result, "hits", []) or []

        return {"hits": [self._hit_to_dict(hit) for hit in hits]}

