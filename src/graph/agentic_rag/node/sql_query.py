from __future__ import annotations

import asyncio
import logging
import time
from typing import Any

from ....knowledge import SQLManager, query_admission_scores
from ...structured_results import StructuredTableResult, build_structured_table_result
from ..schemas import RAGState, SQLPlan, TablePlan

logger = logging.getLogger(__name__)

_DEFAULT_SQL_LIMIT = 6


def _record_sql(duration: float, success: bool) -> None:
    try:
        from ....api.observability import record_sql_query

        record_sql_query(duration_seconds=duration, success=success)
    except Exception:
        pass


def _normalize_text_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, list):
        items = value
    else:
        items = [value]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _find_table_plan(sql_plan: SQLPlan, table_name: str) -> TablePlan | None:
    for item in list(sql_plan.get("table_plans") or []):
        if not isinstance(item, dict):
            continue
        current_table = str(item.get("table") or "").strip()
        if current_table == table_name:
            return item
    return None


def _build_structured_results(
    *,
    table_name: str,
    rows: list[dict[str, Any]],
) -> list[StructuredTableResult]:
    if not rows:
        return []

    meta = SQLManager().get_table_meta(table_name) or {}
    result = build_structured_table_result(
        table=table_name,
        description=str(meta.get("description") or "").strip(),
        query_key=list(meta.get("query_key") or []),
        columns=dict(meta.get("columns") or {}),
        items=rows,
    )
    return [result]


def create_sql_query_node():
    async def sql_query_node(state: RAGState) -> dict[str, Any]:
        sql_plan: SQLPlan = state.get("sql_plan") or {}
        if not bool(sql_plan.get("enabled")):
            return {"structured_results": []}

        table_plan = _find_table_plan(sql_plan, "admission_scores")
        if table_plan is None:
            return {"structured_results": []}

        key_values = dict(table_plan.get("key_values") or {})
        provinces = _normalize_text_list(key_values.get("province"))
        years = _normalize_text_list(key_values.get("year"))

        try:
            limit = int(sql_plan.get("limit") or _DEFAULT_SQL_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_SQL_LIMIT
        if limit <= 0:
            limit = _DEFAULT_SQL_LIMIT

        try:
            start = time.monotonic()
            rows = await asyncio.to_thread(
                lambda: query_admission_scores(
                    provinces=provinces,
                    years=years,
                    limit=limit,
                )
            )
            _record_sql(time.monotonic() - start, True)
        except Exception as exc:
            _record_sql(time.monotonic() - start, False)
            logger.error("SQL query error %s: %s", type(exc).__name__, exc)
            return {"structured_results": []}

        return {
            "structured_results": _build_structured_results(
                table_name="admission_scores",
                rows=rows,
            )
        }

    return sql_query_node
