from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv
import yaml

load_dotenv()

SRC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SRC_ROOT.parent
INGEST_CONFIG_PATH = SRC_ROOT / "config" / "ingest.yaml"


def _load_yaml_config(path: Path) -> dict:
    if not path.exists():
        return {}
    with open(path, "r", encoding="utf-8") as handle:
        data = yaml.safe_load(handle) or {}
    return data if isinstance(data, dict) else {}


def _coerce_int(value: object, default: int, *, minimum: int | None = None) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and parsed < minimum:
        return default
    return parsed


def _coerce_float(value: object, default: float, *, minimum: float | None = None) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    if minimum is not None and parsed < minimum:
        return default
    return parsed


def _coerce_bool(value: object, default: bool) -> bool:
    return value if isinstance(value, bool) else default


def _coerce_str(value: object, default: str) -> str:
    if isinstance(value, str) and value.strip():
        return value.strip()
    return default


def _coerce_str_tuple(value: object, default: tuple[str, ...]) -> tuple[str, ...]:
    if not isinstance(value, list):
        return default
    items = tuple(str(item).strip() for item in value if str(item).strip())
    return items or default


class IntentType(str, Enum):
    SCHOOL_OVERVIEW = "school_overview"
    ADMISSION_POLICY = "admission_policy"
    MAJOR_AND_TRAINING = "major_and_training"
    CAREER_AND_DEVELOPMENT = "career_and_development"
    CAMPUS_LIFE = "campus_life"
    OUT_OF_SCOPE = "out_of_scope"
    OTHER = "other"


INTENT_DESCRIPTIONS: dict[str, str] = {
    IntentType.SCHOOL_OVERVIEW.value: (
        "学校概况：学校定位、办学特色（书院制、导师制、国际化、小班教学、本科生科研）、"
        "校园与城市（深圳优势、校园环境）、师资概况（院士、海归比例、师生比）、科研实力。"
    ),
    IntentType.ADMISSION_POLICY.value: (
        "招生政策：综合评价631模式详细说明、各省报名条件与资格、招生计划与人数、"
        "报名/考核/录取时间节点、能力测试与面试方式、录取规则与历年分数线位次、各省差异政策。"
    ),
    IntentType.MAJOR_AND_TRAINING.value: (
        "专业与培养：全部本科专业目录与院系归属、各专业培养目标与核心课程、"
        "实验实践环节、大一大二通识培养与专业分流机制、转专业条件与流程。"
    ),
    IntentType.CAREER_AND_DEVELOPMENT.value: (
        "毕业去向与发展：总体深造率与境内外比例、去向学校Top列表、"
        "就业率与主要行业岗位、薪资水平参考、代表性校友故事。"
    ),
    IntentType.CAMPUS_LIFE.value: (
        "校园生活：各书院特色与书院生活、宿舍配置与住宿费用、"
        "新生奖学金与助学金政策、各专业学费标准。"
    ),
    IntentType.OUT_OF_SCOPE.value: (
        "超出范围：与南科大招生咨询完全无关的问题，如其他学校、政治时事、娱乐等话题。"
    ),
    IntentType.OTHER.value: (
        "其他互动：问候、感谢、闲聊等简单交互，无需查询知识库即可回应。"
    ),
}

ALLOWED_INTENTS: tuple[str, ...] = tuple(INTENT_DESCRIPTIONS.keys())
DEFAULT_FALLBACK_INTENT: IntentType = IntentType.ADMISSION_POLICY

CONFIDENCE_THRESHOLD: float = float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.55"))

REQUIRED_SLOTS_BY_INTENT: dict[str, list[str]] = {
    IntentType.ADMISSION_POLICY.value: ["province"],
    IntentType.SCHOOL_OVERVIEW.value: [],
    IntentType.MAJOR_AND_TRAINING.value: [],
    IntentType.CAREER_AND_DEVELOPMENT.value: [],
    IntentType.CAMPUS_LIFE.value: [],
}

# 槽位定义：供大模型抽取时参考，键为槽位名，值为说明
SLOT_DESCRIPTIONS: dict[str, str] = {
    "province": "考生所在省份/直辖市/自治区，如：浙江、广东、北京、上海。仅当用户明确提到或可推断时填写，否则空字符串。",
    "year": "招生年份，如：2024、2025。仅当用户明确提到年份时填写，否则空字符串。",
}

# 缺槽位时反问话术（agentic_rag 内 build_clarify 与 generation 节点缺槽追问共用）
SLOT_CLARIFY_PROMPTS: dict[str, str] = {
    "province": "请问您是哪个省份的考生？这样我才能给出准确的招生政策信息。",
    "year": "请问您想咨询哪一年的招生政策？",
}

# 对话历史：提取最近 k 轮（每轮=1 条用户+1 条助手），供后续节点使用
HISTORY_LAST_K_TURNS: int = 2


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
    top_n: int = field(default_factory=lambda: int(os.getenv("RERANK_TOP_N", "8")))


