from __future__ import annotations

import asyncio
from typing import Any

from src.graph.agentic_rag.node.sql_plan_builder import create_sql_plan_builder_node


def _run_node(node, state: dict[str, Any]) -> dict[str, Any]:
    return asyncio.run(node(state))


def test_sql_plan_builder_extracts_multiple_provinces_and_years(monkeypatch) -> None:
    captured: dict[str, Any] = {}

    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            captured["messages"] = messages
            captured["response_format"] = response_format
            return {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "admission_scores",
                        "key_values": {
                            "province": ["广东", "浙江"],
                            "year": ["2022", "2023", "2024"],
                        },
                        "reason": "compare",
                    }
                ],
                "limit": 6,
                "reason": "ok",
            }

    class DummySQLManager:
        def get_table_meta(self, table_name: str) -> dict[str, Any] | None:
            if table_name != "admission_scores":
                return None
            return {
                "db_id": "main_db",
                "physical_name": "admission_scores",
                "description": "各省各年份录取分数数据",
                "query_key": ["province", "year"],
                "columns": {
                    "province": "省份名称",
                    "year": "年份",
                    "min_score": "最低分",
                },
            }

        def execute(self, sql, db_id="main_db", params=None):
            return [{"max_year": 2025}]

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_plan_builder.get_model",
        lambda _model_id: DummyModel(),
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_plan_builder.SQLManager",
        lambda: DummySQLManager(),
    )

    node = create_sql_plan_builder_node(model_id="planner")
    result = _run_node(
        node,
        {
            "query": "广东和浙江 2022 到 2024 年录取情况",
            "intent": "admission_policy",
            "slots": {},
            "sql_candidate": {
                "enabled": True,
                "selected_tables": ["admission_scores"],
                "reason": "score data",
            },
        },
    )

    user_message = captured["messages"][1][1]

    assert "admission_scores" in user_message
    assert '"query_key": ["province", "year"]' in user_message
    assert "默认锚点按 2026 理解" in user_message
    assert "近两年=[2025, 2024]" in user_message
    assert result["sql_plan"]["enabled"] is True
    assert result["sql_plan"]["table_plans"][0]["key_values"]["province"] == ["广东", "浙江"]
    assert result["sql_plan"]["table_plans"][0]["key_values"]["year"] == ["2022", "2023", "2024"]


def test_sql_plan_builder_accepts_llm_generated_recent_years(monkeypatch) -> None:
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "admission_scores",
                        "key_values": {
                            "province": ["广东"],
                            "year": ["2025", "2024", "2023", "2022"],
                        },
                        "reason": "recent years",
                    }
                ],
                "limit": 6,
                "reason": "ok",
            }

    class DummySQLManager:
        def get_table_meta(self, table_name: str) -> dict[str, Any] | None:
            if table_name != "admission_scores":
                return None
            return {
                "db_id": "main_db",
                "physical_name": "admission_scores",
                "description": "各省各年份录取分数数据",
                "query_key": ["province", "year"],
                "columns": {
                    "province": "省份名称",
                    "year": "年份",
                },
            }

        def execute(self, sql, db_id="main_db", params=None):
            return [{"max_year": 2025}]

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_plan_builder.get_model",
        lambda _model_id: DummyModel(),
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_plan_builder.SQLManager",
        lambda: DummySQLManager(),
    )

    node = create_sql_plan_builder_node(model_id="planner")
    result = _run_node(
        node,
        {
            "query": "广东近几年录取情况",
            "intent": "admission_policy",
            "slots": {"province": "广东", "year": "近几年"},
            "sql_candidate": {
                "enabled": True,
                "selected_tables": ["admission_scores"],
                "reason": "score data",
            },
        },
    )

    assert result["sql_plan"]["table_plans"][0]["key_values"]["province"] == ["广东"]
    assert result["sql_plan"]["table_plans"][0]["key_values"]["year"] == ["2025", "2024", "2023", "2022"]


def test_sql_plan_builder_accepts_llm_generated_previous_year(monkeypatch) -> None:
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "admission_scores",
                        "key_values": {
                            "province": ["广东"],
                            "year": ["往年"],
                        },
                        "reason": "previous year",
                    }
                ],
                "limit": 6,
                "reason": "ok",
            }

    class DummySQLManager:
        def get_table_meta(self, table_name: str) -> dict[str, Any] | None:
            if table_name != "admission_scores":
                return None
            return {
                "db_id": "main_db",
                "physical_name": "admission_scores",
                "description": "各省各年份录取分数数据",
                "query_key": ["province", "year"],
                "columns": {
                    "province": "省份名称",
                    "year": "年份",
                },
            }

        def execute(self, sql, db_id="main_db", params=None):
            return [{"max_year": 2025}]

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_plan_builder.get_model",
        lambda _model_id: DummyModel(),
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_plan_builder.SQLManager",
        lambda: DummySQLManager(),
    )

    node = create_sql_plan_builder_node(model_id="planner")
    result = _run_node(
        node,
        {
            "query": "广东往年录取情况",
            "intent": "admission_policy",
            "slots": {"province": "广东", "year": "往年"},
            "sql_candidate": {
                "enabled": True,
                "selected_tables": ["admission_scores"],
                "reason": "score data",
            },
        },
    )

    assert result["sql_plan"]["table_plans"][0]["key_values"]["year"] == ["2024"]


def test_sql_plan_builder_accepts_llm_generated_default_recent_three_years(monkeypatch) -> None:
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "admission_scores",
                        "key_values": {
                            "province": ["广东"],
                            "year": ["2025", "2024", "2023"],
                        },
                        "reason": "year omitted",
                    }
                ],
                "limit": 6,
                "reason": "ok",
            }

    class DummySQLManager:
        def get_table_meta(self, table_name: str) -> dict[str, Any] | None:
            if table_name != "admission_scores":
                return None
            return {
                "db_id": "main_db",
                "physical_name": "admission_scores",
                "description": "各省各年份录取分数数据",
                "query_key": ["province", "year"],
                "columns": {
                    "province": "省份名称",
                    "year": "年份",
                },
            }

        def execute(self, sql, db_id="main_db", params=None):
            return [{"max_year": 2025}]

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_plan_builder.get_model",
        lambda _model_id: DummyModel(),
    )
    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_plan_builder.SQLManager",
        lambda: DummySQLManager(),
    )

    node = create_sql_plan_builder_node(model_id="planner")
    result = _run_node(
        node,
        {
            "query": "广东录取情况怎么样",
            "intent": "admission_policy",
            "slots": {"province": "广东"},
            "sql_candidate": {
                "enabled": True,
                "selected_tables": ["admission_scores"],
                "reason": "score data",
            },
        },
    )

    assert result["sql_plan"]["table_plans"][0]["key_values"]["province"] == ["广东"]
    assert result["sql_plan"]["table_plans"][0]["key_values"]["year"] == ["2025", "2024", "2023"]


def test_sql_plan_builder_skips_when_candidate_disabled() -> None:
    node = create_sql_plan_builder_node(model_id="planner")
    result = _run_node(
        node,
        {
            "query": "631 是什么意思",
            "intent": "admission_policy",
            "slots": {},
            "sql_candidate": {
                "enabled": False,
                "selected_tables": [],
                "reason": "rule question",
            },
        },
    )

    assert result == {
        "sql_plan": {
            "enabled": False,
            "table_plans": [],
            "limit": 6,
            "reason": "sql_candidate disabled",
        }
    }
