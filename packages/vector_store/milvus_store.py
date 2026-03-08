from __future__ import annotations

from typing import Any, Iterable

from .errors import (
    DimensionMismatch,
    IndexAlreadyExists,
    IndexNotFound,
    InternalStoreError,
    InvalidArgument,
    StoreUnavailable,
    VectorStoreError,
)
from .interfaces import VectorStore
from .models import (
    CreateIndexRequest,
    DeleteRequest,
    IndexMeta,
    IndexStats,
    SearchHit,
    SearchRequest,
    SearchResult,
    UpsertRequest,
    UpsertResult,
    VectorItem,
)


class PyMilvusStore(VectorStore):
    """Direct wrapper around pymilvus MilvusClient."""

    def __init__(
        self,
        *,
        uri: str | None = None,
        token: str | None = None,
        db_name: str | None = None,
        client: Any | None = None,
        collection_prefix: str = "adm_",
        vector_field: str = "embedding",
        id_field: str = "id",
        index_params: dict[str, Any] | None = None,
    ) -> None:
        self._collection_prefix = collection_prefix
        self._vector_field = vector_field
        self._id_field = id_field
        self._index_params = index_params or {"index_type": "HNSW", "metric_type": "COSINE"}
        self._meta_cache: dict[str, IndexMeta] = {}

        if client is not None:
            self._client = client
            return

        if uri is None:
            raise InvalidArgument("uri is required when client is not provided")

        try:
            from pymilvus import MilvusClient  # type: ignore

            kwargs: dict[str, Any] = {"uri": uri}
            if token:
                kwargs["token"] = token
            if db_name:
                kwargs["db_name"] = db_name
            self._client = MilvusClient(**kwargs)
        except ImportError as exc:
            raise StoreUnavailable("pymilvus is not installed") from exc
        except Exception as exc:
            raise StoreUnavailable(f"failed to initialize Milvus client: {exc}") from exc

    def create_index(self, req: CreateIndexRequest) -> IndexMeta:
        if not req.index or req.dimension <= 0:
            raise InvalidArgument("index and positive dimension are required")

        collection = self._collection_name(req.index)
        if self._has_collection(collection):
            raise IndexAlreadyExists(f"index '{req.index}' already exists")

        try:
            created_with_advanced_api = False
            try:
                self._client.create_collection(
                    collection_name=collection,
                    dimension=req.dimension,
                    metric_type=req.metric,
                    primary_field_name=self._id_field,
                    id_type="string",
                    max_length=512,
                    vector_field_name=self._vector_field,
                    auto_id=False,
                )
                created_with_advanced_api = True
            except TypeError:
                # Fallback for fake/legacy clients with simpler signatures.
                self._client.create_collection(
                    collection_name=collection,
                    dimension=req.dimension,
                    metric_type=req.metric,
                )
            if hasattr(self._client, "create_index") and not created_with_advanced_api:
                use_prepared = False
                index_params: Any = self._index_params
                if hasattr(self._client, "prepare_index_params"):
                    prepared = self._client.prepare_index_params()
                    base = dict(self._index_params)
                    idx_type = base.get("index_type", "HNSW")
                    metric = base.get("metric_type", req.metric)
                    extra = base.get("params", {})
                    prepared.add_index(
                        field_name=self._vector_field,
                        index_type=idx_type,
                        metric_type=metric,
                        params=extra,
                    )
                    index_params = prepared
                    use_prepared = True
                if use_prepared:
                    self._client.create_index(
                        collection_name=collection,
                        index_params=index_params,
                    )
                else:
                    self._client.create_index(
                        collection_name=collection,
                        field_name=self._vector_field,
                        index_params=index_params,
                    )
            if hasattr(self._client, "load_collection"):
                self._client.load_collection(collection_name=collection)
        except Exception as exc:
            raise self._map_exception(exc)

        meta = IndexMeta(
            index=req.index,
            collection=collection,
            dimension=req.dimension,
            metric=req.metric,
            status="ready",
        )
        self._meta_cache[req.index] = meta
        return meta

    def upsert(self, req: UpsertRequest) -> UpsertResult:
        if not req.items:
            raise InvalidArgument("upsert items must not be empty")
        meta = self._resolve_meta(req.index)

        rows = []
        for item in req.items:
            self._validate_dimension(item.vector, meta.dimension)
            rows.append(self._item_to_row(item))

        try:
            result = self._client.upsert(collection_name=meta.collection, data=rows)
            if hasattr(self._client, "flush"):
                self._client.flush(collection_name=meta.collection)
        except Exception as exc:
            raise self._map_exception(exc)

        upserted = self._extract_count(result, default=len(rows))
        return UpsertResult(upserted=upserted, failed=max(0, len(rows) - upserted))

    def search(self, req: SearchRequest) -> SearchResult:
        if req.top_k <= 0:
            raise InvalidArgument("top_k must be positive")
        meta = self._resolve_meta(req.index)
        self._validate_dimension(req.query_vector, meta.dimension)

        try:
            raw = self._client.search(
                collection_name=meta.collection,
                data=[list(req.query_vector)],
                limit=req.top_k,
                filter=req.filter_expr,
                output_fields=["*"],
            )
        except Exception as exc:
            raise self._map_exception(exc)

        hits = self._normalize_hits(raw)
        return SearchResult(hits=hits)

    def delete(self, req: DeleteRequest) -> None:
        meta = self._resolve_meta(req.index)
        if not req.ids and not req.filter_expr:
            raise InvalidArgument("either ids or filter_expr is required")

        try:
            if req.ids:
                self._client.delete(collection_name=meta.collection, ids=list(req.ids))
            else:
                self._client.delete(collection_name=meta.collection, filter=req.filter_expr)
        except Exception as exc:
            raise self._map_exception(exc)

    def stats(self, index: str) -> IndexStats:
        meta = self._resolve_meta(index)
        try:
            stats = self._client.get_collection_stats(collection_name=meta.collection)
            state = (
                self._client.get_load_state(collection_name=meta.collection)
                if hasattr(self._client, "get_load_state")
                else None
            )
        except Exception as exc:
            raise self._map_exception(exc)

        total = self._extract_row_count(stats)
        loaded = self._is_loaded(state)
        return IndexStats(
            index=meta.index,
            collection=meta.collection,
            total_entities=total,
            indexed_rows=total,
            loaded=loaded,
        )

    def drop_index(self, index: str) -> None:
        meta = self._resolve_meta(index)
        try:
            self._client.drop_collection(collection_name=meta.collection)
        except Exception as exc:
            raise self._map_exception(exc)
        self._meta_cache.pop(index, None)

    def close(self) -> None:
        if hasattr(self._client, "close"):
            self._client.close()

    def _collection_name(self, index: str) -> str:
        return f"{self._collection_prefix}{index}"

    def _has_collection(self, collection_name: str) -> bool:
        if hasattr(self._client, "has_collection"):
            return bool(self._client.has_collection(collection_name=collection_name))
        return False

    def _resolve_meta(self, index: str) -> IndexMeta:
        cached = self._meta_cache.get(index)
        if cached is not None:
            return cached

        collection = self._collection_name(index)
        if not self._has_collection(collection):
            raise IndexNotFound(f"index '{index}' not found")

        # Fallback when cache was lost; dimensions may be unknown here.
        raise IndexNotFound(f"index '{index}' is not initialized in current store instance")

    def _validate_dimension(self, vector: Iterable[float], expected: int) -> None:
        if len(list(vector)) != expected:
            raise DimensionMismatch(f"expected vector dimension {expected}")

    def _item_to_row(self, item: VectorItem) -> dict[str, Any]:
        row = {self._id_field: item.id, self._vector_field: list(item.vector)}
        row.update(dict(item.payload))
        return row

    @staticmethod
    def _extract_count(result: Any, default: int) -> int:
        if isinstance(result, dict):
            for key in ("upsert_count", "insert_count", "count"):
                if key in result:
                    try:
                        return int(result[key])
                    except Exception:
                        return default
        return default

    @staticmethod
    def _extract_row_count(result: Any) -> int:
        if isinstance(result, dict) and "row_count" in result:
            try:
                return int(result["row_count"])
            except Exception:
                return 0
        return 0

    @staticmethod
    def _is_loaded(state: Any) -> bool:
        if state is None:
            return False
        if isinstance(state, dict):
            raw = str(state.get("state", "")).lower()
            return raw in {"loaded", "loadstate.loaded", "3"}
        if isinstance(state, str):
            return state.lower() == "loaded"
        return bool(state)

    @staticmethod
    def _normalize_hits(raw: Any) -> list[SearchHit]:
        if not raw:
            return []

        first_level = raw[0] if isinstance(raw, list) and raw and isinstance(raw[0], list) else raw
        hits: list[SearchHit] = []
        for item in first_level:
            if isinstance(item, dict):
                hit_id = str(item.get("id", ""))
                score = float(item.get("score", item.get("distance", 0.0)))
                payload = item.get("entity", item.get("payload", {})) or {}
            else:
                hit_id = str(getattr(item, "id", ""))
                score = float(
                    getattr(item, "score", getattr(item, "distance", 0.0))
                )
                payload = getattr(item, "entity", getattr(item, "payload", {})) or {}
            hits.append(SearchHit(id=hit_id, score=score, payload=payload))
        return hits

    @staticmethod
    def _map_exception(exc: Exception) -> VectorStoreError:
        if isinstance(exc, VectorStoreError):
            return exc
        msg = str(exc).lower()
        if "not found" in msg:
            return IndexNotFound(str(exc))
        if "dimension" in msg:
            return DimensionMismatch(str(exc))
        return InternalStoreError(str(exc))
