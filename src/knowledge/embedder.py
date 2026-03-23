from __future__ import annotations

import logging
import threading
from pathlib import Path
from typing import Protocol, Sequence

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config.settings import REPO_ROOT, config
from .alaya_embedder import AlayaEmbedder, EmbeddingResult

logger = logging.getLogger(__name__)


class Embedder(Protocol):
    def embed_query(self, query: str) -> EmbeddingResult:
        ...

    def embed(self, query: str) -> list[float]:
        ...

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        ...


class CustomEmbeddingClient:
    _instance: "CustomEmbeddingClient | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "CustomEmbeddingClient":
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
        self._url = f"{config.embedding.custom_api_base.rstrip('/')}/v1/embeddings"
        self._model = config.embedding.custom_model
        self._timeout = config.embedding.custom_timeout
        self._batch_size = max(1, config.embedding.custom_batch_size)
        self._api_key = self._load_api_key()

        session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("http://", HTTPAdapter(max_retries=retry))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session = session

        logger.info(
            "CustomEmbeddingClient initialized: %s model=%s batch_size=%d",
            self._url,
            self._model,
            self._batch_size,
        )

    def _load_api_key(self) -> str:
        if config.embedding.custom_api_key:
            return config.embedding.custom_api_key

        api_key_file = config.embedding.custom_api_key_file
        if not api_key_file:
            return ""

        path = Path(api_key_file)
        if not path.is_absolute():
            path = REPO_ROOT / path
        if not path.exists():
            return ""

        return path.read_text(encoding="utf-8").strip()

    def _headers(self) -> dict[str, str]:
        headers = {"Content-Type": "application/json"}
        if self._api_key:
            headers["Authorization"] = f"Bearer {self._api_key}"
        return headers

    @staticmethod
    def _validate_vector(vector: object, *, field_name: str = "embedding") -> list[float]:
        if not isinstance(vector, list) or not vector or not all(isinstance(x, (int, float)) for x in vector):
            raise ValueError(f"invalid {field_name} in response")
        return [float(x) for x in vector]

    @staticmethod
    def _validate_dim(vector: list[float]) -> None:
        expected = config.milvus.embed_dim
        actual = len(vector)
        if actual != expected:
            raise ValueError(
                "embedding dim mismatch: "
                f"len(vector)={actual} != EMBED_DIM={expected}. "
                "Please update EMBED_DIM and recreate the Milvus collection if needed."
            )

    def embed_texts(self, texts: Sequence[str]) -> list[list[float]]:
        normalized = [text for text in texts if isinstance(text, str) and text.strip()]
        if not normalized:
            return []

        embeddings: list[list[float]] = []
        for start in range(0, len(normalized), self._batch_size):
            batch = normalized[start : start + self._batch_size]
            resp = self._session.post(
                self._url,
                headers=self._headers(),
                json={
                    "model": self._model,
                    "input": batch,
                },
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            items = data.get("data", [])
            if not isinstance(items, list):
                raise ValueError("invalid data in custom embedding response")

            vectors_by_index: dict[int, list[float]] = {}
            for item in items:
                if not isinstance(item, dict):
                    raise ValueError("invalid item in custom embedding response")
                index = item.get("index")
                if not isinstance(index, int):
                    raise ValueError("missing index in custom embedding response")
                vectors_by_index[index] = self._validate_vector(item.get("embedding"))

            if len(vectors_by_index) != len(batch):
                raise ValueError(
                    "custom embedding response count mismatch: "
                    f"expected={len(batch)} actual={len(vectors_by_index)}"
                )

            ordered_batch: list[list[float]] = []
            for index in range(len(batch)):
                if index not in vectors_by_index:
                    raise ValueError(f"missing embedding for input index={index}")
                vector = vectors_by_index[index]
                self._validate_dim(vector)
                ordered_batch.append(vector)
            embeddings.extend(ordered_batch)

        return embeddings

    def embed_query(self, query: str) -> EmbeddingResult:
        vectors = self.embed_texts([query])
        if not vectors:
            raise ValueError("empty embedding result")
        vector = vectors[0]
        return EmbeddingResult(
            embedding_vector=vector,
            embedding_model=self._model,
            dim=len(vector),
        )

    def embed(self, query: str) -> list[float]:
        return self.embed_query(query).embedding_vector


def get_embedder() -> Embedder:
    if config.embedding.use_custom:
        return CustomEmbeddingClient()
    return AlayaEmbedder()
