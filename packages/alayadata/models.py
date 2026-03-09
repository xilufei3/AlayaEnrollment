from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence, TypedDict


# ---------- embedding ----------


@dataclass(slots=True)
class EmbeddingRequest:
    query: str


@dataclass(slots=True)
class EmbeddingResult:
    embedding_vector: list[float]
    embedding_model: str
    dim: int


# ---------- upload ----------
@dataclass(slots=True)
class UploadResult:
    upload_ref: str


# ---------- create job ----------


@dataclass(slots=True)
class CreateJobRequest:
    upload_ref: str
    doc_id: int | None = None
    dataset: str | None = None
    chunk_size: int = 800
    chunk_overlap: int = 120
    enable_ocr: bool = True
    parser_preference: Sequence[str] = field(default_factory=lambda: ["builtin"])


@dataclass(slots=True)
class CreateJobResult:
    job_id: str


# ---------- job status ----------


@dataclass(slots=True)
class JobProgress:
    percent: int = 0


@dataclass(slots=True)
class JobStatusResult:
    job_id: str
    status: str
    stage: str | None = None
    progress: JobProgress = field(default_factory=JobProgress)
    raw: Mapping[str, Any] = field(default_factory=dict)


# ---------- job result ----------


class SliceChunk(TypedDict, total=False):
    """ETL 结果中 data[] 单条分片的 API 形状（仅作文档/类型提示，实际仍为 dict）。"""
    slice_id: int
    slice_type: str
    chunk_index: int
    content_md: str
    embedding_vector: list[float]
    metadata: Mapping[str, Any]


@dataclass(slots=True)
class JobResult:
    job_id: str = ""
    doc_id: int | None = None
    dataset: str | None = None
    status: str | None = None
    data: list[dict[str, Any]] = field(default_factory=list)
    parse: Mapping[str, Any] = field(default_factory=dict)
    assets: list[dict[str, Any]] = field(default_factory=list)
    fulltext: str = ""
    raw: Mapping[str, Any] = field(default_factory=dict)


# ---------- convenience ----------


@dataclass(slots=True)
class ProcessDocumentRequest:
    file_path: Path
    doc_id: int | None = None
    dataset: str | None = None
    chunk_size: int = 800
    chunk_overlap: int = 120
    enable_ocr: bool = True
    parser_preference: Sequence[str] = field(default_factory=lambda: ["builtin"])
    poll_interval: float = 1.0
    max_wait: int | None = None