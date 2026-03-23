from __future__ import annotations

from src.knowledge.sql_queries import query_admission_scores


def test_query_admission_scores_builds_multi_value_filters(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummySQLManager:
        def execute(self, sql, db_id="main_db", params=None):
            captured["sql"] = sql
            captured["db_id"] = db_id
            captured["params"] = params or {}
            return [{"province": "广东", "year": 2024}]

    monkeypatch.setattr(
        "src.knowledge.sql_queries.SQLManager",
        lambda: DummySQLManager(),
    )

    rows = query_admission_scores(
        provinces=["广东", "浙江"],
        years=["2023", "2024"],
        limit=6,
    )

    assert rows == [{"province": "广东", "year": 2024}]
    assert "province" in str(captured["sql"])
    assert "year IN" in str(captured["sql"])
    assert captured["params"] == {
        "province_0": "广东",
        "province_1": "浙江",
        "year_0": 2023,
        "year_1": 2024,
        "limit": 6,
    }


def test_query_admission_scores_skips_filters_for_empty_lists(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class DummySQLManager:
        def execute(self, sql, db_id="main_db", params=None):
            captured["sql"] = sql
            captured["db_id"] = db_id
            captured["params"] = params or {}
            return []

    monkeypatch.setattr(
        "src.knowledge.sql_queries.SQLManager",
        lambda: DummySQLManager(),
    )

    query_admission_scores(provinces=[], years=[], limit=4)

    assert "year IN" not in str(captured["sql"])
    assert "province LIKE" not in str(captured["sql"])
    assert captured["params"] == {"limit": 4}
