from __future__ import annotations

import json
import logging
from typing import Any

from ....knowledge import SQLManager
from ...llm import ModelRequestTimeoutError, get_model
from ...prompts.sql_plan_builder import SQL_PLAN_BUILDER_SYSTEM_PROMPT
from ..schemas import RAGState, SQLCandidate, SQLPlan, TablePlan

logger = logging.getLogger(__name__)

_DEFAULT_SQL_LIMIT = 6


def _default_sql_plan(reason: str) -> SQLPlan:
    return {
        "enabled": False,
        "table_plans": [],
        "limit": _DEFAULT_SQL_LIMIT,
        "reason": reason,
    }


def _normalize_list(value: Any) -> list[str]:
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


def _selected_table_meta(selected_tables: list[str]) -> dict[str, Any]:
    manager = SQLManager()
    meta_by_table: dict[str, Any] = {}
    for table_name in selected_tables:
        meta = manager.get_table_meta(table_name)
        if not meta:
            continue
        meta_by_table[table_name] = dict(meta)
    return meta_by_table


def _selected_table_context(table_meta: dict[str, Any]) -> tuple[dict[str, Any], str]:
    context: dict[str, Any] = {}
    for table_name, meta in table_meta.items():
        context[table_name] = {
            "description": str(meta.get("description", "")).strip(),
            "query_key": [
                str(item).strip()
                for item in list(meta.get("query_key") or [])
                if str(item).strip()
            ],
            "columns": {
                str(key): str(value).strip()
                for key, value in dict(meta.get("columns") or {}).items()
                if str(key).strip()
            },
        }
    return context, json.dumps(context, ensure_ascii=False, sort_keys=True)


def _build_key_values(
    *,
    query_keys: list[str],
    raw_key_values: dict[str, Any],
    slots: dict[str, str],
) -> dict[str, list[str]]:
    key_values: dict[str, list[str]] = {}
    for key in query_keys:
        values = _normalize_list(raw_key_values.get(key))
        if not values:
            values = _normalize_list(slots.get(key))
        key_values[key] = values
    return key_values


def _fallback_table_plans(
    selected_tables: list[str],
    table_meta: dict[str, Any],
    slots: dict[str, str],
) -> list[TablePlan]:
    table_plans: list[TablePlan] = []
    for table_name in selected_tables:
        meta = table_meta.get(table_name) or {}
        query_keys = [str(item).strip() for item in list(meta.get("query_key") or []) if str(item).strip()]
        key_values = _build_key_values(
            query_keys=query_keys,
            raw_key_values={},
            slots=slots,
        )
        table_plans.append(
            {
                "table": table_name,
                "key_values": key_values,
                "reason": "根据已选表和已知槽位回退生成",
            }
        )
    return table_plans


def _normalize_table_plans(
    raw_table_plans: Any,
    selected_tables: list[str],
    table_meta: dict[str, Any],
    slots: dict[str, str],
) -> list[TablePlan]:
    normalized: list[TablePlan] = []
    covered_tables: set[str] = set()

    for item in list(raw_table_plans or []):
        if not isinstance(item, dict):
            continue
        table_name = str(item.get("table", "")).strip()
        if not table_name or table_name not in selected_tables:
            continue
        meta = table_meta.get(table_name) or {}
        query_keys = [str(key).strip() for key in list(meta.get("query_key") or []) if str(key).strip()]
        raw_key_values = dict(item.get("key_values") or {})
        key_values = _build_key_values(
            query_keys=query_keys,
            raw_key_values=raw_key_values,
            slots=slots,
        )

        normalized.append(
            {
                "table": table_name,
                "key_values": key_values,
                "reason": str(item.get("reason", "")).strip(),
            }
        )
        covered_tables.add(table_name)

    for table_name in selected_tables:
        if table_name in covered_tables:
            continue
        meta = table_meta.get(table_name) or {}
        query_keys = [str(key).strip() for key in list(meta.get("query_key") or []) if str(key).strip()]
        key_values = _build_key_values(
            query_keys=query_keys,
            raw_key_values={},
            slots=slots,
        )
        normalized.append(
            {
                "table": table_name,
                "key_values": key_values,
                "reason": "根据已选表和已知槽位回退生成",
            }
        )

    return normalized


