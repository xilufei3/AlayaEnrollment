from __future__ import annotations

import logging
import threading
from dataclasses import dataclass

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

from ..config.settings import config

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class EmbeddingResult:
    embedding_vector: list[float]
    embedding_model: str
    dim: int


class AlayaEmbedder:
    _instance: "AlayaEmbedder | None" = None
    _lock = threading.Lock()

    def __new__(cls) -> "AlayaEmbedder":
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
        self._url = f"{config.alaya.server_url.rstrip('/')}/v1/etl/embedding"

        session = requests.Session()
        retry = Retry(total=3, backoff_factor=1, status_forcelist=[429, 500, 502, 503, 504])
        session.mount("http://", HTTPAdapter(max_retries=retry))
        session.mount("https://", HTTPAdapter(max_retries=retry))
        self._session = session
        logger.info("AlayaEmbedder initialized: %s", self._url)

    def embed_query(self, query: str) -> EmbeddingResult:
        resp = self._session.post(
            self._url,
            json={"query": query},
            timeout=config.alaya.timeout,
        )
        resp.raise_for_status()
        data = resp.json()

        vector = data.get("embedding_vector")
        model = data.get("embedding_model")
        dim = data.get("dim")

        if not isinstance(vector, list) or not all(isinstance(x, (int, float)) for x in vector):
            raise ValueError("invalid embedding_vector in response")
        if not isinstance(model, str):
            raise ValueError("invalid embedding_model in response")
        if not isinstance(dim, int):
            raise ValueError("invalid dim in response")
        if len(vector) != dim:
            raise ValueError(
                f"embedding dim mismatch: len(vector)={len(vector)} != dim={dim}"
            )

        return EmbeddingResult(
            embedding_vector=[float(x) for x in vector],
            embedding_model=model,
            dim=dim,
        )

    def embed(self, query: str) -> list[float]:
        return self.embed_query(query).embedding_vector
