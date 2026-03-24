import asyncio
from types import SimpleNamespace

from langchain_core.documents import Document

from src.graph.agentic_rag.node import search_planner as search_planner_module
from src.graph.agentic_rag.node import sufficiency_eval as sufficiency_eval_module
from src.graph.node import generation as generation_module
from src.graph.node import intent_classify as intent_classify_module
from src.graph.prompts import (
    BANNED_PROVENANCE_PHRASES,
    INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE,
    SEARCH_PLANNER_SYSTEM_PROMPT,
    SUFFICIENCY_EVAL_SYSTEM_PROMPT,
    build_generation_system_prompt,
    build_generation_user_prompt,
    build_missing_slot_context_suffix,
)


def test_generation_prompt_pushes_direct_answer_and_reduces_document_tone():
    prompt = build_generation_system_prompt("admission_policy", has_context=True)

    assert "先直接回答用户最关心的问题" in prompt
    assert "语气像招生老师或招生顾问" in prompt
    assert "不要向用户暴露检索、知识库、参考文档等内部过程" in prompt
    for phrase in BANNED_PROVENANCE_PHRASES:
        assert phrase in prompt


def test_generation_prompt_stays_close_to_current_query_without_extra_analysis():
    prompt = build_generation_system_prompt("admission_policy", has_context=True)

    assert "先紧扣用户明确问到的内容作答" in prompt
    assert "如果用户没有继续追问，不要主动扩展到报考建议" in prompt
    assert "默认回答广东近年录取概况" in prompt


def test_generation_prompt_distinguishes_broad_and_narrow_questions():
    prompt = build_generation_system_prompt("school_overview", has_context=True)

    assert "当问题属于概览型、开放型时，才在同一主题下适度补充相关维度" in prompt
    assert "当问题是狭窄、单点型时，优先只回答当前这一点" in prompt


def test_generation_prompt_uses_conditional_data_format_guidance():
    prompt = build_generation_system_prompt("admission_policy", has_context=True)

    assert "当材料中存在明确对比维度" in prompt
    assert "优先使用简洁表格" in prompt
    assert "当没有明显对比轴时，优先使用短列表或短段落" in prompt


def test_generation_prompt_uses_neutral_consultation_voice():
    prompt = build_generation_system_prompt("admission_policy", has_context=True)

    assert "服务对象是高中生和家长" not in prompt
    assert "面向考生和家长" not in prompt
    assert "南方科技大学本科招生咨询助手" in prompt


def test_generation_prompt_uses_user_facing_language_when_context_is_missing():
    prompt = build_generation_system_prompt("admission_policy", has_context=False)

    assert "我这边暂时没查到这项官方信息" in prompt
    assert "建议你查看南科大本科招生网最新公告" in prompt
    assert "当前暂无相关检索文档" not in prompt


def test_missing_slot_suffix_prefers_reference_then_natural_follow_up():
    suffix = build_missing_slot_context_suffix("province、year")

    assert "先给用户一个简短参考" in suffix
    assert "再自然追问缺少的信息" in suffix
    assert "不要出现“槽位”这种系统词" in suffix


def test_generation_user_prompt_tells_model_to_answer_current_question_only():
    prompt = build_generation_user_prompt(
        query="介绍一下广东省的录取情况",
        history="（无）",
        context="[1] 广东 2024 最低分 632",
    )

    assert "请先回答用户当前这个问题" in prompt
    assert "不要补充用户没有问到的分析或建议" in prompt


def test_generation_user_prompt_uses_conditional_scope_and_format_triggers():
    prompt = build_generation_user_prompt(
        query="广东省录取情况怎么样",
        history="（无）",
        context="[1] 广东 2024 最低分 632",
    )

    assert "当问题属于概览型或开放型时，才在同一主题下适度补充相关维度" in prompt
    assert "当材料里存在明确对比维度时，优先用简洁表格" in prompt


def test_admission_policy_prompt_defaults_to_recent_overview_before_strategy():
    prompt = build_generation_system_prompt("admission_policy", has_context=True)

    assert "如果用户问的是录取情况、分数线或位次趋势" in prompt
    assert "默认回答近年数据概况与必要口径" in prompt
    assert "只有用户继续追问时，才展开到报考策略" in prompt


def test_generation_prompt_allows_direct_inference_but_blocks_strategy_jump():
    prompt = build_generation_system_prompt("major_and_training", has_context=True)

    assert "允许基于已有材料做一步直接推理" in prompt
    assert "“要求物理+化学”可以进一步解释为“未选物理和化学的考生通常不符合该专业选科要求”" in prompt
    assert "不要把这类一步推理继续扩展成报考策略或适合人群判断" in prompt


