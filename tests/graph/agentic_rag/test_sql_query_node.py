from __future__ import annotations

import asyncio

from src.graph.agentic_rag.node.sql_query import create_sql_query_node


def _run_node(node, state: dict) -> dict:
    return asyncio.run(node(state))


def test_sql_query_node_passes_multi_value_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_query_admission_scores(*, provinces=None, years=None, limit=20):
        captured["provinces"] = provinces
        captured["years"] = years
        captured["limit"] = limit
        return [{"province": "广东", "year": 2024, "min_score": "640"}]

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_query.query_admission_scores",
        fake_query_admission_scores,
    )

    node = create_sql_query_node()
    result = _run_node(
        node,
        {
            "query": "广东和浙江 2023 到 2024 年录取情况",
            "intent": "admission_policy",
            "sql_plan": {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "admission_scores",
                        "key_values": {
                            "province": ["广东", "浙江"],
                            "year": ["2023", "2024"],
                        },
                        "reason": "compare",
                    }
                ],
                "limit": 6,
                "reason": "need sql",
            },
        },
    )

    assert captured == {
        "provinces": ["广东", "浙江"],
        "years": ["2023", "2024"],
        "limit": 6,
    }
    assert result["structured_results"][0]["province"] == "广东"
    assert result["structured_chunks"][0].metadata["table"] == "admission_scores"


def test_sql_query_node_skips_when_plan_disabled(monkeypatch) -> None:
    called = {"value": False}

    def fake_query_admission_scores(*, provinces=None, years=None, limit=20):
        called["value"] = True
        return []

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_query.query_admission_scores",
        fake_query_admission_scores,
    )

    node = create_sql_query_node()
    result = _run_node(
        node,
        {
            "intent": "admission_policy",
            "sql_plan": {
                "enabled": False,
                "table_plans": [],
                "limit": 6,
                "reason": "skip",
            },
        },
    )

    assert called["value"] is False
    assert result == {"structured_results": [], "structured_chunks": []}


def test_sql_query_node_skips_when_no_supported_table_plan(monkeypatch) -> None:
    called = {"value": False}

    def fake_query_admission_scores(*, provinces=None, years=None, limit=20):
        called["value"] = True
        return []

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_query.query_admission_scores",
        fake_query_admission_scores,
    )

    node = create_sql_query_node()
    result = _run_node(
        node,
        {
            "intent": "admission_policy",
            "sql_plan": {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "other_table",
                        "key_values": {"province": ["广东"], "year": ["2024"]},
                        "reason": "unsupported",
                    }
                ],
                "limit": 6,
                "reason": "skip",
            },
        },
    )

    assert called["value"] is False
    assert result == {"structured_results": [], "structured_chunks": []}
