from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Mapping, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config.settings import config

logger = logging.getLogger(__name__)


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
class JobProgress:
    percent: int = 0


@dataclass(slots=True)
class JobStatusResult:
    job_id: str
    status: str
    stage: str | None = None
    progress: JobProgress = field(default_factory=JobProgress)
    raw: Mapping[str, Any] = field(default_factory=dict)


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


class AlayaETL:
    def __init__(self) -> None:
        self._server = config.alaya.server_url.rstrip("/")
        self._timeout = config.alaya.timeout

        session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("http://", HTTPAdapter(max_retries=retry))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session = session

    def process_document(self, req: ProcessDocumentRequest) -> JobResult:
        upload_ref = self._upload(req.file_path)
        job_id = self._create_job(
            CreateJobRequest(
                upload_ref=upload_ref,
                doc_id=req.doc_id,
                dataset=req.dataset,
                chunk_size=req.chunk_size,
                chunk_overlap=req.chunk_overlap,
                enable_ocr=req.enable_ocr,
                parser_preference=req.parser_preference,
            )
        )
        return self._wait_job(
            job_id=job_id,
            poll_interval=req.poll_interval,
            max_wait=req.max_wait,
        )

    def process_file(
        self,
        file_path: Path,
        chunk_size: int = 800,
        chunk_overlap: int = 120,
        enable_ocr: bool = True,
        *,
        doc_id: int | None = None,
        dataset: str | None = None,
        parser_preference: Sequence[str] = ("builtin",),
        poll_interval: float = 1.0,
        max_wait: int | None = None,
    ) -> list[dict[str, Any]]:
        result = self.process_document(
            ProcessDocumentRequest(
                file_path=file_path,
                doc_id=doc_id,
                dataset=dataset,
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                enable_ocr=enable_ocr,
                parser_preference=parser_preference,
                poll_interval=poll_interval,
                max_wait=max_wait,
            )
        )
        return self._parse_chunks(result)

    def _upload(self, file_path: Path) -> str:
        logger.info("Uploading file: %s (%d bytes)", file_path.name, file_path.stat().st_size)
        with open(file_path, "rb") as handle:
            resp = self._session.post(
                f"{self._server}/v1/etl/uploads",
                files={"file": (file_path.name, handle, "application/octet-stream")},
                timeout=self._timeout,
            )
        resp.raise_for_status()
        upload_ref = resp.json()["upload_ref"]
        logger.info("Upload completed: upload_ref=%s", upload_ref)
        return upload_ref

    def _create_job(self, req: CreateJobRequest) -> str:
        payload: dict[str, Any] = {
            "input": {
                "type": "upload_ref",
                "upload_ref": req.upload_ref,
            },
            "config_snapshot": {
                "chunk_size": req.chunk_size,
                "chunk_overlap": req.chunk_overlap,
                "enable_ocr": req.enable_ocr,
                "parser_preference": list(req.parser_preference),
            },
        }

        doc_meta: dict[str, Any] = {}
        if req.doc_id is not None:
            doc_meta["doc_id"] = req.doc_id
        if req.dataset is not None:
            doc_meta["dataset"] = req.dataset
        if doc_meta:
            payload["doc_meta"] = doc_meta

        resp = self._session.post(
            f"{self._server}/v1/etl/jobs",
            json=payload,
            timeout=self._timeout,
        )
        resp.raise_for_status()
        job_id = resp.json()["job_id"]
        logger.info("ETL job created: job_id=%s", job_id)
        return job_id

    def _get_job_status(self, job_id: str) -> JobStatusResult:
        resp = self._session.get(
            f"{self._server}/v1/etl/jobs/{job_id}",
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        progress_data = data.get("progress", {})
        percent = progress_data.get("percent", 0)
        if not isinstance(percent, int):
            percent = 0

        return JobStatusResult(
            job_id=job_id,
            status=str(data.get("status", "")),
            stage=data.get("stage") if isinstance(data.get("stage"), str) else None,
            progress=JobProgress(percent=percent),
            raw=data,
        )

    def _get_job_result(self, job_id: str) -> JobResult:
        resp = self._session.get(
            f"{self._server}/v1/etl/jobs/{job_id}/result",
            timeout=self._timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        result_data = data.get("data", [])
        parse = data.get("parse", {})
        assets = data.get("assets", [])
        fulltext = data.get("fulltext", "")
        status = data.get("status")
        job_id_out = data.get("job_id", "")
        doc_id_raw = data.get("doc_id")
        dataset_out = data.get("dataset")

        if not isinstance(result_data, list):
            result_data = []
        if not isinstance(parse, dict):
            parse = {}
        if not isinstance(assets, list):
            assets = []
        if not isinstance(fulltext, str):
            fulltext = ""
        if status is not None and not isinstance(status, str):
            status = None
        if not isinstance(job_id_out, str):
            job_id_out = str(job_id_out) if job_id_out is not None else ""
        if doc_id_raw is not None:
            try:
                doc_id_out: int | None = int(doc_id_raw)
            except (TypeError, ValueError):
                doc_id_out = None
        else:
            doc_id_out = None
        if dataset_out is not None and not isinstance(dataset_out, str):
            dataset_out = str(dataset_out)

        return JobResult(
            job_id=job_id_out,
            doc_id=doc_id_out,
            dataset=dataset_out,
            status=status,
            data=result_data,
            parse=parse,
            assets=assets,
            fulltext=fulltext,
            raw=data,
        )

    def _wait_job(
        self,
        job_id: str,
        poll_interval: float = 1.0,
        max_wait: int | None = None,
    ) -> JobResult:
        start = time.time()
        last_status = None

        while True:
            status_info = self._get_job_status(job_id)
            status = status_info.status

            if status != last_status:
                logger.info("Job status: %s", status)
                last_status = status

            if status in {"succeeded", "partial_succeeded"}:
                time.sleep(0.5)
                return self._get_job_result(job_id)

            if status == "failed":
                errors = status_info.raw.get("errors", [])
                message = "unknown job error"
                if isinstance(errors, list) and errors:
                    first = errors[0]
                    if isinstance(first, dict):
                        message = str(first.get("message", message))
                raise RuntimeError(f"ETL job failed: {message}")

            if status == "canceled":
                raise RuntimeError("ETL job canceled")

            if max_wait is not None and (time.time() - start) > max_wait:
                raise TimeoutError(f"ETL job timeout after {max_wait}s")

            time.sleep(poll_interval)

    @staticmethod
    def _parse_chunks(result: JobResult | dict[str, Any]) -> list[dict[str, Any]]:
        if isinstance(result, JobResult):
            rows = result.data
        else:
            rows = result.get("data", [])

        chunks: list[dict[str, Any]] = []
        for row in rows:
            if not isinstance(row, dict):
                continue

            content = row.get("content_md", "")
            vector = row.get("embedding_vector")
            if vector is None:
                vector = row.get("embedding")

            if (
                not content
                or not isinstance(vector, list)
                or not vector
                or not all(isinstance(x, (int, float)) for x in vector)
            ):
                logger.warning("Skipping invalid chunk: content or embedding_vector is empty")
                continue

            normalized_vector = [float(x) for x in vector]
            chunk = {
                "content_md": content,
                "embedding_vector": normalized_vector,
                "metadata": {
                    key: value
                    for key, value in row.items()
                    if key not in ("content_md", "embedding_vector", "embedding")
                },
            }
            chunk["embedding"] = normalized_vector
            chunks.append(chunk)

        logger.info("Parsed %d valid chunks", len(chunks))
        return chunks
