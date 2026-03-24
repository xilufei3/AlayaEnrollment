from __future__ import annotations

import re
from typing import Any

from .sql_manager import SQLManager

_YEAR_PATTERN = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_INTEGER_PATTERN = re.compile(r"-?\d+")


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
        candidates: list[int] = []
        if isinstance(item, int) and not isinstance(item, bool):
            candidates = [item]
        else:
            text = str(item).strip()
            if not text:
                continue
            if text.isdigit():
                candidates = [int(text)]
            else:
                candidates = [int(match) for match in _YEAR_PATTERN.findall(text)]

        for year in candidates:
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


def _to_int_or_zero(value: Any) -> int:
    if value is None:
        return 0
    if isinstance(value, int) and not isinstance(value, bool):
        return value

    text = str(value).strip()
    if not text:
        return 0
    match = _INTEGER_PATTERN.search(text.replace(",", ""))
    if not match:
        return 0
    try:
        return int(match.group(0))
    except ValueError:
        return 0


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
    ORDER BY year DESC
    LIMIT CAST(:limit AS INTEGER)
    """

    rows = SQLManager().execute(sql, params=params)

    # For 2025 rows, admission_count may be omitted in the source sheet. In that
    # case we derive it from the four disclosed sub-counts, treating blanks as 0.
    for row in rows:
        if str(row.get("admission_count") or "").strip():
            continue
        if row.get("year") != 2025:
            continue

        total = (
            _to_int_or_zero(row.get("regular_batch_count"))
            + _to_int_or_zero(row.get("joint_program_count"))
            + _to_int_or_zero(row.get("physics_review_count"))
            + _to_int_or_zero(row.get("kcl_count"))
        )
        row["admission_count"] = str(total)

    return rows
