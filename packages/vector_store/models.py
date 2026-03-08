from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Mapping, Sequence


MetricType = Literal["COSINE", "IP", "L2"]


@dataclass(slots=True)
class CreateIndexRequest:
    index: str
    dimension: int
    metric: MetricType = "COSINE"


@dataclass(slots=True)
class IndexMeta:
    index: str
    collection: str
    dimension: int
    metric: MetricType
    status: str = "ready"


@dataclass(slots=True)
class VectorItem:
    id: str
    vector: Sequence[float]
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class UpsertRequest:
    index: str
    items: Sequence[VectorItem]


@dataclass(slots=True)
class UpsertResult:
    upserted: int
    failed: int = 0


@dataclass(slots=True)
class SearchRequest:
    index: str
    query_vector: Sequence[float]
    top_k: int = 8
    filter_expr: str | None = None


@dataclass(slots=True)
class SearchHit:
    id: str
    score: float
    payload: Mapping[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class SearchResult:
    hits: list[SearchHit]


@dataclass(slots=True)
class DeleteRequest:
    index: str
    ids: Sequence[str] = field(default_factory=list)
    filter_expr: str | None = None


@dataclass(slots=True)
class IndexStats:
    index: str
    collection: str
    total_entities: int
    indexed_rows: int
    loaded: bool

