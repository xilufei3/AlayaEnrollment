from __future__ import annotations

import os
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

SRC_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = SRC_ROOT.parent


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
    "ALLOWED_INTENTS",
    "AgentConfig",
    "AlayaConfig",
    "CONFIDENCE_THRESHOLD",
    "DBConfig",
    "DEFAULT_FALLBACK_INTENT",
    "HISTORY_LAST_K_TURNS",
    "INTENT_DESCRIPTIONS",
    "IntentType",
    "LLMConfig",
    "MilvusConfig",
    "REPO_ROOT",
    "RerankConfig",
    "REQUIRED_SLOTS_BY_INTENT",
    "SLOT_CLARIFY_PROMPTS",
    "SLOT_DESCRIPTIONS",
    "SRC_ROOT",
    "config",
]
