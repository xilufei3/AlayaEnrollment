from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    CreateCollectionRequest,
    DropCollectionRequest,
    CollectionExistsRequest,
    CollectionExistsResult,
    CollectionInfo,
    UpsertRequest,
    UpsertResult,
    DeleteRequest,
    DeleteResult,
    SearchRequest,
    SearchResult,
)


class VectorStore(ABC):
    """Vector storage abstraction for RAG systems."""

    # ---------- collection management ----------

    @abstractmethod
    def create_collection(self, req: CreateCollectionRequest) -> CollectionInfo:
        raise NotImplementedError

    @abstractmethod
    def drop_collection(self, req: DropCollectionRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    def collection_exists(self, req: CollectionExistsRequest) -> CollectionExistsResult:
        raise NotImplementedError

    # ---------- data operations ----------

    @abstractmethod
    def upsert(self, req: UpsertRequest) -> UpsertResult:
        raise NotImplementedError

    @abstractmethod
    def delete(self, req: DeleteRequest) -> DeleteResult:
        raise NotImplementedError

    @abstractmethod
    def search(self, req: SearchRequest) -> SearchResult:
        raise NotImplementedError