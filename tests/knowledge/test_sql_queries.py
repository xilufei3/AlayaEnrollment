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


def test_query_admission_scores_extracts_years_from_free_text(monkeypatch) -> None:
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

    query_admission_scores(
        provinces=["广东"],
        years=["2023到2024年", "近几年", "2024"],
        limit=5,
    )

    assert "year IN" in str(captured["sql"])
    assert captured["params"] == {
        "province_0": "广东",
        "year_0": 2023,
        "year_1": 2024,
        "limit": 5,
    }


def test_query_admission_scores_ignores_unparseable_year_text(monkeypatch) -> None:
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

    query_admission_scores(
        provinces=["广东"],
        years=["近几年", "最近几年", "近4年"],
        limit=3,
    )

    assert "year IN" not in str(captured["sql"])
    assert captured["params"] == {
        "province_0": "广东",
        "limit": 3,
    }


def test_query_admission_scores_derives_2025_admission_count_from_sub_counts(monkeypatch) -> None:
    class DummySQLManager:
        def execute(self, sql, db_id="main_db", params=None):
            return [
                {
                    "province": "广东",
                    "year": 2025,
                    "admission_count": None,
                    "regular_batch_count": "22",
                    "joint_program_count": "16",
                    "physics_review_count": "282",
                    "kcl_count": "18",
                }
            ]

    monkeypatch.setattr(
        "src.knowledge.sql_queries.SQLManager",
        lambda: DummySQLManager(),
    )

    rows = query_admission_scores(provinces=["广东"], years=[2025], limit=4)

    assert rows[0]["admission_count"] == "338"


def test_query_admission_scores_does_not_bind_admission_count_to_physics_review_count(monkeypatch) -> None:
    class DummySQLManager:
        def execute(self, sql, db_id="main_db", params=None):
            return [
                {
                    "province": "广东",
                    "year": 2024,
                    "admission_count": None,
                    "regular_batch_count": None,
                    "joint_program_count": None,
                    "physics_review_count": "303",
                    "kcl_count": "20",
                }
            ]

    monkeypatch.setattr(
        "src.knowledge.sql_queries.SQLManager",
        lambda: DummySQLManager(),
    )

    rows = query_admission_scores(provinces=["广东"], years=[2024], limit=4)

    assert rows[0]["admission_count"] is None
