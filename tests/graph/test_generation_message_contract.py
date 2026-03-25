from __future__ import annotations

import asyncio
from types import SimpleNamespace

from langchain_core.messages import AIMessage, HumanMessage

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
