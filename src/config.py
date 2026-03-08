from __future__ import annotations

from enum import Enum


class IntentType(str, Enum):
    SCHOOL_OVERVIEW = "school_overview"
    ADMISSION_POLICY = "admission_policy"
    MAJOR_AND_TRAINING = "major_and_training"
    CAREER_AND_DEVELOPMENT = "career_and_development"
    CAMPUS_LIFE = "campus_life"


INTENT_DESCRIPTIONS: dict[str, str] = {
    IntentType.SCHOOL_OVERVIEW.value: (
        "学校概况：学校定位、办学特色、师资、科研实力、校园与城市整体介绍。"
    ),
    IntentType.ADMISSION_POLICY.value: (
        "招生政策：综合评价631模式、报名条件、时间节点、考核方式、录取规则、分省差异。"
    ),
    IntentType.MAJOR_AND_TRAINING.value: (
        "专业与培养：专业目录、培养方案、课程体系、入学后选专业机制、转专业政策。"
    ),
    IntentType.CAREER_AND_DEVELOPMENT.value: (
        "毕业去向与发展：深造率、升学去向、就业行业与岗位、职业发展路径。"
    ),
    IntentType.CAMPUS_LIFE.value: (
        "校园生活：书院制度、住宿、奖助学金、学费、校园日常与配套。"
    ),
}

ALLOWED_INTENTS: tuple[str, ...] = tuple(INTENT_DESCRIPTIONS.keys())
DEFAULT_FALLBACK_INTENT: IntentType = IntentType.ADMISSION_POLICY

# intent -> vector collection name
INTENT_COLLECTION_MAP: dict[str, str] = {
    IntentType.SCHOOL_OVERVIEW.value: "sustech_school_overview",
    IntentType.ADMISSION_POLICY.value: "sustech_admission_policy",
    IntentType.MAJOR_AND_TRAINING.value: "sustech_major_training",
    IntentType.CAREER_AND_DEVELOPMENT.value: "sustech_career_development",
    IntentType.CAMPUS_LIFE.value: "sustech_campus_life",
}
