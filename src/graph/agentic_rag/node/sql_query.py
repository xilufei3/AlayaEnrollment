from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.documents import Document

from ....knowledge import query_admission_scores
from ..schemas import RAGState, SQLPlan

logger = logging.getLogger(__name__)

_DEFAULT_SQL_LIMIT = 6


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


def create_sql_query_node():
    def sql_query_node(state: RAGState) -> dict[str, Any]:
        intent = str(state.get("intent") or "").strip()
        if intent != "admission_policy":
            return {"structured_results": [], "structured_chunks": []}

        sql_plan: SQLPlan = state.get("sql_plan") or {}
        if not bool(sql_plan.get("enabled")):
            return {"structured_results": [], "structured_chunks": []}

        slots = dict(state.get("slots") or {})
        province = _optional_text(sql_plan.get("province")) or _optional_text(slots.get("province"))
        year = _optional_text(sql_plan.get("year")) or _optional_text(slots.get("year"))

        try:
            limit = int(sql_plan.get("limit") or _DEFAULT_SQL_LIMIT)
        except (TypeError, ValueError):
            limit = _DEFAULT_SQL_LIMIT
        if limit <= 0:
            limit = _DEFAULT_SQL_LIMIT

        try:
            rows = query_admission_scores(province=province, year=year, limit=limit)
        except Exception as exc:
            logger.error(f"SQL query error {type(exc).__name__}: {exc}")
            return {"structured_results": [], "structured_chunks": []}

        docs = [_row_to_document(row=row, index=i) for i, row in enumerate(rows, start=1)]
        return {
            "structured_results": rows,
            "structured_chunks": docs,
        }

    return sql_query_node
