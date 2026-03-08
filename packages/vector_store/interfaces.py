from __future__ import annotations

from abc import ABC, abstractmethod

from .models import (
    CreateIndexRequest,
    DeleteRequest,
    IndexMeta,
    IndexStats,
    SearchRequest,
    SearchResult,
    UpsertRequest,
    UpsertResult,
)


class VectorStore(ABC):
    """Milvus-oriented vector storage contract."""

    @abstractmethod
    def create_index(self, req: CreateIndexRequest) -> IndexMeta:
        raise NotImplementedError

    @abstractmethod
    def upsert(self, req: UpsertRequest) -> UpsertResult:
        raise NotImplementedError

    @abstractmethod
    def search(self, req: SearchRequest) -> SearchResult:
        raise NotImplementedError

    @abstractmethod
    def delete(self, req: DeleteRequest) -> None:
        raise NotImplementedError

    @abstractmethod
    def stats(self, index: str) -> IndexStats:
        raise NotImplementedError

    @abstractmethod
    def drop_index(self, index: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def close(self) -> None:
        raise NotImplementedError

