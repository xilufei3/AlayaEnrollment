from __future__ import annotations

import asyncio

from langchain_core.documents import Document

from src.graph.agentic_rag.node.sufficiency_eval import create_sufficiency_eval_node


def _run_node(node, state: dict) -> dict:
    return asyncio.run(node(state))


def test_sufficiency_eval_does_not_request_slots_when_current_query_does_not_need_them(
    monkeypatch,
) -> None:
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "eval_result": "sufficient",
                "missing_slots": [],
                "reason": "enough",
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sufficiency_eval.get_model",
        lambda _model_id: DummyModel(),
    )

    node = create_sufficiency_eval_node(model_id="eval")
    result = _run_node(
        node,
        {
            "query": "631是什么意思",
            "intent": "admission_policy",
            "slots": {},
            "required_slots": [],
            "chunks": [
                Document(page_content="631 是综合评价录取模式。"),
                Document(page_content="学校会结合高考成绩、校测和高中学业成绩。"),
            ],
        }
    )

    assert result["missing_slots"] == []


def test_sufficiency_eval_ignores_missing_slots_and_still_evaluates_materials(
    monkeypatch,
) -> None:
    captured: dict[str, object] = {}

    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            captured["messages"] = messages
            return {
                "eval_result": "sufficient",
                "missing_slots": [],
                "reason": "enough",
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sufficiency_eval.get_model",
        lambda _model_id: DummyModel(),
    )

    node = create_sufficiency_eval_node(model_id="eval")
    result = _run_node(
        node,
        {
            "query": "帮我比较不同省份的新生奖学金情况",
            "intent": "campus_life",
            "slots": {},
            "required_slots": ["province"],
            "missing_slots": ["province"],
            "chunks": [Document(page_content="新生奖学金政策会因省份和年份有所差异。")],
        }
    )

    assert result["eval_result"] == "sufficient"
    assert result["missing_slots"] == []
    assert "可用材料摘要" in captured["messages"][1][1]


def test_sufficiency_eval_accepts_structured_results_without_chunks(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            captured["messages"] = messages
            captured["response_format"] = response_format
            return {
                "eval_result": "sufficient",
                "missing_slots": [],
                "reason": "sql rows are enough",
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sufficiency_eval.get_model",
        lambda _model_id: DummyModel(),
    )

    node = create_sufficiency_eval_node(model_id="eval")
    result = _run_node(
        node,
        {
            "query": "广东 2024 年录取分数线是多少",
            "intent": "admission_policy",
            "slots": {},
            "required_slots": [],
            "chunks": [],
            "structured_results": [
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
        }
    )

    assert result["eval_result"] == "sufficient"
    user_prompt = captured["messages"][1][1]
    assert "结构化 SQL 结果" in user_prompt
    assert "admission_scores" in user_prompt
    assert '"province": "广东"' in user_prompt


def test_sufficiency_eval_forces_one_more_round_for_factual_query_and_records_chunk_highlights(
    monkeypatch,
) -> None:
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "eval_result": "sufficient",
                "missing_slots": [],
                "reason": "当前材料已可初步回答",
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sufficiency_eval.get_model",
        lambda _model_id: DummyModel(),
    )

    node = create_sufficiency_eval_node(model_id="eval")
    result = _run_node(
        node,
        {
            "query": "广东近几年录取情况怎么样",
            "intent": "admission_policy",
            "query_mode": "factual_query",
            "slots": {"province": "广东", "year": "近几年"},
            "required_slots": [],
            "chunks": [
                Document(page_content="2025 年广东录取人数较多，普通批和综评均有覆盖。"),
                Document(page_content="近年最低分、平均分和位次波动不大，整体保持在较高区间。"),
            ],
            "rag_iteration": 1,
            "max_iterations": 2,
        },
    )

    assert result["eval_result"] == "insufficient_docs"
    assert "默认补充一轮检索" in result["eval_reason"]
    assert "本轮已覆盖要点" in result["eval_reason"]
    assert "2025 年广东录取人数较多" in result["eval_reason"]
