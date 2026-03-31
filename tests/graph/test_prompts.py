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
)


def test_generation_prompt_pushes_direct_answer_and_reduces_document_tone():
    prompt = build_generation_system_prompt("admission_policy", "factual_query", has_context=True)

    assert "以招生顾问的口吻作答" in prompt
    assert "只能来自本轮注入的【参考材料】" in prompt
    assert "暴露内部流程的表述" in prompt
    for phrase in BANNED_PROVENANCE_PHRASES:
        assert phrase in prompt


def test_generation_prompt_stays_close_to_current_query_without_extra_analysis():
    prompt = build_generation_system_prompt("admission_policy", "factual_query", has_context=True)

    assert "## 作答结构：事实查询型" in prompt
    assert "开头直接给出核心事实，无须铺垫。" in prompt
    assert "不主动补充建议或政策背景" in prompt


def test_generation_prompt_distinguishes_broad_and_narrow_questions():
    intro_prompt = build_generation_system_prompt("school_overview", "introduction", has_context=True)
    factual_prompt = build_generation_system_prompt("school_overview", "factual_query", has_context=True)

    assert "## 作答结构：介绍型" in intro_prompt
    assert "从参考材料中选取与问题直接相关的维度分点展开" in intro_prompt
    assert "## 作答结构：事实查询型" in factual_prompt
    assert "开头直接给出核心事实，无须铺垫。" in factual_prompt


def test_generation_prompt_uses_conditional_data_format_guidance():
    system_prompt = build_generation_system_prompt("admission_policy", "factual_query", has_context=True)
    user_prompt = build_generation_user_prompt(
        query="广东省录取情况怎么样",
        query_mode="factual_query",
        history="（无）",
        context="[1] 广东 2024 最低分 632",
    )

    assert "结构化数据（SQL 查询结果）可用时，优先采用" in system_prompt
    assert "存在明确对比维度时，优先用简洁表格呈现。" in user_prompt


def test_generation_prompt_requires_policy_content_to_reference_official_notice():
    prompt = build_generation_system_prompt("admission_policy", "factual_query", has_context=True)

    assert "涉及招生政策、报名资格、时间节点" in prompt
    assert "具体以南方科技大学招生办公室当年发布的官方公告或简章为准。" in prompt


def test_generation_prompt_uses_neutral_consultation_voice():
    prompt = build_generation_system_prompt("admission_policy", "factual_query", has_context=True)

    assert "服务对象是高中生和家长" not in prompt
    assert "面向考生和家长" not in prompt
    assert "南方科技大学本科招生咨询助手" in prompt
    assert "| 今年 / 当年 | 2026 |" in prompt
    assert "| 近两年 | 2025、2024 |" in prompt


def test_generation_prompt_uses_user_facing_language_when_context_is_missing():
    prompt = build_generation_system_prompt("admission_policy", "factual_query", has_context=False)

    assert "本轮参考材料为空或不包含能支撑当前问题的官方信息。" in prompt
    assert "zsb@sustech.edu.cn" in prompt
    assert "http://zs.sustech.edu.cn" in prompt
    assert "当前暂无相关检索文档" not in prompt


def test_generation_user_prompt_tells_model_to_answer_current_question_only():
    prompt = build_generation_user_prompt(
        query="介绍一下广东省的录取情况",
        query_mode="factual_query",
        history="（无）",
        context="[1] 广东 2024 最低分 632",
    )

    assert "## 用户问题" in prompt
    assert "直接回答当前问题，不偏题。" in prompt
    assert "材料中未出现的内容不得补充。" in prompt


def test_generation_user_prompt_uses_conditional_scope_and_format_triggers():
    prompt = build_generation_user_prompt(
        query="广东省录取情况怎么样",
        query_mode="factual_query",
        history="（无）",
        context="[1] 广东 2024 最低分 632",
    )

    assert "仅当问题形态为 introduction 或 factual_query 时" in prompt
    assert "存在明确对比维度时，优先用简洁表格呈现。" in prompt


