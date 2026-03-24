from __future__ import annotations

import asyncio
from typing import Any

from src.graph.agentic_rag.node.search_planner import create_search_planner_node


def _run_node(node, state: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(node(state))


def test_search_planner_includes_sql_registry_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            captured["messages"] = messages
            captured["response_format"] = response_format
            return {
                "rewritten_query": "广东 2024 录取分数",
                "reason": "ok",
                "sql_candidate": {
                    "enabled": True,
                    "selected_tables": ["admission_scores"],
                    "reason": "分数数据查询",
                },
            }

    class DummySQLManager:
        def get_all_table_meta(self) -> dict[str, Any]:
            return {
                "admission_scores": {
                    "description": "各省各年份录取分数数据",
                    "use_when": ["查询某省某年的录取分数", "查询近几年录取情况"],
                    "query_key": ["province", "year"],
                    "columns": {
                        "province": "省份名称",
                        "year": "年份",
                        "min_score": "最低分",
                    },
                }
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.search_planner.get_model",
        lambda _model_id: DummyModel(),
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.node.search_planner.SQLManager",
        lambda: DummySQLManager(),
    )

    node = create_search_planner_node(model_id="planner")
    result = _run_node(
        node,
        {
            "query": "广东 2024 录取分数",
            "intent": "admission_policy",
            "slots": {"province": "广东", "year": "2024"},
            "rag_iteration": 0,
            "eval_reason": "",
            "chunks": [],
        },
    )

    user_message = captured["messages"][1][1]

    assert "admission_scores" in user_message
    assert '"query_key": ["province", "year"]' in user_message
    assert "min_score" in user_message
    assert captured["response_format"] == {"type": "json_object"}
    assert result["search_plan"]["vector_query"] == "广东 2024 录取分数"
    assert result["sql_candidate"]["enabled"] is True
    assert result["sql_candidate"]["selected_tables"] == ["admission_scores"]


def test_search_planner_disables_sql_for_rule_question(monkeypatch) -> None:
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "rewritten_query": "综合评价 631 规则 含义",
                "reason": "ok",
                "sql_candidate": {
                    "enabled": False,
                    "selected_tables": [],
                    "reason": "规则解释问题",
                },
            }

    class DummySQLManager:
        def get_all_table_meta(self) -> dict[str, Any]:
            return {
                "admission_scores": {
                    "description": "各省各年份录取分数数据",
                    "use_when": ["查询某省某年的录取分数", "查询近几年录取情况"],
                    "query_key": ["province", "year"],
                    "columns": {
                        "province": "省份名称",
                        "year": "年份",
                    },
                }
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.search_planner.get_model",
        lambda _model_id: DummyModel(),
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.node.search_planner.SQLManager",
        lambda: DummySQLManager(),
    )

    node = create_search_planner_node(model_id="planner")
    result = _run_node(
        node,
        {
            "query": "631 是什么意思",
            "intent": "admission_policy",
            "slots": {},
            "rag_iteration": 0,
            "eval_reason": "",
            "chunks": [],
        },
    )

    assert result["sql_candidate"]["enabled"] is False
    assert result["sql_candidate"]["selected_tables"] == []


def test_search_planner_passes_previous_eval_reason_as_retry_context(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            captured["messages"] = messages
            return {
                "rewritten_query": "广东 近年 录取分数 位次 招生人数",
                "reason": "补充更多角度",
                "sql_candidate": {
                    "enabled": True,
                    "selected_tables": ["admission_scores"],
                    "reason": "录取数据查询",
                },
            }

    class DummySQLManager:
        def get_all_table_meta(self) -> dict[str, Any]:
            return {
                "admission_scores": {
                    "description": "各省各年份录取分数数据",
                    "use_when": ["查询某省某年的录取分数", "查询近几年录取情况"],
                    "query_key": ["province", "year"],
                    "columns": {
                        "province": "省份名称",
                        "year": "年份",
                    },
                }
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.search_planner.get_model",
        lambda _model_id: DummyModel(),
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.node.search_planner.SQLManager",
        lambda: DummySQLManager(),
    )

    node = create_search_planner_node(model_id="planner")
    _run_node(
        node,
        {
            "query": "广东近几年录取情况怎么样",
            "intent": "admission_policy",
            "query_mode": "factual_query",
            "slots": {"province": "广东", "year": "近几年"},
            "rag_iteration": 1,
            "eval_reason": "当前问题属于介绍型/事实查询，默认补充一轮检索以扩展覆盖角度；本轮已覆盖要点：1. 2025 录取人数；2. 最低分位次",
            "chunks": [],
        },
    )

    user_message = captured["messages"][1][1]
    assert "上一轮评估理由（可能包含已覆盖要点，请据此补充未覆盖角度）" in user_message
    assert "本轮已覆盖要点" in user_message
