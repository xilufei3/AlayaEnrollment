from __future__ import annotations

import asyncio
from types import SimpleNamespace

from src.graph.node.intent_classify import (
    IntentClassificationResult,
    create_intent_classify_node,
)


def _run_node(node, state):
    runtime = SimpleNamespace(context=SimpleNamespace(chat_model_id=None))
    return asyncio.run(node(state, runtime))


def test_intent_classify_overrides_year_from_current_query(monkeypatch) -> None:
    async def fake_classify(self, *, query, conversation_context=(), model_id=None):
        return IntentClassificationResult(
            intent="admission_policy",
            query_mode="factual_query",
            reason="ok",
            confidence=0.9,
            slots={"province": "广东", "year": "2024"},
            required_slots=[],
        )

    monkeypatch.setattr(
        "src.graph.node.intent_classify.EnrollmentIntentClassifier.classify",
        fake_classify,
    )

    node = create_intent_classify_node()
    result = _run_node(
        node,
        {
            "query": "广东近几年录取情况",
            "slots": {"province": "广东", "year": "2024"},
            "messages": [],
        },
    )

    assert result["slots"]["province"] == "广东"
    assert result["slots"]["year"] == "近几年"


def test_intent_classify_clears_year_when_current_query_has_no_time_expression(monkeypatch) -> None:
    async def fake_classify(self, *, query, conversation_context=(), model_id=None):
        return IntentClassificationResult(
            intent="admission_policy",
            query_mode="factual_query",
            reason="ok",
            confidence=0.9,
            slots={"province": "广东", "year": "2025"},
            required_slots=[],
        )

    monkeypatch.setattr(
        "src.graph.node.intent_classify.EnrollmentIntentClassifier.classify",
        fake_classify,
    )

    node = create_intent_classify_node()
    result = _run_node(
        node,
        {
            "query": "广东录取情况怎么样",
            "slots": {"province": "广东", "year": "2025"},
            "messages": [],
        },
    )

    assert result["slots"]["province"] == "广东"
    assert "year" not in result["slots"]
