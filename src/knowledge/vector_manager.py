from __future__ import annotations

import logging
import threading
from typing import Any

from ..config.settings import config
from .embedder import get_embedder

logger = logging.getLogger(__name__)

SEARCH_VECTOR = "vector"
SEARCH_HYBRID = "hybrid"
SEARCH_SPARSE = "sparse"


class VectorManager:
    _instance: "VectorManager | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "VectorManager":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    obj = super().__new__(cls)
                    obj._initialized = False
                    cls._instance = obj
        return cls._instance

    def __init__(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            self._setup()
            self._initialized = True

    def _setup(self) -> None:
        from pymilvus import MilvusClient

        logger.info("VectorManager: connecting to Milvus ...")
        self._client = MilvusClient(uri=config.milvus.uri)
        self._collection = config.milvus.collection_name
        self._embedder = get_embedder()
        try:
            self._client.load_collection(self._collection)
        except Exception as exc:
            logger.warning("load_collection('%s') on startup: %s", self._collection, exc)
        logger.info("VectorManager: initialized")

    def ensure_collection(self) -> None:
        from pymilvus import CollectionSchema, DataType, FieldSchema, Function, FunctionType

        if self._client.has_collection(self._collection):
            logger.info("Collection '%s' already exists, skipping creation", self._collection)
            return

        fields = [
            FieldSchema("id", DataType.INT64, is_primary=True, auto_id=True),
            FieldSchema(
                "content",
                DataType.VARCHAR,
                max_length=4096,
                enable_analyzer=True,
                analyzer_params={"type": "chinese"},
            ),
            FieldSchema("dense", DataType.FLOAT_VECTOR, dim=config.milvus.embed_dim),
            FieldSchema("sparse", DataType.SPARSE_FLOAT_VECTOR),
            FieldSchema("source_file", DataType.VARCHAR, max_length=256, nullable=True),
            FieldSchema("category", DataType.VARCHAR, max_length=64, nullable=True),
        ]

        bm25_fn = Function(
            name="bm25",
            function_type=FunctionType.BM25,
            input_field_names=["content"],
            output_field_names=["sparse"],
        )

        schema = CollectionSchema(
            fields=fields,
            functions=[bm25_fn],
            description="Knowledge base collection",
        )
        self._client.create_collection(
            collection_name=self._collection,
            schema=schema,
        )

        index_params = self._client.prepare_index_params()
        index_params.add_index(
            field_name="dense",
            index_type="HNSW",
            metric_type="COSINE",
            params={"M": 16, "efConstruction": 200},
        )
        index_params.add_index(
            field_name="sparse",
            index_type="SPARSE_INVERTED_INDEX",
            metric_type="BM25",
        )
        self._client.create_index(self._collection, index_params)
        self._client.load_collection(self._collection)
        logger.info("Collection '%s' created and loaded", self._collection)

    def drop_collection(self) -> None:
        self._client.drop_collection(self._collection)
        logger.warning("Collection '%s' dropped", self._collection)

    def collection_stats(self) -> dict[str, Any]:
        stats = self._client.get_collection_stats(self._collection)
        return {"collection": self._collection, "row_count": stats.get("row_count", 0)}

    def insert(self, records: list[dict[str, Any]], *, flush: bool = True) -> int:
        """
        批量导入时可传 flush=False 跳过逐次刷盘，最后统一调用 flush() 即可。
        """
        if not records:
            return 0

        valid = []
        for record in records:
            if not record.get("content") or not record.get("dense"):
                logger.warning("Skipping record without content or dense vector")
                continue
            valid.append(record)

        if not valid:
            return 0

        self._client.insert(collection_name=self._collection, data=valid)
        if flush:
            self._client.flush(self._collection)
        logger.info("Inserted %d records", len(valid))
        return len(valid)

    def flush(self) -> None:
        """手动刷盘，批量导入结束后调用一次即可"""
        self._client.flush(self._collection)
        logger.info("Collection '%s' flushed", self._collection)

    def insert_chunks(self, chunks: list[dict[str, Any]], *, flush: bool = True) -> int:
        prepared: list[dict[str, Any]] = []
        for chunk in chunks:
            content = chunk.get("content_md") or chunk.get("content")
            vector = (
                chunk.get("embedding_vector")
                or chunk.get("embedding")
                or chunk.get("dense")
            )
            metadata = chunk.get("metadata")
            if not isinstance(metadata, dict):
                metadata = {}

            if (
                not isinstance(content, str)
                or not content
            ):
                logger.warning("Skipping invalid chunk: empty content")
                continue

            normalized_vector: list[float] | None = None
            if isinstance(vector, list) and vector and all(isinstance(x, (int, float)) for x in vector):
                normalized_vector = [float(x) for x in vector]

            prepared.append(
                {
                    "content": content,
                    "dense": normalized_vector,
                    "source_file": chunk.get("source_file") or metadata.get("source_file") or "",
                    "category": chunk.get("category") or metadata.get("category") or "",
                }
            )

        if not prepared:
            return 0

        if config.embedding.use_custom:
            logger.info("Custom embedding is enabled; re-embedding %d chunks before insert", len(prepared))
            embedded_vectors = self._embedder.embed_texts([record["content"] for record in prepared])
            for record, vector in zip(prepared, embedded_vectors, strict=True):
                record["dense"] = vector
        else:
            missing_indexes = [index for index, record in enumerate(prepared) if not record["dense"]]
            if missing_indexes:
                logger.info(
                    "Detected %d chunks without embedding; generating vectors with active embedder",
                    len(missing_indexes),
                )
                backfilled_vectors = self._embedder.embed_texts(
                    [prepared[index]["content"] for index in missing_indexes]
                )
                for index, vector in zip(missing_indexes, backfilled_vectors, strict=True):
                    prepared[index]["dense"] = vector

        records: list[dict[str, Any]] = []
        for record in prepared:
            dense = record.get("dense")
            if not isinstance(dense, list) or not dense:
                logger.warning("Skipping record without dense vector after embedding")
                continue
            records.append(
                {
                    "content": record["content"],
                    "dense": dense,
                    "source_file": record["source_file"],
                    "category": record["category"],
                }
            )

        return self.insert(records, flush=flush)

    def delete(self, ids: list[int]) -> None:
        self._client.delete(collection_name=self._collection, ids=ids)
        logger.info("Deleted %d records", len(ids))

    def search(
        self,
        query: str,
        top_k: int = 8,
        filter_expr: str | None = None,
        output_fields: list[str] | None = None,
        mode: str = SEARCH_HYBRID,
    ) -> list[dict[str, Any]]:
        self._client.load_collection(self._collection)
        selected_fields = output_fields or ["content", "source_file", "category"]

        if mode == SEARCH_VECTOR:
            return self._vector_search(query, top_k, filter_expr, selected_fields)
        if mode == SEARCH_SPARSE:
            return self._sparse_search(query, top_k, filter_expr, selected_fields)
        return self._hybrid_search(query, top_k, filter_expr, selected_fields)

    def _sparse_search(
        self,
        query: str,
        top_k: int,
        filter_expr: str | None,
        output_fields: list[str],
    ) -> list[dict[str, Any]]:
        try:
            results = self._client.search(
                collection_name=self._collection,
                data=[query],
                anns_field="sparse",
                limit=top_k,
                filter=filter_expr,
                search_params={"metric_type": "BM25"},
                output_fields=output_fields,
            )
        except Exception as exc:
            logger.error("sparse_search failed: %s", exc)
            return []
        return self._format(results, output_fields)

    def _vector_search(
        self,
        query: str,
        top_k: int,
        filter_expr: str | None,
        output_fields: list[str],
    ) -> list[dict[str, Any]]:
        try:
            query_vector = self._embedder.embed(query)
        except Exception as exc:
            logger.error("Embedding query failed: %s", exc)
            return []

        try:
            results = self._client.search(
                collection_name=self._collection,
                data=[query_vector],
                anns_field="dense",
                limit=top_k,
                filter=filter_expr,
                search_params={"metric_type": "COSINE", "params": {"ef": 100}},
                output_fields=output_fields,
            )
        except Exception as exc:
            logger.error("vector_search failed: %s", exc)
            return []

        return self._format(results, output_fields)

    def _hybrid_search(
        self,
        query: str,
        top_k: int,
        filter_expr: str | None,
        output_fields: list[str],
    ) -> list[dict[str, Any]]:
        from pymilvus import AnnSearchRequest, RRFRanker

        try:
            query_vector = self._embedder.embed(query)
        except Exception as exc:
            logger.warning("Embedding failed, fallback to sparse search: %s", exc)
            return self._sparse_search(query, top_k, filter_expr, output_fields)

        try:
            dense_req = AnnSearchRequest(
                data=[query_vector],
                anns_field="dense",
                param={"metric_type": "COSINE", "params": {"ef": 100}},
                limit=top_k,
                expr=filter_expr,
            )
            sparse_req = AnnSearchRequest(
                data=[query],
                anns_field="sparse",
                param={"metric_type": "BM25"},
                limit=top_k,
                expr=filter_expr,
            )
            results = self._client.hybrid_search(
                collection_name=self._collection,
                reqs=[dense_req, sparse_req],
                ranker=RRFRanker(k=60),
                limit=top_k,
                output_fields=output_fields,
            )
        except Exception as exc:
            logger.warning("hybrid_search failed, fallback to sparse search: %s", exc)
            return self._sparse_search(query, top_k, filter_expr, output_fields)

        return self._format(results, output_fields)

    @staticmethod
    def _format(results: Any, output_fields: list[str]) -> list[dict[str, Any]]:
        hits = results[0] if results else []
        return [
            {
                "id": hit["id"],
                "score": float(hit["distance"]),
                **{field: hit["entity"].get(field) for field in output_fields},
            }
            for hit in hits
        ]
