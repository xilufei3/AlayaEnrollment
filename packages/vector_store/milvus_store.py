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
    DeleteRequest,
    DeleteResult,
    DropCollectionRequest,
    SearchHit,
    SearchRequest,
    SearchResult,
    UpsertRequest,
    UpsertResult,
)


# 主键为字符串时的最大长度（VARCHAR）
PRIMARY_KEY_MAX_LENGTH = 512


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

    def drop_collection(self, req: DropCollectionRequest) -> None:
        if self._client.has_collection(collection_name=req.name):
            self._client.drop_collection(collection_name=req.name)

    def collection_exists(self, req: CollectionExistsRequest) -> CollectionExistsResult:
        return CollectionExistsResult(
            exists=self._client.has_collection(collection_name=req.name)
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
        raw = self._client.search(
            collection_name=req.collection,
            data=[list(req.query_vector)],
            limit=req.top_k,
            output_fields=["*"],
        )

        hits: list[SearchHit] = []
        if not raw:
            return SearchResult(hits=hits)

        # 单个 query，一般取第一组结果
        for item in raw[0]:
            entity = dict(item.get("entity", {}))
            entity.pop("id", None)
            entity.pop("vector", None)

            hits.append(
                SearchHit(
                    id=str(item["id"]),
                    score=float(item.get("distance", item.get("score", 0.0))),
                    metadata=entity,
                )
            )

        return SearchResult(hits=hits)

    # ---------- helpers ----------

    @staticmethod
    def _build_ids_filter(ids: Sequence[str]) -> str:
        quoted = ", ".join(f'"{item}"' for item in ids)
        return f"id in [{quoted}]"