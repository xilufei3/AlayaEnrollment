from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence


# ---------- collection ----------


@dataclass(slots=True)
class CollectionInfo:
    name: str
    dimension: int
    metric: str = "cosine"


@dataclass(slots=True)
class CreateCollectionRequest:
    name: str
    dimension: int
    metric: str = "cosine"


@dataclass(slots=True)
class DropCollectionRequest:
    name: str


@dataclass(slots=True)
class CollectionExistsRequest:
    name: str


@dataclass(slots=True)
class CollectionExistsResult:
    exists: bool


# ---------- vector record ----------


@dataclass(slots=True)
class VectorRecord:
    id: str
    vector: Sequence[float]
    metadata: Mapping[str, Any] = field(default_factory=dict)


# ---------- upsert ----------


@dataclass(slots=True)
class UpsertRequest:
    collection: str
    records: Sequence[VectorRecord]


@dataclass(slots=True)
class UpsertResult:
    written: int


# ---------- delete ----------


@dataclass(slots=True)
class DeleteRequest:
    collection: str
    ids: Sequence[str]


@dataclass(slots=True)
class DeleteResult:
    deleted: int


# ---------- search ----------


@dataclass(slots=True)
class SearchRequest:
    collection: str
    query_vector: Sequence[float]
    top_k: int = 5


@dataclass(slots=True)
class SearchHit:
    id: str
    score: float
    metadata: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    hits: list[SearchHit]