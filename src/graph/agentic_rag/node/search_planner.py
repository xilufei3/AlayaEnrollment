from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ....knowledge import SQLManager
from ...llm import ModelRequestTimeoutError, get_model
from ...prompts.search_planner import SEARCH_PLANNER_SYSTEM_PROMPT
from ...utils import chunk_texts as shared_chunk_texts
from ..schemas import RAGState, SQLCandidate, SQLPlan, SearchPlan

logger = logging.getLogger(__name__)

_INTENT_TOP_K: dict[str, int] = {
    "admission_policy": 10,
    "school_overview": 6,
    "major_and_training": 8,
    "career_and_development": 6,
    "campus_life": 6,
}
_DEFAULT_TOP_K = 8
_DEFAULT_SQL_LIMIT = 6


class SearchPlanLLMOutput(BaseModel):
    rewritten_query: str = Field(default="", description="改写后的主检索查询")
    reason: str = Field(default="", description="规划理由")
    sql_candidate: dict[str, Any] = Field(default_factory=dict, description="SQL 路由候选结果")


def _get_top_k(intent: str, iteration: int) -> int:
    top_k = _INTENT_TOP_K.get(intent, _DEFAULT_TOP_K)
    if iteration >= 1:
        top_k = min(top_k + 4, 16)
    return top_k


def _build_plan_rule(
    intent: str,
    iteration: int,
    eval_reason: str,
    query: str,
) -> SearchPlan:
    top_k = _get_top_k(intent, iteration)

    if iteration > 0:
        logger.debug(
            "SearchPlanner rule retry.\n"
            f"iteration={iteration}\n"
            f"eval_reason={eval_reason}\n"
            f"top_k={top_k}"
        )

    return {
        "strategy": "vector_keyword_hybrid",
        "vector_query": query.strip(),
        "top_k": top_k,
    }


def _default_sql_candidate() -> SQLCandidate:
    return {
        "enabled": False,
        "selected_tables": [],
        "reason": "默认不启用 SQL",
    }


def _default_sql_plan() -> SQLPlan:
    return {
        "enabled": False,
        "table_plans": [],
        "limit": _DEFAULT_SQL_LIMIT,
        "reason": "尚未执行 SQL 查询计划构建",
    }


def _chunk_texts(chunks: list[Any]) -> list[str]:
    return shared_chunk_texts(chunks)


def _build_sql_registry_context() -> str:
    try:
        tables = SQLManager().get_all_table_meta()
    except Exception as exc:
        logger.warning("SearchPlanner: failed to load SQL registry context. %s", exc)
        return "{}"

    summary: dict[str, Any] = {}
    for table_name, meta in tables.items():
        columns = dict(meta.get("columns") or {})
        summary[table_name] = {
            "description": str(meta.get("description", "")).strip(),
            "use_when": [
                str(item).strip()
                for item in list(meta.get("use_when") or [])
                if str(item).strip()
            ],
            "query_key": [
                str(item).strip()
                for item in list(meta.get("query_key") or [])
                if str(item).strip()
            ],
            "columns": {
                str(key): str(value).strip()
                for key, value in columns.items()
                if str(key).strip()
            },
        }
    return json.dumps(summary, ensure_ascii=False, sort_keys=True)


def _normalize_sql_candidate(data: Any) -> SQLCandidate:
    if not isinstance(data, dict):
        return _default_sql_candidate()

    selected_tables: list[str] = []
    for item in list(data.get("selected_tables") or []):
        table_name = str(item).strip()
        if table_name:
            selected_tables.append(table_name)

    enabled = bool(data.get("enabled")) and bool(selected_tables)
    return {
        "enabled": enabled,
        "selected_tables": selected_tables,
        "reason": str(data.get("reason", "")).strip(),
    }