async def _llm_build_sql_plan(
    *,
    model_id: str,
    query: str,
    intent: str,
    slots: dict[str, str],
    sql_candidate: SQLCandidate,
) -> SQLPlan:
    selected_tables = [str(item).strip() for item in list(sql_candidate.get("selected_tables") or []) if str(item).strip()]
    table_meta = _selected_table_meta(selected_tables)
    _, table_context = _selected_table_context(table_meta)
    model = get_model(model_id)
    user_prompt = "\n".join(
        [
            f"用户问题：{query}",
            f"意图：{intent}",
            f"已知信息：{json.dumps(slots, ensure_ascii=False)}",
            "时间口径提示：正常情况下默认锚点按 2026 理解；今年=[2026]，往年=[2025]，去年=[2025]；涉及“近几年/近两年/近三年”等近年范围时，以 2025 为锚点，例如近两年=[2025, 2024]；如果当前问题没有明确 year，默认输出 [2025, 2024, 2023]。",
            f"SQL 候选表：{json.dumps(selected_tables, ensure_ascii=False)}",
            f"候选表结构：{table_context}",
            "请输出 SQL 查询计划 JSON。",
        ]
    )
    response = await model.ainvoke(
        [("system", SQL_PLAN_BUILDER_SYSTEM_PROMPT), ("user", user_prompt)],
        response_format={"type": "json_object"},
    )
    content = getattr(response, "content", response)
    if isinstance(content, str):
        data = json.loads(content)
    else:
        data = content

    table_plans = _normalize_table_plans(
        data.get("table_plans"),
        selected_tables,
        table_meta,
        slots,
    )
    try:
        limit = int(data.get("limit") or _DEFAULT_SQL_LIMIT)
    except (TypeError, ValueError):
        limit = _DEFAULT_SQL_LIMIT
    if limit <= 0:
        limit = _DEFAULT_SQL_LIMIT

    return {
        "enabled": bool(data.get("enabled")) and bool(table_plans),
        "table_plans": table_plans,
        "limit": limit,
        "reason": str(data.get("reason", "")).strip(),
    }


def create_sql_plan_builder_node(*, model_id: str | None = None):
    async def sql_plan_builder_node(state: RAGState) -> dict[str, SQLPlan]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        slots = dict(state.get("slots") or {})
        sql_candidate: SQLCandidate = state.get("sql_candidate") or {}

        if not bool(sql_candidate.get("enabled")):
            return {"sql_plan": _default_sql_plan("SQL 候选未启用")}

        selected_tables = [
            str(item).strip()
            for item in list(sql_candidate.get("selected_tables") or [])
            if str(item).strip()
        ]
        if not selected_tables:
            return {"sql_plan": _default_sql_plan("没有选中的数据表")}

        active_model = model_id or "planner"
        try:
            sql_plan = await _llm_build_sql_plan(
                model_id=active_model,
                query=query,
                intent=intent,
                slots=slots,
                sql_candidate=sql_candidate,
            )
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            logger.warning(
                "SQLPlanBuilder LLM failed, fallback to selected tables. %s: %s",
                type(exc).__name__,
                exc,
            )
            table_meta = _selected_table_meta(selected_tables)
            sql_plan = {
                "enabled": True,
                "table_plans": _fallback_table_plans(
                    selected_tables,
                    table_meta,
                    slots,
                ),
                "limit": _DEFAULT_SQL_LIMIT,
                "reason": "根据已选表和已知槽位回退生成",
            }

        logger.debug(
            "SQLPlanBuilder done.\n"
            f"selected_tables={selected_tables}\n"
            f"enabled={sql_plan.get('enabled')}\n"
            f"table_plans={len(sql_plan.get('table_plans') or [])}\n"
            f"limit={sql_plan.get('limit')}"
        )
        return {"sql_plan": sql_plan}

    return sql_plan_builder_node