def test_generation_user_prompt_allows_precise_inference_without_extra_judgment():
    prompt = build_generation_user_prompt(
        query="文科生能报吗",
        history="用户：这个专业要选物化吗",
        context="[1] 该专业选科要求：物理+化学",
    )

    assert "允许基于材料做直接且确定的一步推理" in prompt
    assert "不要把一步推理扩展成更多主观判断" in prompt


def test_intent_prompt_is_grounded_in_undergraduate_admissions_dialogue():
    assert "南科大本科招生咨询场景" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert "优先判断用户真正想咨询什么" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE


def test_intent_prompt_requests_fixed_global_slots_and_query_aware_required_slots():
    assert "province" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert "year" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert "required_slots" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE


def test_search_planner_prompt_is_for_admissions_answering_not_generic_retrieval():
    assert "为本科招生答疑服务" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "不要保留与检索无关的寒暄" in SEARCH_PLANNER_SYSTEM_PROMPT


def test_search_planner_prompt_preserves_user_question_and_adds_normalized_rewrite():
    assert "保留用户原问题中的关键口语表达" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "可以把这些表达合并进一条更适合检索的规范化主查询" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "不要直接替用户下判断" in SEARCH_PLANNER_SYSTEM_PROMPT


def test_search_planner_prompt_expands_search_terms_without_widening_scope():
    assert "“录取情况”补充为“录取分数 位次 招生录取情况”" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "不能把“广东录取情况”改写成“南科大报考建议”" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "- `rewritten_query`: 改写后的主查询" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "- `sub_queries`: 子查询列表" not in SEARCH_PLANNER_SYSTEM_PROMPT


def test_search_planner_prompt_expands_broad_questions_but_keeps_narrow_ones_tight():
    assert "优先在一条主查询中覆盖同一主题下最相关的几个维度" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "保持查询聚焦，不要额外扩写无关维度" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "如果问题大概率需要年份、省份、位次、分数等对比展示" in SEARCH_PLANNER_SYSTEM_PROMPT


def test_sufficiency_eval_prompt_checks_answerability_for_students_and_parents():
    assert "是否已经足以支持对考生或家长直接作答" in SUFFICIENCY_EVAL_SYSTEM_PROMPT
    assert "insufficient_docs" in SUFFICIENCY_EVAL_SYSTEM_PROMPT


def test_other_nodes_reference_shared_prompt_constants():
    assert intent_classify_module.INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE == INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert search_planner_module.SEARCH_PLANNER_SYSTEM_PROMPT == SEARCH_PLANNER_SYSTEM_PROMPT
    assert sufficiency_eval_module.SUFFICIENCY_EVAL_SYSTEM_PROMPT == SUFFICIENCY_EVAL_SYSTEM_PROMPT


def test_generation_component_uses_shared_counselor_style_prompt(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.requests = []

        async def astream(self, request):
            self.requests.append(request)
            yield SimpleNamespace(content="测试回复")

    fake_model = FakeModel()
    monkeypatch.setattr(generation_module, "get_model", lambda *_args, **_kwargs: fake_model)

    answer = asyncio.run(
        generation_module.GenerationComponent().generate(
            query="浙江考生631怎么算",
            intent="admission_policy",
            chunks=[Document(page_content="浙江综合评价录取规则示例")],
            messages=[],
        )
    )

    assert answer == "测试回复"

    system_prompt = fake_model.requests[0][0][1]
    user_prompt = fake_model.requests[0][1][1]
    assert "先直接回答用户最关心的问题" in system_prompt
    assert "不要用“文档中提到”" in system_prompt
    assert "请先回答用户当前这个问题" in user_prompt


def test_generation_component_treats_structured_results_as_available_context(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.requests = []

        async def astream(self, request):
            self.requests.append(request)
            yield SimpleNamespace(content="测试回复")

    fake_model = FakeModel()
    monkeypatch.setattr(generation_module, "get_model", lambda *_args, **_kwargs: fake_model)

    answer = asyncio.run(
        generation_module.GenerationComponent().generate(
            query="介绍一下广东省的录取情况",
            intent="admission_policy",
            chunks=[],
            structured_results=[{"province": "广东", "year": 2024, "min_score": "632"}],
            messages=[],
        )
    )

    assert answer == "测试回复"

    system_prompt = fake_model.requests[0][0][1]
    user_prompt = fake_model.requests[0][1][1]
    assert "我这边暂时没查到这项官方信息" not in system_prompt
    assert "SQL 结构化结果" in user_prompt
    assert "（当前没有可用材料）" not in user_prompt
