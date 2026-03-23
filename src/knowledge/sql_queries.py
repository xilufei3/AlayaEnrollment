from __future__ import annotations

from typing import Any

from .sql_manager import SQLManager


def _normalize_text_list(values: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()
    for item in values or []:
        text = str(item).strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _normalize_year_list(values: list[int | str] | None) -> list[int]:
    normalized: list[int] = []
    seen: set[int] = set()
    for item in values or []:
        text = str(item).strip()
        if not text:
            continue
        year = int(text)
        if year in seen:
            continue
        normalized.append(year)
        seen.add(year)
    return normalized


def _province_clause(provinces: list[str], params: dict[str, Any]) -> str:
    if not provinces:
        return ""

    conditions: list[str] = []
    for index, province in enumerate(provinces):
        key = f"province_{index}"
        params[key] = province
        conditions.append(
            f"(province LIKE '%' || :{key} || '%' OR :{key} LIKE '%' || province || '%')"
        )
    return "(" + " OR ".join(conditions) + ")"


def _year_clause(years: list[int], params: dict[str, Any]) -> str:
    if not years:
        return ""

    placeholders: list[str] = []
    for index, year in enumerate(years):
        key = f"year_{index}"
        params[key] = year
        placeholders.append(f":{key}")
    return "year IN (" + ", ".join(placeholders) + ")"


def query_admission_scores(
    *,
    provinces: list[str] | None = None,
    years: list[int | str] | None = None,
    limit: int = 20,
) -> list[dict]:
    normalized_provinces = _normalize_text_list(provinces)
    normalized_years = _normalize_year_list(years)

    params: dict[str, Any] = {"limit": limit}
    where_clauses = ["1=1"]

    province_clause = _province_clause(normalized_provinces, params)
    if province_clause:
        where_clauses.append(province_clause)

    year_clause = _year_clause(normalized_years, params)
    if year_clause:
        where_clauses.append(year_clause)

    sql = f"""
    SELECT *
    FROM admission_scores
    WHERE {' AND '.join(where_clauses)}
    LIMIT CAST(:limit AS INTEGER)
    """
    return SQLManager().execute(sql, params=params)