async def _llm_plan(
    model_id: str,
    query: str,
    intent: str,
    query_mode: str,
    slots: dict[str, str],
    iteration: int,
    eval_reason: str,
    chunks: list[Any] | None = None,
) -> tuple[SearchPlan, SQLCandidate]:
    model = get_model(model_id)
    user_parts = [
        f"用户问题：{query}",
        f"意图：{intent}",
        f"问题形态：{query_mode}",
        f"已知信息：{json.dumps(slots, ensure_ascii=False)}",
        f"当前检索轮次：{iteration}",
        f"SQL 表能力摘要：{_build_sql_registry_context()}",
    ]
    if eval_reason.strip():
        user_parts.append(f"上一轮评估理由（可能包含已覆盖要点，请据此补充未覆盖角度）：{eval_reason.strip()}")
    chunk_texts = _chunk_texts(list(chunks or []))
    if chunk_texts:
        user_parts.append("上一轮召回片段原文：\n" + "\n".join(chunk_texts))
    user_parts.append("请输出检索参数 JSON。")
    user_prompt = "\n".join(user_parts)

    response = await model.ainvoke(
        [("system", SEARCH_PLANNER_SYSTEM_PROMPT), ("user", user_prompt)],
        response_format={"type": "json_object"},
    )
    content = getattr(response, "content", response)
    if isinstance(content, str):
        try:
            data = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            logger.warning(
                "SearchPlanner: LLM returned invalid JSON, using fallback. content=%s",
                content[:200],
            )
            data = {}
    else:
        data = content

    out = SearchPlanLLMOutput(
        rewritten_query=str(data.get("rewritten_query", query)).strip() or query,
        reason=str(data.get("reason", "")).strip(),
        sql_candidate=dict(data.get("sql_candidate") or {}),
    )
    top_k_final = _get_top_k(intent, iteration)

    plan: SearchPlan = {
        "strategy": "vector_keyword_hybrid",
        "vector_query": out.rewritten_query,
        "top_k": top_k_final,
    }
    sql_candidate = _normalize_sql_candidate(out.sql_candidate)
    logger.debug(
        "SearchPlanner LLM done.\n"
        f"rewritten_query={out.rewritten_query[:60]}...\n"
        f"top_k={top_k_final}\n"
        f"reason={out.reason}\n"
        f"sql_candidate={sql_candidate}"
    )
    return plan, sql_candidate


def create_search_planner_node(*, model_id: str | None = None):
    async def search_planner_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        query_mode = str(state.get("query_mode") or "").strip()
        slots = dict(state.get("slots") or {})
        iteration = int(state.get("rag_iteration") or 0)
        eval_reason = str(state.get("eval_reason") or "")
        chunks = list(state.get("chunks") or [])

        planner_model_kind = model_id or "planner"

        if query:
            try:
                plan, sql_candidate = await _llm_plan(
                    model_id=planner_model_kind,
                    query=query,
                    intent=intent,
                    query_mode=query_mode,
                    slots=slots,
                    iteration=iteration,
                    eval_reason=eval_reason,
                    chunks=chunks,
                )
            except ModelRequestTimeoutError:
                raise
            except Exception as exc:
                logger.warning(
                    "SearchPlanner LLM failed, fallback to rule. %s: %s",
                    type(exc).__name__,
                    exc,
                )
                plan = _build_plan_rule(intent, iteration, eval_reason, query)
                sql_candidate = _default_sql_candidate()
        else:
            plan = _build_plan_rule(intent, iteration, eval_reason, query)
            sql_candidate = _default_sql_candidate()

        sql_plan = _default_sql_plan()
        logger.debug(
            "SearchPlanner done.\n"
            f"intent={intent}\n"
            f"query_mode={query_mode}\n"
            f"iteration={iteration}\n"
            f"strategy={plan.get('strategy')}\n"
            f"vector_query={plan.get('vector_query', '')[:60]}\n"
            f"top_k={plan.get('top_k')}\n"
            f"sql_candidate_enabled={sql_candidate.get('enabled')}\n"
            f"sql_candidate_tables={sql_candidate.get('selected_tables')}\n"
            f"sql_limit={sql_plan.get('limit')}"
        )
        return {
            "search_plan": plan,
            "sql_candidate": sql_candidate,
            "sql_plan": sql_plan,
            "rag_iteration": iteration + 1,
        }

    return search_planner_node
