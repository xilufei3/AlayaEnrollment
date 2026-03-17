from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pymilvus import DataType, MilvusClient

from .interfaces import VectorStore
from .models import (
    CollectionExistsRequest,
    CollectionExistsResult,
    CollectionInfo,
    CreateCollectionRequest,
    CreateHybridCollectionRequest,
    DeleteRequest,
    DeleteResult,
    DropCollectionRequest,
    SearchHit,
    SearchRequest,
    SearchResult,
    SearchSparseRequest,
    UpsertRequest,
    UpsertResult,
)


PRIMARY_KEY_MAX_LENGTH = 512
HYBRID_FIELD_CONTENT = "content"
HYBRID_FIELD_SPARSE = "sparse_vector"


class MilvusVectorStore(VectorStore):
    """Milvus implementation of VectorStore for RAG-oriented workloads."""

    def __init__(self, client: MilvusClient) -> None:
        self._client = client

    # ---------- collection management ----------

    def create_collection(self, req: CreateCollectionRequest) -> CollectionInfo:
        exists = self._client.has_collection(collection_name=req.name)
        if not exists:
            self._client.create_collection(
                collection_name=req.name,
                dimension=req.dimension,
                metric_type=req.metric.upper(),
                primary_field_name="id",
                id_type=DataType.VARCHAR,
                max_length=PRIMARY_KEY_MAX_LENGTH,
            )

        return CollectionInfo(
            name=req.name,
            dimension=req.dimension,
            metric=req.metric,
        )

    def create_hybrid_collection(self, req: CreateHybridCollectionRequest) -> CollectionInfo:
        """创建支持混合检索的 collection：id, vector, content(VARCHAR), sparse_vector(SPARSE_FLOAT_VECTOR)。"""
        if self._client.has_collection(collection_name=req.name):
            return CollectionInfo(name=req.name, dimension=req.dimension, metric=req.metric)
        try:
            schema = self._client.create_schema(
                auto_id=False,
                enable_dynamic_field=True,
                primary_field_name="id",
            )
            schema.add_field(field_name="id", datatype=DataType.VARCHAR, max_length=PRIMARY_KEY_MAX_LENGTH, is_primary=True)
            schema.add_field(field_name="vector", datatype=DataType.FLOAT_VECTOR, dim=req.dimension)
            schema.add_field(field_name=HYBRID_FIELD_CONTENT, datatype=DataType.VARCHAR, max_length=req.content_max_length)
            schema.add_field(field_name=HYBRID_FIELD_SPARSE, datatype=DataType.SPARSE_FLOAT_VECTOR)
            self._client.create_collection(
                collection_name=req.name,
                schema=schema,
                metric_type=req.metric.upper(),
            )
        except Exception as e:
            raise RuntimeError(f"create_hybrid_collection failed: {e}") from e
        return CollectionInfo(name=req.name, dimension=req.dimension, metric=req.metric)

    def drop_collection(self, req: DropCollectionRequest) -> None:
        if self._client.has_collection(collection_name=req.name):
            self._client.drop_collection(collection_name=req.name)

    def collection_exists(self, req: CollectionExistsRequest) -> CollectionExistsResult:
        return CollectionExistsResult(
            exists=self._client.has_collection(collection_name=req.name)
        )

    def _ensure_loaded(self, collection_name: str) -> None:
        """Search 前确保 collection 已 load 到内存，否则 Milvus 报 collection not loaded。"""
        try:
            state = self._client.get_load_state(collection_name=collection_name)
            if state is not None and str(state).upper() == "LOADED":
                return
        except Exception:
            pass
        try:
            self._client.load_collection(collection_name=collection_name, replica_number=1)
        except Exception as e:
            if "already loaded" in str(e).lower() or "loaded" in str(e).lower():
                return
            raise

    def ensure_index_and_load(
        self,
        collection_name: str,
        dimension: int,
        metric: str = "cosine",
        is_hybrid: bool = False,
    ) -> None:
        """
        为已写入数据的 collection 创建索引并 load，供检索使用。
        若已有索引则只执行 load。需在 insert 完成后调用（建议先 flush）。
        """
        self._client.flush(collection_name=collection_name)
        existing = self._client.list_indexes(collection_name=collection_name)
        if existing and "vector" in existing:
            try:
                self._client.load_collection(collection_name=collection_name, replica_number=1)
            except Exception as e:
                if "already loaded" in str(e).lower():
                    return
                raise
            return

        index_params = self._client.prepare_index_params()
        metric_upper = (metric or "cosine").upper()
        index_params.add_index(
            field_name="vector",
            index_type="IVF_FLAT",
            index_name="vector_idx",
            metric_type=metric_upper,
            params={"nlist": 1024},
        )
        if is_hybrid:
            index_params.add_index(
                field_name=HYBRID_FIELD_SPARSE,
                index_type="SPARSE_INVERTED_INDEX",
                index_name="sparse_idx",
                metric_type="IP",
                params={},
            )
        self._client.create_index(
            collection_name=collection_name,
            index_params=index_params,
            sync=True,
        )
        self._client.load_collection(collection_name=collection_name, replica_number=1)

    def ensure_index_and_load_auto(self, collection_name: str, metric: str = "cosine") -> None:
        """
        根据 collection 的 schema 推断 dimension 与是否 hybrid，再建索引并 load。
        用于已有数据但未建索引的 collection（如历史导入未执行 ensure_index_and_load 时）。
        """
        desc = self._client.describe_collection(collection_name=collection_name)
        dimension: int | None = None
        is_hybrid = False
        for f in desc.get("fields") or []:
            name = f.get("name") or ""
            if name == "vector":
                params = f.get("params") or {}
                dimension = params.get("dim")
                if dimension is not None:
                    dimension = int(dimension)
            if name == HYBRID_FIELD_SPARSE:
                is_hybrid = True
        if dimension is None:
            raise ValueError(
                f"describe_collection did not find vector field with dim: {collection_name}"
            )
        self.ensure_index_and_load(
            collection_name=collection_name,
            dimension=dimension,
            metric=metric,
            is_hybrid=is_hybrid,
        )

    # ---------- data operations ----------

    def upsert(self, req: UpsertRequest) -> UpsertResult:
        rows: list[dict[str, Any]] = []

        for record in req.records:
            rows.append(
                {
                    "id": record.id,
                    "vector": list(record.vector),
                    **dict(record.metadata),
                }
            )

        if not rows:
            return UpsertResult(written=0)

        self._client.upsert(
            collection_name=req.collection,
            data=rows,
        )

        return UpsertResult(written=len(rows))

    def delete(self, req: DeleteRequest) -> DeleteResult:
        if not req.ids:
            return DeleteResult(deleted=0)

        result = self._client.delete(
            collection_name=req.collection,
            filter=self._build_ids_filter(req.ids),
        )

        deleted = 0
        if isinstance(result, dict):
            deleted = int(result.get("delete_count", 0) or 0)

        return DeleteResult(deleted=deleted)

    def search(self, req: SearchRequest) -> SearchResult:
        self._ensure_loaded(req.collection)
        search_kwargs: dict[str, Any] = {
            "collection_name": req.collection,
            "data": [list(req.query_vector)],
            "anns_field": "vector",
            "limit": req.top_k,
            "output_fields": ["*"],
        }
        if req.filter_expression:
            search_kwargs["filter"] = req.filter_expression

        raw = self._client.search(**search_kwargs)

        hits: list[SearchHit] = []
        if not raw:
            return SearchResult(hits=hits)

        # Single query search: usually take first result set.
        for item in raw[0]:
            entity = dict(item.get("entity", {}))
            entity.pop("id", None)
            entity.pop("vector", None)
            entity.pop(HYBRID_FIELD_SPARSE, None)

            hits.append(
                SearchHit(
                    id=str(item["id"]),
                    score=float(item.get("distance", item.get("score", 0.0))),
                    metadata=entity,
                )
            )

        return SearchResult(hits=hits)

    def search_sparse(self, req: SearchSparseRequest) -> SearchResult:
        """稀疏向量检索（BM25），用于混合检索的一路。"""
        if not req.query_sparse:
            return SearchResult(hits=[])
        self._ensure_loaded(req.collection)
        sparse_data = [dict(req.query_sparse)]
        search_kwargs: dict[str, Any] = {
            "collection_name": req.collection,
            "data": sparse_data,
            "anns_field": HYBRID_FIELD_SPARSE,
            "search_params": {"metric_type": "IP", "params": {}},
            "limit": req.top_k,
            "output_fields": ["*"],
        }
        if req.filter_expression:
            search_kwargs["filter"] = req.filter_expression
        try:
            raw = self._client.search(**search_kwargs)
        except Exception:
            return SearchResult(hits=[])
        hits: list[SearchHit] = []
        if raw and raw[0]:
            for item in raw[0]:
                entity = dict(item.get("entity", {}))
                entity.pop("id", None)
                entity.pop("vector", None)
                entity.pop(HYBRID_FIELD_SPARSE, None)
                hits.append(
                    SearchHit(
                        id=str(item["id"]),
                        score=float(item.get("distance", item.get("score", 0.0))),
                        metadata=entity,
                    )
                )
        return SearchResult(hits=hits)

    @staticmethod
    def _rrf_fuse(
        vector_hits: list[SearchHit],
        sparse_hits: list[SearchHit],
        k: int = 60,
    ) -> list[SearchHit]:
        """RRF 融合两路检索结果。"""
        scores: dict[str, float] = {}
        for rank, hit in enumerate(vector_hits, start=1):
            scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (k + rank)
        for rank, hit in enumerate(sparse_hits, start=1):
            scores[hit.id] = scores.get(hit.id, 0.0) + 1.0 / (k + rank)
        seen: set[str] = set()
        fused: list[SearchHit] = []
        for hid in sorted(scores.keys(), key=lambda x: -scores[x]):
            if hid in seen:
                continue
            seen.add(hid)
            for h in vector_hits + sparse_hits:
                if h.id == hid:
                    fused.append(SearchHit(id=h.id, score=scores[hid], metadata=h.metadata))
                    break
        return fused

    # ---------- helpers ----------

    @staticmethod
    def _build_ids_filter(ids: Sequence[str]) -> str:
        quoted = ", ".join(f'"{item}"' for item in ids)
        return f"id in [{quoted}]"