@dataclass
class DBConfig:
    admissions_db_path: str = str(REPO_ROOT / "data" / "db" / "admissions.db")
    table_registry_path: str = str(SRC_ROOT / "config" / "table_registry.yaml")
    system_db_path: str = str(REPO_ROOT / "data" / "db" / "system.db")


@dataclass(frozen=True)
class VectorIngestConfig:
    categories: tuple[str, ...] = (
        "school_info",
        "admissions",
        "major",
        "career",
        "campus",
    )
    chunk_size: int = 512
    chunk_overlap: int = 64
    enable_ocr: bool = True
    parser_preference: tuple[str, ...] = ("builtin",)
    poll_interval: float = 1.0
    max_wait: int | None = None
    default_input_dir: str = "data/raw/unstructured"
    supported_extensions: tuple[str, ...] = (".md", ".txt", ".doc", ".docx", ".pdf")


@dataclass(frozen=True)
class SQLIngestConfig:
    if_exists: str = "append"


@dataclass(frozen=True)
class IngestConfig:
    config_path: str = str(INGEST_CONFIG_PATH)
    vector: VectorIngestConfig = field(default_factory=VectorIngestConfig)
    sql: SQLIngestConfig = field(default_factory=SQLIngestConfig)

    @classmethod
    def from_file(cls, path: Path = INGEST_CONFIG_PATH) -> "IngestConfig":
        defaults_vector = VectorIngestConfig()
        defaults_sql = SQLIngestConfig()
        raw = _load_yaml_config(path)

        vector_raw = raw.get("vector", {}) if isinstance(raw.get("vector", {}), dict) else {}
        sql_raw = raw.get("sql", {}) if isinstance(raw.get("sql", {}), dict) else {}

        chunk_size = _coerce_int(
            vector_raw.get("chunk_size"),
            defaults_vector.chunk_size,
            minimum=1,
        )
        chunk_overlap = _coerce_int(
            vector_raw.get("chunk_overlap"),
            defaults_vector.chunk_overlap,
            minimum=0,
        )
        if chunk_overlap >= chunk_size:
            chunk_overlap = defaults_vector.chunk_overlap

        max_wait_raw = vector_raw.get("max_wait")
        max_wait = None if max_wait_raw is None else _coerce_int(max_wait_raw, 0, minimum=1)
        if max_wait == 0:
            max_wait = None

        return cls(
            config_path=str(path),
            vector=VectorIngestConfig(
                categories=_coerce_str_tuple(vector_raw.get("categories"), defaults_vector.categories),
                chunk_size=chunk_size,
                chunk_overlap=chunk_overlap,
                enable_ocr=_coerce_bool(vector_raw.get("enable_ocr"), defaults_vector.enable_ocr),
                parser_preference=_coerce_str_tuple(
                    vector_raw.get("parser_preference"),
                    defaults_vector.parser_preference,
                ),
                poll_interval=_coerce_float(
                    vector_raw.get("poll_interval"),
                    defaults_vector.poll_interval,
                    minimum=0.0,
                ),
                max_wait=max_wait,
                default_input_dir=_coerce_str(
                    vector_raw.get("default_input_dir"),
                    defaults_vector.default_input_dir,
                ),
                supported_extensions=_coerce_str_tuple(
                    vector_raw.get("supported_extensions"),
                    defaults_vector.supported_extensions,
                ),
            ),
            sql=SQLIngestConfig(
                if_exists=_coerce_str(sql_raw.get("if_exists"), defaults_sql.if_exists),
            ),
        )


@dataclass
class AgentConfig:
    llm: LLMConfig | None = None
    milvus: MilvusConfig | None = None
    alaya: AlayaConfig | None = None
    rerank: RerankConfig | None = None
    db: DBConfig | None = None
    ingest: IngestConfig | None = None

    def __post_init__(self) -> None:
        self.llm = self.llm or LLMConfig()
        self.milvus = self.milvus or MilvusConfig()
        self.alaya = self.alaya or AlayaConfig()
        self.rerank = self.rerank or RerankConfig()
        self.db = self.db or DBConfig()
        self.ingest = self.ingest or IngestConfig.from_file()


config = AgentConfig()

__all__ = [
    "ALLOWED_INTENTS",
    "AgentConfig",
    "AlayaConfig",
    "CONFIDENCE_THRESHOLD",
    "DBConfig",
    "DEFAULT_FALLBACK_INTENT",
    "HISTORY_LAST_K_TURNS",
    "IngestConfig",
    "INTENT_DESCRIPTIONS",
    "IntentType",
    "LLMConfig",
    "MilvusConfig",
    "SQLIngestConfig",
    "REPO_ROOT",
    "RerankConfig",
    "REQUIRED_SLOTS_BY_INTENT",
    "SLOT_CLARIFY_PROMPTS",
    "SLOT_DESCRIPTIONS",
    "SRC_ROOT",
    "VectorIngestConfig",
    "config",
]
