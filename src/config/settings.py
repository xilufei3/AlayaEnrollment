from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SRC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SRC_ROOT.parent


# 对话历史：提取最近 k 轮（每轮=1 条用户+1 条助手），供后续节点使用
HISTORY_LAST_K_TURNS: int = 4


@dataclass
class LLMConfig:
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", ""))
    base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1"))
    model: str = "deepseek-chat"
    temperature: float = 0.0
    max_tokens: int = 1024


@dataclass
class MilvusConfig:
    uri: str = field(default_factory=lambda: os.getenv("MILVUS_URI", "http://localhost:19530"))
    collection_name: str = field(default_factory=lambda: os.getenv("MILVUS_COLLECTION", "admissions_knowledge"))
    embed_dim: int = field(default_factory=lambda: int(os.getenv("EMBED_DIM", "768")))
    top_k: int = 8
    score_threshold: float = 0.35

@dataclass
class AlayaConfig:
    server_url: str = field(default_factory=lambda: os.getenv("AlayaData_URL", "http://100.64.0.30:6000"))
    timeout: int = 300

@dataclass
class RerankConfig:
    model_id: str = "rerank"
    top_n: int = field(default_factory=lambda: int(os.getenv("RERANK_TOP_N", "5")))


@dataclass
class DBConfig:
    admissions_db_path: str = str(REPO_ROOT / "data" / "db" / "admissions.db")
    table_registry_path: str = str(SRC_ROOT / "config" / "table_registry.yaml")
    system_db_path: str = str(REPO_ROOT / "data" / "db" / "system.db")


@dataclass
class AgentConfig:
    llm: LLMConfig | None = None
    milvus: MilvusConfig | None = None
    alaya: AlayaConfig | None = None
    rerank: RerankConfig | None = None
    db: DBConfig | None = None

    def __post_init__(self) -> None:
        self.llm = self.llm or LLMConfig()
        self.milvus = self.milvus or MilvusConfig()
        self.alaya = self.alaya or AlayaConfig()
        self.rerank = self.rerank or RerankConfig()
        self.db = self.db or DBConfig()


config = AgentConfig()

__all__ = [
    "AgentConfig",
    "AlayaConfig",
    "DBConfig",
    "HISTORY_LAST_K_TURNS",
    "LLMConfig",
    "MilvusConfig",
    "REPO_ROOT",
    "RerankConfig",
    "SRC_ROOT",
    "config",
]
