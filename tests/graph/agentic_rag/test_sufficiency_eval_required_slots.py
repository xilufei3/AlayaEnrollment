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


def test_sufficiency_eval_uses_required_slots_even_when_intent_default_is_empty(
    monkeypatch,
) -> None:
    """When missing_slots is passed in state, the evaluator short-circuits to missing_slots
    without calling the LLM, regardless of what the model would return."""

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
            "query": "帮我比较不同省份的新生奖学金情况",
            "intent": "campus_life",
            "slots": {},
            "required_slots": ["province"],
            "missing_slots": ["province"],
            "chunks": [Document(page_content="新生奖学金政策会因省份和年份有所差异。")],
        }
    )

    assert result["eval_result"] == "missing_slots"
    assert result["missing_slots"] == ["province"]


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
            "structured_results": [{"province": "广东", "year": 2024, "min_score": "632"}],
        }
    )

    assert result["eval_result"] == "sufficient"
    user_prompt = captured["messages"][1][1]
    assert "结构化 SQL 结果" in user_prompt
    assert '"province": "广东"' in user_prompt