def test_admission_policy_prompt_defaults_to_recent_overview_before_strategy():
    prompt = build_generation_system_prompt("admission_policy", "introduction", has_context=True)

    assert "## 当前话题范围：招生政策" in prompt
    assert "综合评价招生、631 录取模式" in prompt
    assert "历年分数与位次" in prompt


def test_generation_prompt_allows_direct_inference_but_blocks_strategy_jump():
    prompt = build_generation_system_prompt("major_and_training", "judgment", has_context=True)

    assert "## 作答结构：判断型" in prompt
    assert "首句直接给出结论：能 / 不能 / 视具体情况而定。" in prompt
    assert "不延伸为政策介绍" in prompt


def test_generation_user_prompt_allows_precise_inference_without_extra_judgment():
    prompt = build_generation_user_prompt(
        query="文科生能报吗",
        query_mode="judgment",
        history="用户：这个专业要选物化吗",
        context="[1] 该专业选科要求：物理+化学",
    )

    assert "## 问题形态" in prompt
    assert "judgment" in prompt
    assert "直接回答当前问题，不偏题。" in prompt


def test_intent_prompt_is_grounded_in_undergraduate_admissions_dialogue():
    assert "南科大本科招生咨询场景" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert "优先判断用户真正想咨询什么" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE


def test_intent_prompt_requests_fixed_global_slots_and_query_aware_required_slots():
    assert "province" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert "year" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert "近几年" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert "不要从历史补 year" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
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


def test_search_planner_prompt_uses_previous_covered_points_to_expand_retry_search():
    assert "上一轮评估理由" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "本轮已覆盖要点" in SEARCH_PLANNER_SYSTEM_PROMPT
    assert "优先补充未覆盖维度" in SEARCH_PLANNER_SYSTEM_PROMPT


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
            query_mode="factual_query",
            chunks=[Document(page_content="浙江综合评价录取规则示例")],
            messages=[],
        )
    )

    assert answer == "测试回复"

    system_prompt = fake_model.requests[0][0][1]
    user_prompt = fake_model.requests[0][1][1]
    assert "## 作答结构：事实查询型" in system_prompt
    assert '"文档中提到"' in system_prompt
    assert "直接回答当前问题，不偏题。" in user_prompt


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
            query_mode="introduction",
            chunks=[],
            structured_results=[
                {
                    "table": "admission_scores",
                    "description": "各省各年份录取数据宽表",
                    "query_key": ["province", "year"],
                    "columns": {
                        "province": "省份名称",
                        "year": "年份",
                        "min_score": "最低分原文",
                    },
                    "items": [{"province": "广东", "year": 2024, "min_score": "632"}],
                }
            ],
            messages=[],
        )
    )

    assert answer == "测试回复"

    system_prompt = fake_model.requests[0][0][1]
    user_prompt = fake_model.requests[0][1][1]
    assert "我这边暂时没查到这项官方信息" not in system_prompt
    assert "如果需要使用下面的 SQL 结构化数据" in user_prompt
    assert "请整理成简洁、规范的表格返回" in user_prompt
    assert "完整展示该表已返回的列" in user_prompt
    assert "按字段说明中的列顺序组织表头" in user_prompt
    assert "SQL 结构化结果" in user_prompt
    assert "admission_scores" in user_prompt
    assert "字段说明" in user_prompt
    assert "（本轮无可用参考材料）" not in user_prompt


def test_generation_component_adds_qq_channel_format_suffix(monkeypatch):
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
            query="介绍一下综合评价招生",
            intent="admission_policy",
            query_mode="introduction",
            chunks=[Document(page_content="综合评价招生采用 631 模式。")],
            messages=[],
            system_suffix=generation_module.QQ_SYSTEM_SUFFIX,
            channel="qq",
        )
    )

    assert answer == "测试回复"

    system_prompt = fake_model.requests[0][0][1]
    assert "## 渠道格式要求：QQ Bot" in system_prompt
    assert "禁止任何 Markdown" in system_prompt
