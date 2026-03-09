from __future__ import annotations

import time
from pathlib import Path
from typing import Any

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from .models import (
    CreateJobRequest,
    CreateJobResult,
    EmbeddingResult,
    JobProgress,
    JobResult,
    JobStatusResult,
    ProcessDocumentRequest,
    UploadResult,
)


class AlayaDataError(Exception):
    """Base error for AlayaData client."""


class AlayaDataHTTPError(AlayaDataError):
    """HTTP-level error."""


class AlayaDataJobError(AlayaDataError):
    """ETL job failed or ended unexpectedly."""


class AlayaDataClient:
    """Client for AlayaData embedding + ETL service."""

    def __init__(
        self,
        base_url: str,
        timeout: float = 300,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout
        self._session = self._create_session()

    def _create_session(self) -> requests.Session:
        session = requests.Session()
        retry_strategy = Retry(
            total=3,
            backoff_factor=1,
            status_forcelist=[429, 500, 502, 503, 504],
        )
        adapter = HTTPAdapter(max_retries=retry_strategy)
        session.mount("http://", adapter)
        session.mount("https://", adapter)
        return session

    # ---------- embedding ----------

    def embed_query(self, query: str) -> EmbeddingResult:
        data = self._post_json(
            "/v1/etl/embedding",
            payload={"query": query},
        )

        vector = data.get("embedding_vector")
        model = data.get("embedding_model")
        dim = data.get("dim")

        if not isinstance(vector, list) or not all(isinstance(x, (int, float)) for x in vector):
            raise AlayaDataError("invalid embedding_vector in response")

        if not isinstance(model, str):
            raise AlayaDataError("invalid embedding_model in response")

        if not isinstance(dim, int):
            raise AlayaDataError("invalid dim in response")

        if len(vector) != dim:
            raise AlayaDataError(
                f"embedding dim mismatch: len(vector)={len(vector)} != dim={dim}"
            )

        return EmbeddingResult(
            embedding_vector=[float(x) for x in vector],
            embedding_model=model,
            dim=dim,
        )

    # ---------- upload ----------

    def upload_file(self, file_path: Path) -> UploadResult:
        if not file_path.exists():
            raise FileNotFoundError(f"file not found: {file_path}")
        if not file_path.is_file():
            raise ValueError(f"path is not a file: {file_path}")

        url = f"{self._base_url}/v1/etl/uploads"
        try:
            with open(file_path, "rb") as f:
                files = {"file": (file_path.name, f, "application/octet-stream")}
                resp = self._session.post(url, files=files, timeout=self._timeout)
                resp.raise_for_status()
                data = resp.json()
        except requests.RequestException as exc:
            raise AlayaDataHTTPError(f"failed to upload file: {exc}") from exc
        except ValueError as exc:
            raise AlayaDataError("upload response is not valid JSON") from exc

        upload_ref = data.get("upload_ref")
        if not isinstance(upload_ref, str) or not upload_ref:
            raise AlayaDataError("invalid upload_ref in response")

        return UploadResult(upload_ref=upload_ref)

    # ---------- ETL job ----------

    def create_job(self, req: CreateJobRequest) -> CreateJobResult:
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

        data = self._post_json("/v1/etl/jobs", payload=payload)

        job_id = data.get("job_id")
        if not isinstance(job_id, str) or not job_id:
            raise AlayaDataError("invalid job_id in response")

        return CreateJobResult(job_id=job_id)

    def get_job_status(self, job_id: str) -> JobStatusResult:
        data = self._get_json(f"/v1/etl/jobs/{job_id}")

        status = data.get("status")
        stage = data.get("stage")
        progress_data = data.get("progress", {})

        if not isinstance(status, str):
            raise AlayaDataError("invalid status in job status response")

        percent = progress_data.get("percent", 0)
        if not isinstance(percent, int):
            percent = 0

        return JobStatusResult(
            job_id=job_id,
            status=status,
            stage=stage if isinstance(stage, str) else None,
            progress=JobProgress(percent=percent),
            raw=data,
        )

    def get_job_result(self, job_id: str) -> JobResult:
        data = self._get_json(f"/v1/etl/jobs/{job_id}/result")

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

    def wait_for_job(
        self,
        job_id: str,
        poll_interval: float = 1.0,
        max_wait: int | None = None,
    ) -> JobResult:
        start = time.time()

        while True:
            status_info = self.get_job_status(job_id)
            status = status_info.status

            if status in {"succeeded", "partial_succeeded"}:
                # 给结果写入留一点余量
                time.sleep(0.5)
                return self.get_job_result(job_id)

            if status == "failed":
                errors = status_info.raw.get("errors", [])
                message = "unknown job error"
                if isinstance(errors, list) and errors:
                    first = errors[0]
                    if isinstance(first, dict):
                        message = str(first.get("message", message))
                raise AlayaDataJobError(f"job failed: {message}")

            if status == "canceled":
                raise AlayaDataJobError("job canceled")

            if max_wait is not None and (time.time() - start) > max_wait:
                raise TimeoutError(f"job timeout after {max_wait}s")

            time.sleep(poll_interval)

    def process_document(self, req: ProcessDocumentRequest) -> JobResult:
        upload = self.upload_file(req.file_path)

        job = self.create_job(
            CreateJobRequest(
                upload_ref=upload.upload_ref,
                doc_id=req.doc_id,
                dataset=req.dataset,
                chunk_size=req.chunk_size,
                chunk_overlap=req.chunk_overlap,
                enable_ocr=req.enable_ocr,
                parser_preference=req.parser_preference,
            )
        )

        return self.wait_for_job(
            job_id=job.job_id,
            poll_interval=req.poll_interval,
            max_wait=req.max_wait,
        )

    # ---------- lifecycle ----------

    def close(self) -> None:
        self._session.close()

    # ---------- internals ----------

    def _post_json(self, path: str, payload: dict[str, Any]) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = self._session.post(url, json=payload, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise AlayaDataHTTPError(f"POST {path} failed: {exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise AlayaDataError(f"POST {path} returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise AlayaDataError(f"POST {path} returned non-object JSON")

        return data

    def _get_json(self, path: str) -> dict[str, Any]:
        url = f"{self._base_url}{path}"
        try:
            resp = self._session.get(url, timeout=self._timeout)
            resp.raise_for_status()
        except requests.RequestException as exc:
            raise AlayaDataHTTPError(f"GET {path} failed: {exc}") from exc

        try:
            data = resp.json()
        except ValueError as exc:
            raise AlayaDataError(f"GET {path} returned invalid JSON") from exc

        if not isinstance(data, dict):
            raise AlayaDataError(f"GET {path} returned non-object JSON")

        return data