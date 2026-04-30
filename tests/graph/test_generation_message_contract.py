from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, HumanMessage

from src.graph.node import generation as generation_module
from src.graph.node.generation import GenerationComponent
from src.graph.node.generation import create_generation_node


def _run_node(node, state):
    runtime = SimpleNamespace(context=SimpleNamespace(chat_model_id=None))
    return asyncio.run(node(state, runtime))


def test_generation_node_returns_ai_message_delta_and_excludes_current_query_from_history(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_generate(self, **kwargs):
        captured.update(kwargs)
        return "测试回复"

    monkeypatch.setattr("src.graph.node.generation.GenerationComponent.generate", fake_generate)

    node = create_generation_node()
    result = _run_node(
        node,
        {
            "query": "今年广东录取情况怎么样",
            "intent": "admission_policy",
            "chunks": [],
            "messages": [
                HumanMessage(content="之前的问题"),
                AIMessage(content="之前的回答"),
                HumanMessage(content="今年广东录取情况怎么样"),
            ],
        },
    )

    history = captured["messages"]
    assert history == [
        HumanMessage(content="之前的问题"),
        AIMessage(content="之前的回答"),
    ]
    assert captured["eval_result"] == ""
    assert result["answer"] == "测试回复"
    assert result["messages"] == [AIMessage(content="测试回复")]


def test_generation_node_missing_slots_returns_only_ai_delta(monkeypatch):
    """Even if missing_slots exists in state, generate() still answers normally."""

    async def fake_generate(self, **kwargs):
        return "请补充省份"

    monkeypatch.setattr("src.graph.node.generation.GenerationComponent.generate", fake_generate)

    node = create_generation_node()
    result = _run_node(
        node,
        {
            "query": "录取情况怎么样",
            "intent": "admission_policy",
            "missing_slots": ["province"],
            "chunks": [],
            "messages": [HumanMessage(content="录取情况怎么样")],
        },
    )

    assert result["answer"] == "请补充省份"
    assert result["messages"] == [AIMessage(content="请补充省份")]


def test_generation_node_passes_rag_eval_result_to_component(monkeypatch):
    captured: dict[str, object] = {}

    async def fake_generate(self, **kwargs):
        captured.update(kwargs)
        return "测试回复"

    monkeypatch.setattr("src.graph.node.generation.GenerationComponent.generate", fake_generate)

    node = create_generation_node()
    result = _run_node(
        node,
        {
            "query": "介绍一下他的个人经历",
            "intent": "school_overview",
            "query_mode": "introduction",
            "chunks": [Document(page_content="李凤亮校长出席学校活动。")],
            "eval_result": "insufficient_docs",
            "eval_reason": "缺少个人经历材料",
            "messages": [HumanMessage(content="介绍一下他的个人经历")],
        },
    )

    assert captured["eval_result"] == "insufficient_docs"
    assert result["answer"] == "测试回复"


def test_generation_component_ignores_chunks_when_eval_result_is_insufficient(monkeypatch):
    class FakeModel:
        def __init__(self):
            self.requests = []

        async def astream(self, request):
            self.requests.append(request)
            yield SimpleNamespace(content="测试回复")

    fake_model = FakeModel()
    monkeypatch.setattr(generation_module, "get_model", lambda *_args, **_kwargs: fake_model)

    answer = asyncio.run(
        GenerationComponent().generate(
            query="介绍一下他的个人经历",
            intent="school_overview",
            query_mode="introduction",
            chunks=[Document(page_content="李凤亮校长出席学校活动。")],
            eval_result="insufficient_docs",
            messages=[],
        )
    )

    assert answer == "测试回复"

    system_prompt = fake_model.requests[0][0][1]
    user_prompt = fake_model.requests[0][1][1]
    assert "## 材料不足协议" in system_prompt
    assert "（本轮无可用参考材料）" in user_prompt
    assert "李凤亮校长出席学校活动" not in user_prompt
