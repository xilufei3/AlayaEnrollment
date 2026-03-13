"""
向量导入相关配置：子目录与 collection 映射、Milvus/ETL 连接等。
可从 .env 覆盖，或在此文件内修改默认值。
"""
from __future__ import annotations

import os
from pathlib import Path

# 仓库根目录、data 目录
REPO_ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = REPO_ROOT / "data"

# 所有子目录统一写入的 collection 名称
COLLECTION_NAME: str = "sustc_enrollment"

# 支持的子目录列表（用于校验）
SUPPORTED_DIRS: list[str] = [
    "admission_policy",
    "majors_and_training",
    "school_overview",
    "sustech_rag_markdown_clean",
]

# .env 路径
ENV_FILE = REPO_ROOT / ".env"


def load_dotenv(env_file: Path | None = None) -> None:
    path = env_file or ENV_FILE
    if not path.is_file():
        return
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k, v = k.strip(), v.strip().strip("'\"").strip()
            if k and k not in os.environ:
                os.environ[k] = v


def get_milvus_uri() -> str:
    return os.getenv("MILVUS_URI", "http://localhost:19530")


def get_milvus_token() -> str:
    return os.getenv("MILVUS_TOKEN", "").strip()


def get_etl_url() -> str:
    return os.getenv("ETL_SERVER_URL", os.getenv("AlayaData_URL", "http://100.64.0.30:6000")).strip().rstrip("/")


def get_collection_for_dir(dir_name: str) -> str:
    """返回统一 collection 名称。"""
    return COLLECTION_NAME


# ETL/分片默认（可按需在 .env 或此处改）
DEFAULT_CHUNK_SIZE = 800
DEFAULT_CHUNK_OVERLAP = 120
DEFAULT_BATCH_SIZE = 64
DEFAULT_ETL_TIMEOUT = 300
