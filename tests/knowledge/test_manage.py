from __future__ import annotations

from src.knowledge.manage import run_query_admission_scores


def test_run_query_admission_scores_adapts_single_values_to_list_signature(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_query_admission_scores(*, provinces=None, years=None, limit=20):
        captured["provinces"] = provinces
        captured["years"] = years
        captured["limit"] = limit
        return [{"province": "广东", "year": 2024}]

    monkeypatch.setattr(
        "src.knowledge.sql_queries.query_admission_scores",
        fake_query_admission_scores,
    )

    rows = run_query_admission_scores(province="广东", year=2024, limit=6)

    assert rows == [{"province": "广东", "year": 2024}]
    assert captured == {
        "provinces": ["广东"],
        "years": [2024],
        "limit": 6,
    }


def test_run_query_admission_scores_keeps_omitted_filters_empty(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_query_admission_scores(*, provinces=None, years=None, limit=20):
        captured["provinces"] = provinces
        captured["years"] = years
        captured["limit"] = limit
        return []

    monkeypatch.setattr(
        "src.knowledge.sql_queries.query_admission_scores",
        fake_query_admission_scores,
    )

    run_query_admission_scores(province=None, year=None, limit=4)

    assert captured == {
        "provinces": [],
        "years": [],
        "limit": 4,
    }
