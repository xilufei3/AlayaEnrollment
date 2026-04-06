from __future__ import annotations

import asyncio

from langchain_core.documents import Document

from src.graph.agentic_rag.node.sufficiency_eval import create_sufficiency_eval_node


def _run_node(node, state: dict) -> dict:
    return asyncio.run(node(state))


def test_sufficiency_eval_extracts_matching_qa_doc_from_chunks(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            captured["messages"] = messages
            return {
                "eval_result": "sufficient",
                "reason": "matched qa is enough",
                "qa_doc": {
                    "question": "631是什么意思？",
                    "answer": (
                        "631 是综合评价录取模式，一般指高考成绩占 60%，"
                        "学校能力测试占 30%，高中学业成绩占 10%。"
                    ),
                },
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sufficiency_eval.get_model",
        lambda *_args, **_kwargs: DummyModel(),
    )

    node = create_sufficiency_eval_node(model_id="eval")
    result = _run_node(
        node,
        {
            "query": "631是什么意思",
            "intent": "admission_policy",
            "chunks": [
                Document(
                    page_content=(
                        "Q: 奖学金有哪些？\n"
                        "A: 学校设有多种奖助项目。\n\n"
                        "Q: 631是什么意思？\n"
                        "A: 631 是综合评价录取模式，一般指高考成绩占 60%，"
                        "学校能力测试占 30%，高中学业成绩占 10%。"
                    ),
                    metadata={"source": "faq.md"},
                )
            ],
        },
    )

    qa_doc = result["qa_doc"]
    assert qa_doc is not None
    assert qa_doc.page_content.startswith("Q: 631是什么意思")
    assert "A: 631 是综合评价录取模式" in qa_doc.page_content
    assert qa_doc.metadata["qa_extracted"] is True
    assert qa_doc.metadata["qa_source"] == "eval_llm"
    assert "原始用户问题：631是什么意思" in captured["messages"][1][1]


def test_sufficiency_eval_returns_empty_qa_doc_when_no_match(monkeypatch) -> None:
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "eval_result": "sufficient",
                "reason": "general material is enough",
                "qa_doc": None,
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sufficiency_eval.get_model",
        lambda *_args, **_kwargs: DummyModel(),
    )

    node = create_sufficiency_eval_node(model_id="eval")
    result = _run_node(
        node,
        {
            "query": "宿舍几人间",
            "intent": "campus_life",
            "chunks": [
                Document(
                    page_content=(
                        "Q: 631是什么意思？\n"
                        "A: 631 是综合评价录取模式。"
                    )
                )
            ],
        },
    )

    assert result["qa_doc"] is None
