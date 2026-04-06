from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain_core.documents import Document

from src.graph.node.generation import GenerationComponent, create_generation_node


def test_generation_component_includes_qa_doc_in_user_context(monkeypatch) -> None:
    class FakeModel:
        def __init__(self) -> None:
            self.requests = []

        async def astream(self, request):
            self.requests.append(request)
            yield SimpleNamespace(content="测试回复")

    fake_model = FakeModel()
    monkeypatch.setattr("src.graph.node.generation.get_model", lambda *_args, **_kwargs: fake_model)

    answer = asyncio.run(
        GenerationComponent().generate(
            query="631是什么意思",
            intent="admission_policy",
            query_mode="factual_query",
            chunks=[],
            qa_doc=Document(page_content="Q: 631是什么意思？\nA: 631 是综合评价录取模式。"),
            messages=[],
        )
    )

    assert answer == "测试回复"
    user_prompt = fake_model.requests[0][1][1]
    assert "## 命中 QA（最高优先级）" in user_prompt
    assert "Q: 631是什么意思？" in user_prompt
    assert "A: 631 是综合评价录取模式。" in user_prompt
    assert "直接输出其中 `A:` 后的答案原文作为完整回复" in user_prompt


def test_generation_node_passes_qa_doc_to_component(monkeypatch) -> None:
    captured: dict[str, object] = {}

    async def fake_generate(self, **kwargs):
        captured.update(kwargs)
        return "测试回复"

    monkeypatch.setattr("src.graph.node.generation.GenerationComponent.generate", fake_generate)

    node = create_generation_node()
    qa_doc = Document(page_content="Q: 631是什么意思？\nA: 631 是综合评价录取模式。")
    runtime = SimpleNamespace(context=SimpleNamespace(chat_model_id=None))

    result = asyncio.run(
        node(
            {
                "query": "631是什么意思",
                "intent": "admission_policy",
                "query_mode": "factual_query",
                "chunks": [],
                "qa_doc": qa_doc,
                "messages": [],
            },
            runtime,
        )
    )

    assert captured["qa_doc"] == qa_doc
    assert result["answer"] == "测试回复"
