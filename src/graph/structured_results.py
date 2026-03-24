from __future__ import annotations

import json
from typing import Any, Sequence, TypedDict


class StructuredTableResult(TypedDict, total=False):
    table: str
    description: str
    query_key: list[str]
    columns: dict[str, str]
    items: list[dict[str, Any]]


def _normalize_string_list(values: Any) -> list[str]:
    if values is None:
        items: list[Any] = []
    elif isinstance(values, (str, bytes)):
        items = [values]
    else:
        try:
            items = list(values)
        except TypeError:
            items = [values]

    normalized: list[str] = []
    seen: set[str] = set()
    for item in items:
        text = str(item).strip()
        if not text or text in seen:
            continue
        normalized.append(text)
        seen.add(text)
    return normalized


def _normalize_columns(columns: Any) -> dict[str, str]:
    normalized: dict[str, str] = {}
    for key, value in dict(columns or {}).items():
        column_name = str(key).strip()
        if not column_name:
            continue
        normalized[column_name] = str(value).strip()
    return normalized


def _normalize_items(items: Any) -> list[dict[str, Any]]:
    if items is None:
        raw_items: list[Any] = []
    elif isinstance(items, dict):
        raw_items = [items]
    else:
        try:
            raw_items = list(items)
        except TypeError:
            raw_items = [items]

    normalized: list[dict[str, Any]] = []
    for item in raw_items:
        if isinstance(item, dict):
            normalized.append(dict(item))
    return normalized


def build_structured_table_result(
    *,
    table: str,
    description: str = "",
    query_key: Sequence[str] | None = None,
    columns: dict[str, Any] | None = None,
    items: Sequence[dict[str, Any]] | None = None,
) -> StructuredTableResult:
    return {
        "table": str(table).strip(),
        "description": str(description).strip(),
        "query_key": _normalize_string_list(query_key),
        "columns": _normalize_columns(columns),
        "items": _normalize_items(items),
    }


def _looks_like_structured_table_result(item: Any) -> bool:
    if not isinstance(item, dict):
        return False
    keys = set(item.keys())
    return bool(keys & {"table", "description", "query_key", "columns", "items"})


def format_structured_results_for_prompt(
    results: Sequence[dict[str, Any]],
    *,
    max_tables: int = 3,
    max_items_per_table: int = 12,
    max_chars: int | None = None,
) -> str:
    sections: list[str] = []
    total_chars = 0

    for index, entry in enumerate(list(results)[:max_tables], start=1):
        if not isinstance(entry, dict):
            continue

        if not _looks_like_structured_table_result(entry):
            section = f"【SQL 结果 {index}】{json.dumps(entry, ensure_ascii=False)}"
        else:
            payload = build_structured_table_result(
                table=str(entry.get("table") or "").strip(),
                description=str(entry.get("description") or "").strip(),
                query_key=list(entry.get("query_key") or []),
                columns=dict(entry.get("columns") or {}),
                items=list(entry.get("items") or []),
            )
            items = list(payload.get("items") or [])
            section_lines = [f"【SQL 表 {index}】{payload.get('table') or '未命名表'}"]
            description = str(payload.get("description") or "").strip()
            if description:
                section_lines.append(f"表说明：{description}")
            query_key = list(payload.get("query_key") or [])
            if query_key:
                section_lines.append(f"查询键：{json.dumps(query_key, ensure_ascii=False)}")
            columns = dict(payload.get("columns") or {})
            if columns:
                section_lines.append(
                    f"字段说明：{json.dumps(columns, ensure_ascii=False)}"
                )
            if items:
                section_lines.append("结果条目：")
                for item_index, item in enumerate(items[:max_items_per_table], start=1):
                    section_lines.append(
                        f"[{item_index}] {json.dumps(item, ensure_ascii=False)}"
                    )
            else:
                section_lines.append("结果条目：[]")
            section = "\n".join(section_lines)

        if max_chars is not None and sections and total_chars + len(section) > max_chars:
            break
        sections.append(section)
        total_chars += len(section)
        if max_chars is not None and total_chars >= max_chars:
            break

    return "\n\n".join(sections)
