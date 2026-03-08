from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .errors import StoreUnavailable
from .milvus_store import PyMilvusStore


def _read_env_file(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    if not path.exists():
        return values

    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key:
            values[key] = value
    return values


@dataclass(slots=True)
class MilvusConfig:
    uri: str = "http://localhost:19530"
    token: str | None = None
    db_name: str | None = None

    collection_prefix: str = "adm_"
    vector_field: str = "embedding"
    id_field: str = "id"

    index_type: str = "HNSW"
    metric_type: str = "COSINE"
    hnsw_m: int = 16
    hnsw_ef_construction: int = 200

    @classmethod
    def from_env(cls, env_file: str | Path | None = None) -> "MilvusConfig":
        if env_file is None:
            env_file = Path(__file__).resolve().parent / ".env"
        else:
            env_file = Path(env_file)

        file_vars = _read_env_file(env_file)

        def pick(key: str, default: str | None = None) -> str | None:
            if key in os.environ:
                return os.environ[key]
            return file_vars.get(key, default)

        return cls(
            uri=pick("MILVUS_URI", "http://localhost:19530") or "http://localhost:19530",
            token=pick("MILVUS_TOKEN") or None,
            db_name=pick("MILVUS_DB_NAME") or pick("MILVUS_DB") or None,
            collection_prefix=pick("MILVUS_COLLECTION_PREFIX", "adm_") or "adm_",
            vector_field=pick("MILVUS_VECTOR_FIELD", "embedding") or "embedding",
            id_field=pick("MILVUS_ID_FIELD", "id") or "id",
            index_type=(pick("MILVUS_INDEX_TYPE", "HNSW") or "HNSW").upper(),
            metric_type=(pick("MILVUS_METRIC_TYPE", "COSINE") or "COSINE").upper(),
            hnsw_m=int(pick("MILVUS_HNSW_M", "16") or "16"),
            hnsw_ef_construction=int(
                pick("MILVUS_HNSW_EF_CONSTRUCTION", "200") or "200"
            ),
        )

    def build_index_params(self) -> dict[str, Any]:
        params: dict[str, Any] = {
            "index_type": self.index_type,
            "metric_type": self.metric_type,
        }
        if self.index_type == "HNSW":
            params["params"] = {
                "M": self.hnsw_m,
                "efConstruction": self.hnsw_ef_construction,
            }
        return params


def create_milvus_client_from_env(env_file: str | Path | None = None):
    cfg = MilvusConfig.from_env(env_file)
    try:
        from pymilvus import MilvusClient  # type: ignore
    except ImportError as exc:
        raise StoreUnavailable("pymilvus is not installed") from exc

    kwargs: dict[str, Any] = {"uri": cfg.uri}
    if cfg.token:
        kwargs["token"] = cfg.token
    if cfg.db_name:
        kwargs["db_name"] = cfg.db_name
    return MilvusClient(**kwargs)


def create_store_from_env(env_file: str | Path | None = None) -> PyMilvusStore:
    cfg = MilvusConfig.from_env(env_file)
    client = create_milvus_client_from_env(env_file=env_file)
    return PyMilvusStore(
        client=client,
        collection_prefix=cfg.collection_prefix,
        vector_field=cfg.vector_field,
        id_field=cfg.id_field,
        index_params=cfg.build_index_params(),
    )
