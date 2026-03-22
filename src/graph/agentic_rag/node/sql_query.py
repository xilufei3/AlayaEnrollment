from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import Any

from langchain_core.documents import Document

from ....knowledge import query_admission_scores
from ...utils import query_prefers_year_range as shared_query_prefers_year_range
from ..schemas import RAGState, SQLPlan

logger = logging.getLogger(__name__)


def _record_sql(duration: float, success: bool) -> None:
    try:
        from ....api.observability import record_sql_query
        record_sql_query(duration_seconds=duration, success=success)
    except Exception:
        pass

_DEFAULT_SQL_LIMIT = 6
_YEAR_RANGE_HINTS: tuple[str, ...] = (
    "近几年",
    "近年来",
    "历年",
    "往年",
    "最近几年",
)


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _row_to_document(row: dict[str, Any], index: int) -> Document:
    return Document(
        page_content=json.dumps(row, ensure_ascii=False),
        metadata={
            "source": "sql",
            "table": "admission_scores",
            "row_index": index,
        },
    )


def _query_prefers_year_range(query: str) -> bool:
    return shared_query_prefers_year_range(query)


def create_sql_query_node():
    async def sql_query_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        if intent != "admission_policy":
            return {"structured_results": [], "structured_chunks": []}

        sql_plan: SQLPlan = state.get("sql_plan") or {}
        if not bool(sql_plan.get("enabled")):
            return {"structured_results": [], "structured_chunks": []}

        slots = dict(state.get("slots") or {})
        province = _optional_text(sql_plan.get("province")) or _optional_text(slots.get("province"))
        slot_year = _optional_text(slots.get("year"))
        if _query_prefers_year_range(query):
            slot_year = None
        year = _optional_text(sql_plan.get("year")) or slot_year

        try:
            limit = int(sql_plan.get("limit") or _DEFAULT_SQL_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_SQL_LIMIT
        if limit <= 0:
            limit = _DEFAULT_SQL_LIMIT

        try:
            start = time.monotonic()
            rows = await asyncio.to_thread(
                lambda: query_admission_scores(province=province, year=year, limit=limit)
            )
            _record_sql(time.monotonic() - start, True)
        except Exception as exc:
            _record_sql(time.monotonic() - start, False)
            logger.error(f"SQL query error {type(exc).__name__}: {exc}")
            return {"structured_results": [], "structured_chunks": []}

        docs = [_row_to_document(row=row, index=i) for i, row in enumerate(rows, start=1)]
        return {
            "structured_results": rows,
            "structured_chunks": docs,
        }

    return sql_query_node
