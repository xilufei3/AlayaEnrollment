from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Sequence

from packages.alayadata.client import AlayaDataClient
from packages.alayadata.models import ProcessDocumentRequest
from packages.retriever.bm25_utils import BM25SparseEncoder
from packages.vector_store.interfaces import VectorStore
from packages.vector_store.models import (
    CollectionExistsRequest,
    CollectionExistsResult,
    CreateCollectionRequest,
    CreateHybridCollectionRequest,
    DeleteRequest,
    DeleteResult,
    DropCollectionRequest,
    UpsertRequest,
    VectorRecord,
)


@dataclass
class InsertFilesResult:
    """Summary for insert_files."""

    collection: str
    files_processed: int
    chunks_written: int
    skipped_files: list[str] = field(default_factory=list)


class CollectionService:
    """Collection management and chunk ingestion via AlayaData."""

    def __init__(
        self,
        store: VectorStore,
        alaya_client: AlayaDataClient,
    ) -> None:
        self._store = store
        self._alaya_client = alaya_client

    def create_collection(
        self,
        collection_name: str,
        dimension: int,
        metric: str = "cosine",
    ) -> None:
        """Create collection if it does not exist."""
        exists = self._store.collection_exists(CollectionExistsRequest(name=collection_name))
        if not exists.exists:
            self._store.create_collection(
                CreateCollectionRequest(
                    name=collection_name,
                    dimension=dimension,
                    metric=metric.lower(),
                )
            )

    def create_hybrid_collection(
        self,
        collection_name: str,
        dimension: int,
        metric: str = "cosine",
        content_max_length: int = 65535,
    ) -> None:
        """创建支持混合检索的 collection（需 store 实现 create_hybrid_collection）。"""
        if not hasattr(self._store, "create_hybrid_collection"):
            raise NotImplementedError("store does not support create_hybrid_collection")
        exists = self._store.collection_exists(CollectionExistsRequest(name=collection_name))
        if not exists.exists:
            self._store.create_hybrid_collection(
                CreateHybridCollectionRequest(
                    name=collection_name,
                    dimension=dimension,
                    metric=metric.lower(),
                    content_max_length=content_max_length,
                )
            )

    def drop_collection(self, collection_name: str) -> None:
        """Drop a collection if it exists."""
        self._store.drop_collection(DropCollectionRequest(name=collection_name))

    def collection_exists(self, name: str) -> CollectionExistsResult:
        """Check if a collection exists."""
        return self._store.collection_exists(CollectionExistsRequest(name=name))

    def insert_chunk(
        self,
        collection_name: str,
        chunk_id: str,
        chunk: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Embed one chunk and upsert it."""
        emb = self._alaya_client.embed_query(chunk)
        record = VectorRecord(
            id=chunk_id,
            vector=emb.embedding_vector,
            metadata={**(metadata or {}), "text": chunk},
        )
        self._store.upsert(UpsertRequest(collection=collection_name, records=[record]))

    def insert_files(
        self,
        collection_name: str,
        file_paths: Sequence[Path | str],
        *,
        dimension: int | None = None,
        metric: str = "cosine",
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        enable_ocr: bool = True,
        parser_preference: Sequence[str] = ("builtin",),
        poll_interval: float = 1.0,
        max_wait: int | None = 300,
        batch_size: int = 64,
        extra_metadata: dict[str, Any] | None = None,
        enable_hybrid: bool = False,
        bm25_state_dir: str | Path | None = None,
    ) -> InsertFilesResult:
        """Process files through ETL and upsert chunks. enable_hybrid=True 时写入 content+sparse_vector 并保存 BM25 状态。"""
        result = InsertFilesResult(collection=collection_name, files_processed=0, chunks_written=0)
        inferred_dim: int | None = dimension
        bm25_dir = Path(bm25_state_dir or os.environ.get("BM25_STATE_DIR", "data/bm25_state"))

        if enable_hybrid:
            return self._insert_files_hybrid(
                collection_name=collection_name,
                file_paths=file_paths,
                result=result,
                inferred_dim=inferred_dim,
                metric=metric,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                enable_ocr=enable_ocr,
                parser_preference=parser_preference,
                poll_interval=poll_interval,
                max_wait=max_wait,
                batch_size=batch_size,
                extra_metadata=extra_metadata,
                bm25_dir=bm25_dir,
            )

        for raw_path in file_paths:
            path = Path(raw_path)
            if not path.is_file():
                result.skipped_files.append(str(path))
                continue

            try:
                job_result = self._alaya_client.process_document(
                    ProcessDocumentRequest(
                        file_path=path,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        enable_ocr=enable_ocr,
                        parser_preference=list(parser_preference),
                        poll_interval=poll_interval,
                        max_wait=max_wait,
                    )
                )
            except Exception:
                result.skipped_files.append(str(path))
                continue

            parse = job_result.parse or {}
            source_name = parse.get("source_name", path.name)
            chunks = [c for c in job_result.data if self._chunk_text(c).strip()]

            records: list[VectorRecord] = []
            for i, chunk in enumerate(chunks):
                text = self._chunk_text(chunk)
                vec = self._chunk_vector(chunk)
                if vec is None:
                    emb = self._alaya_client.embed_query(text)
                    vec = emb.embedding_vector
                if inferred_dim is None:
                    inferred_dim = len(vec)

                rid = self._record_id(collection_name, job_result.job_id, i, text)
                meta: dict[str, Any] = {
                    "job_id": job_result.job_id,
                    "doc_id": job_result.doc_id,
                    "dataset": job_result.dataset,
                    "source_name": source_name,
                    "chunk_index": i,
                    "slice_id": chunk.get("slice_id"),
                    "slice_type": chunk.get("slice_type", "text"),
                    "text": text,
                    **(extra_metadata or {}),
                }
                records.append(VectorRecord(id=rid, vector=vec, metadata=meta))

            if not records:
                result.files_processed += 1
                continue

            if inferred_dim is not None:
                self.create_collection(collection_name, dimension=inferred_dim, metric=metric)

            for i in range(0, len(records), batch_size):
                batch = records[i : i + batch_size]
                upsert_result = self._store.upsert(
                    UpsertRequest(collection=collection_name, records=batch)
                )
                result.chunks_written += upsert_result.written

            result.files_processed += 1

        if (
            hasattr(self._store, "ensure_index_and_load")
            and inferred_dim is not None
            and result.chunks_written > 0
        ):
            self._store.ensure_index_and_load(
                collection_name,
                dimension=inferred_dim,
                metric=metric,
                is_hybrid=False,
            )
        return result

    def _insert_files_hybrid(
        self,
        collection_name: str,
        file_paths: Sequence[Path | str],
        result: InsertFilesResult,
        inferred_dim: int | None,
        metric: str,
        chunk_size: int,
        chunk_overlap: int,
        enable_ocr: bool,
        parser_preference: Sequence[str],
        poll_interval: float,
        max_wait: int | None,
        batch_size: int,
        extra_metadata: dict[str, Any] | None,
        bm25_dir: Path,
    ) -> InsertFilesResult:
        """两阶段：先收集所有 chunk 文本，fit BM25，再统一 embed + 写入 hybrid collection。"""
        all_chunks: list[tuple[str, dict[str, Any], str]] = []  # (text, meta, rid)
        for raw_path in file_paths:
            path = Path(raw_path)
            if not path.is_file():
                result.skipped_files.append(str(path))
                continue
            try:
                job_result = self._alaya_client.process_document(
                    ProcessDocumentRequest(
                        file_path=path,
                        chunk_size=chunk_size,
                        chunk_overlap=chunk_overlap,
                        enable_ocr=enable_ocr,
                        parser_preference=list(parser_preference),
                        poll_interval=poll_interval,
                        max_wait=max_wait,
                    )
                )
            except Exception:
                result.skipped_files.append(str(path))
                continue
            parse = job_result.parse or {}
            source_name = parse.get("source_name", path.name)
            chunks = [c for c in job_result.data if self._chunk_text(c).strip()]
            for i, chunk in enumerate(chunks):
                text = self._chunk_text(chunk)
                rid = self._record_id(collection_name, job_result.job_id, i, text)
                meta: dict[str, Any] = {
                    "job_id": job_result.job_id,
                    "doc_id": job_result.doc_id,
                    "dataset": job_result.dataset,
                    "source_name": source_name,
                    "chunk_index": i,
                    "slice_id": chunk.get("slice_id"),
                    "slice_type": chunk.get("slice_type", "text"),
                    "text": text,
                    **(extra_metadata or {}),
                }
                all_chunks.append((text, meta, rid))
            result.files_processed += 1

        if not all_chunks:
            return result

        texts = [c[0] for c in all_chunks]
        bm25 = BM25SparseEncoder()
        bm25.fit(texts)

        if inferred_dim is None:
            emb0 = self._alaya_client.embed_query(texts[0])
            inferred_dim = len(emb0.embedding_vector)

        if hasattr(self._store, "create_hybrid_collection"):
            self.create_hybrid_collection(
                collection_name, dimension=inferred_dim, metric=metric, content_max_length=65535
            )

        for start in range(0, len(all_chunks), batch_size):
            batch_data = all_chunks[start : start + batch_size]
            records: list[VectorRecord] = []
            for text, meta, rid in batch_data:
                emb = self._alaya_client.embed_query(text)
                sparse = bm25.encode_doc(text)
                meta["content"] = text
                meta["sparse_vector"] = sparse
                records.append(VectorRecord(id=rid, vector=emb.embedding_vector, metadata=meta))
            upsert_result = self._store.upsert(UpsertRequest(collection=collection_name, records=records))
            result.chunks_written += upsert_result.written

        if hasattr(self._store, "ensure_index_and_load"):
            self._store.ensure_index_and_load(
                collection_name,
                dimension=inferred_dim,
                metric=metric,
                is_hybrid=True,
            )
        bm25.save(bm25_dir / f"{collection_name}.json")
        return result

    @staticmethod
    def _chunk_text(chunk: dict[str, Any]) -> str:
        for key in ("content_md", "text", "content"):
            if chunk.get(key):
                return str(chunk[key])
        return ""

    @staticmethod
    def _chunk_vector(chunk: dict[str, Any]) -> list[float] | None:
        vector = chunk.get("embedding_vector")
        if isinstance(vector, list) and vector and all(isinstance(x, (int, float)) for x in vector):
            return [float(x) for x in vector]
        return None

    @staticmethod
    def _record_id(collection: str, job_id: str, chunk_index: int, text: str) -> str:
        token = f"{collection}|{job_id}|{chunk_index}|{text[:64]}"
        return f"{collection}:{hashlib.sha1(token.encode('utf-8')).hexdigest()}"

    def delete_chunks(
        self,
        collection_name: str,
        chunk_ids: list[str],
    ) -> DeleteResult:
        """Delete chunks by id list."""
        return self._store.delete(DeleteRequest(collection=collection_name, ids=chunk_ids))