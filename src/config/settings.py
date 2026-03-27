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


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    value = raw.strip().lower()
    if value == "true":
        return True
    if value == "false":
        return False
    return default


class IntentType(str, Enum):
    SCHOOL_OVERVIEW = "school_overview"
    ADMISSION_POLICY = "admission_policy"
    MAJOR_AND_TRAINING = "major_and_training"
    CAREER_AND_DEVELOPMENT = "career_and_development"
    CAMPUS_LIFE = "campus_life"
    OUT_OF_SCOPE = "out_of_scope"
    OTHER = "other"


class QueryModeType(str, Enum):
    INTRODUCTION = "introduction"
    JUDGMENT = "judgment"
    FACTUAL_QUERY = "factual_query"
    COMPARISON = "comparison"
    ADVICE = "advice"
    OTHER = "other"


INTENT_DESCRIPTIONS: dict[str, str] = {
    IntentType.SCHOOL_OVERVIEW.value: (
        "学校概况：学校定位、办学特色（书院制、导师制、国际化、小班教学、本科生科研）、"
        "校园与城市（深圳优势、校园环境）、师资概况（院士、海归比例、师生比）、科研实力。"
    ),
    IntentType.ADMISSION_POLICY.value: (
        "招生政策：综合评价631模式详细说明、各省报名条件与资格、招生计划与人数、招生办联系方式"
        "报名/考核/录取时间节点、能力测试与面试方式、录取规则与历年分数线位次、各省差异政策。"
    ),
    IntentType.MAJOR_AND_TRAINING.value: (
        "专业与培养：全部本科专业目录与院系归属、各专业培养目标与核心课程、专业内容"
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
QUERY_MODE_DESCRIPTIONS: dict[str, str] = {
    QueryModeType.INTRODUCTION.value: (
        "介绍型：用户想了解某个学校、专业、政策、制度或校园事项的整体情况，"
        "核心诉求是建立一个较完整的认识，而不是只问单个事实点或做资格判断。\n"
        "特征：问题里通常有“介绍一下”“怎么样”“是什么情况”“整体如何”“展开说说”；"
        "用户希望得到有层次的概览，而不是一个单点数据答案。\n"
        "跨意图举例：\n"
        "- 学校概况：介绍一下南科大 / 南科大整体怎么样 / 南科大有什么特色\n"
        "- 招生政策：综合评价招生整体是怎么回事 / 南科大招生政策大概是怎样的\n"
        "- 专业培养：计算机专业怎么样 / 介绍一下大类培养和专业分流\n"
        "- 毕业去向：南科大学生毕业去向怎么样 / 深造就业整体情况如何\n"
        "- 校园生活：宿舍和书院生活怎么样 / 介绍一下校园生活"
    ),
    QueryModeType.JUDGMENT.value: (
        "判断型：用户想知道自己或某类考生是否符合条件、有没有资格、能不能做某件事，"
        "核心诉求是得到一个明确判断，而不是只听规则介绍。\n"
        "特征：问题里通常有“能不能”“有没有资格”“符不符合”“我这种情况”“算不算”“有没有机会”；"
        "用户往往会带入自己的分数、选科、地区、年级或目标专业。\n"
        "跨意图举例：\n"
        "- 招生政策：广东600分有机会吗 / 竞赛生有资格报名吗 / 没选化学还能报吗\n"
        "- 专业培养：大一可以转专业吗 / GPA不够还能申请转专业吗\n"
        "- 毕业去向：本科直接就业前景好吗 / 这个专业适合以后读博吗\n"
        "- 校园生活：低收入家庭能申请助学金吗 / 新生都能申请奖学金吗"
    ),
    QueryModeType.FACTUAL_QUERY.value: (
        "事实查询：用户想获取一个或一组明确的客观信息，答案通常是事实、时间、数字、名单、费用、分数、位次或简短说明。\n"
        "特征：问题指向具体信息点，通常可以直接作答或用简短表格呈现；"
        "问题里常见“多少”“几号”“有没有”“是什么”“几人间”“多少分”“多少位次”。\n"
        "跨意图举例：\n"
        "- 学校概况：有多少院士 / 学校在哪里 / 师生比是多少\n"
        "- 招生政策：报名截止时间是什么时候 / 广东今年招多少人 / 近三年录取位次是多少\n"
        "- 专业培养：有没有金融专业 / 计算机属于哪个学院 / 转专业什么时候申请\n"
        "- 毕业去向：深造率是多少 / 主要去了哪些学校 / 就业率大概多少\n"
        "- 校园生活：宿舍几人间 / 学费多少 / 有空调吗 / 住宿费是多少"
    ),
    QueryModeType.COMPARISON.value: (
        "对比型：用户明确想比较两个或多个对象、年份、专业、省份或方案，"
        "希望了解差异、优劣或变化趋势，而不是分别做独立介绍。\n"
        "特征：问题里通常有“哪个更”“和……相比”“区别是什么”“差多少”“对比一下”“近几年变化如何”；"
        "回答时通常需要并列展开后再给总结。\n"
        "跨意图举例：\n"
        "- 招生政策：广东和浙江录取难度差多少 / 综合评价和统招有什么区别\n"
        "- 专业培养：计算机和电子信息哪个好就业 / 直申专业和入学后分流有什么区别\n"
        "- 毕业去向：境内深造和出国读研哪个比例更高\n"
        "- 校园生活：不同书院的住宿条件有差别吗"
    ),
    QueryModeType.ADVICE.value: (
        "建议型：用户想获得报考、备考、选专业、发展规划方面的建议，"
        "核心诉求不是唯一标准答案，而是希望得到可执行的方向性建议。\n"
        "特征：问题里通常有“怎么准备”“值不值得”“怎么选”“建议”“该怎么办”“适合什么”；"
        "回答往往需要结合用户情况给出路径，而不是只查事实。\n"
        "跨意图举例：\n"
        "- 招生政策：高二现在怎么准备综合评价 / 值不值得冲一下南科大\n"
        "- 专业培养：我喜欢数学适合报什么专业 / 想做科研该怎么选专业\n"
        "- 毕业去向：以后想去互联网大厂该怎么规划 / 想出国读研选什么方向更合适\n"
        "- 学校概况：南科大适合什么样的学生 / 什么样的考生更建议重点关注南科大"
    ),
    QueryModeType.OTHER.value: (
        "其它：用户的话不属于以上几类中的主要任务，通常是寒暄、感谢、轻松闲聊、泛化追问，"
        "或者信息目标不够明确、问题形态混杂但主诉求不突出、当前无法稳定判断应归入哪一种模式，"
        "暂时不适合进入完整答题模式。\n"
        "特征：问题里没有清晰的介绍、判断、查询、对比或建议诉求；"
        "或者虽然涉及招生相关内容，但主问题形态不明确，继续强行细分反而容易误判；"
        "更适合简短回应后继续引导用户明确问题。\n"
        "跨意图举例：\n"
        "- 互动：你好 / 谢谢老师 / 明白了\n"
        "- 泛化开场：我先随便了解一下 / 最近有点想看看南科大\n"
        "- 模糊追问：这个呢 / 那另一个怎么样 / 还有别的吗\n"
        "- 模式不明确：我这种情况怎么说呢 / 这个到底算哪种 / 先大概聊聊吧"
    ),
}
ALLOWED_QUERY_MODES: tuple[str, ...] = tuple(QUERY_MODE_DESCRIPTIONS.keys())
DEFAULT_QUERY_MODE: QueryModeType = QueryModeType.FACTUAL_QUERY

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
    "year": "招生年份或时间表达，如：2024、2025、2023-2025、近几年、近两年、往年。year 必须根据当前用户这一问单独提取并更新；如果当前问题没有明确时间表达，则填空字符串。",
}

# 对话历史：提取最近 k 轮（每轮=1 条用户+1 条助手），供后续节点使用
HISTORY_LAST_K_TURNS: int = 4


@dataclass
class LLMConfig:
    api_key: str = field(
        default_factory=lambda: os.getenv(
            "QWEN_API_KEY",
            os.getenv("DEEPSEEK_API_KEY", ""),
        ).strip()
    )
    base_url: str = field(
        default_factory=lambda: os.getenv(
            "QWEN_BASE_URL",
            os.getenv(
                "DEEPSEEK_BASE_URL",
                "https://star.sustech.edu.cn/service/model/qwen/v1",
            ),
        ).strip()
    )
    model: str = field(
        default_factory=lambda: os.getenv(
            "QWEN_MODEL_NAME",
            os.getenv("DEEPSEEK_MODEL_NAME", "qwen3.5-397b-a17b-fp8"),
        ).strip()
    )
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
class EmbeddingConfig:
    use_custom: bool = field(default_factory=lambda: _env_bool("USE_CUSTOM_EMBEDDING", False))
    custom_api_base: str = field(
        default_factory=lambda: os.getenv("CUSTOM_EMBEDDING_API_BASE", "http://172.18.41.222:18005")
    )
    custom_model: str = field(
        default_factory=lambda: os.getenv("CUSTOM_EMBEDDING_MODEL", "Qwen/Qwen3-Embedding-8B")
    )
    custom_api_key: str = field(default_factory=lambda: os.getenv("CUSTOM_EMBEDDING_API_KEY", "").strip())
    custom_api_key_file: str = field(
        default_factory=lambda: os.getenv(
            "CUSTOM_EMBEDDING_API_KEY_FILE",
            str(REPO_ROOT / ".sglang_api_key"),
        ).strip()
    )
    custom_timeout: int = field(default_factory=lambda: int(os.getenv("CUSTOM_EMBEDDING_TIMEOUT", "120")))
    custom_batch_size: int = field(
        default_factory=lambda: max(1, int(os.getenv("CUSTOM_EMBEDDING_BATCH_SIZE", "32")))
    )

    @property
    def provider_name(self) -> str:
        return "custom" if self.use_custom else "alaya"


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
    embedding: EmbeddingConfig | None = None
    rerank: RerankConfig | None = None
    db: DBConfig | None = None
    ingest: IngestConfig | None = None

    def __post_init__(self) -> None:
        self.llm = self.llm or LLMConfig()
        self.milvus = self.milvus or MilvusConfig()
        self.alaya = self.alaya or AlayaConfig()
        self.embedding = self.embedding or EmbeddingConfig()
        self.rerank = self.rerank or RerankConfig()
        self.db = self.db or DBConfig()
        self.ingest = self.ingest or IngestConfig.from_file()


config = AgentConfig()

__all__ = [
    "ALLOWED_INTENTS",
    "ALLOWED_QUERY_MODES",
    "AgentConfig",
    "AlayaConfig",
    "CONFIDENCE_THRESHOLD",
    "DBConfig",
    "DEFAULT_FALLBACK_INTENT",
    "DEFAULT_QUERY_MODE",
    "HISTORY_LAST_K_TURNS",
    "IngestConfig",
    "EmbeddingConfig",
    "INTENT_DESCRIPTIONS",
    "IntentType",
    "LLMConfig",
    "MilvusConfig",
    "QUERY_MODE_DESCRIPTIONS",
    "QueryModeType",
    "SQLIngestConfig",
    "REPO_ROOT",
    "RerankConfig",
    "REQUIRED_SLOTS_BY_INTENT",
    "SLOT_DESCRIPTIONS",
    "SRC_ROOT",
    "VectorIngestConfig",
    "config",
]
