from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ...llm import get_model
from ...prompts import SEARCH_PLANNER_SYSTEM_PROMPT
from ...utils import (
    chunk_texts as shared_chunk_texts,
    query_prefers_year_range as shared_query_prefers_year_range,
)
from ..schemas import RAGState, SQLPlan, SearchPlan

logger = logging.getLogger(__name__)

# 意图 -> 默认检索 top_k（规则定义，与 LLM 无关）
_INTENT_TOP_K: dict[str, int] = {
    "admission_policy": 10,
    "school_overview": 6,
    "major_and_training": 8,
    "career_and_development": 6,
    "campus_life": 6,
}
_DEFAULT_TOP_K = 8
_DEFAULT_SQL_LIMIT = 6
_YEAR_RANGE_HINTS: tuple[str, ...] = (
    "近几年",
    "近年来",
    "历年",
    "往年",
    "最近几年",
)


def _get_top_k(intent: str, iteration: int) -> int:
    """按意图与轮次计算 top_k：首轮用意图默认值，重试时放大。"""
    top_k = _INTENT_TOP_K.get(intent, _DEFAULT_TOP_K)
    if iteration >= 1:
        top_k = min(top_k + 4, 16)
    return top_k


class SearchPlanLLMOutput(BaseModel):
    rewritten_query: str = Field(..., description="改写后的主查询")
    reason: str = Field(default="", description="规划理由")


def _build_plan_rule(
    intent: str,
    iteration: int,
    eval_reason: str,
    query: str,
) -> SearchPlan:
    """规则式兜底：无 LLM 或 LLM 失败时使用。"""
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


def _build_sql_plan(intent: str) -> SQLPlan:
    enabled = intent == "admission_policy"
    return {
        "enabled": enabled,
        "province": "",
        "year": "",
        "limit": _DEFAULT_SQL_LIMIT,
        "reason": "enable sql branch for admission_policy" if enabled else "intent is not admission_policy",
    }


def _query_prefers_year_range(query: str) -> bool:
    return shared_query_prefers_year_range(query)


def _mask_slots_for_query(query: str, slots: dict[str, str]) -> dict[str, str]:
    effective_slots = dict(slots)
    if _query_prefers_year_range(query):
        effective_slots.pop("year", None)
    return effective_slots


def _chunk_texts(chunks: list[Any]) -> list[str]:
    return shared_chunk_texts(chunks)


async def _llm_plan(
    model_id: str,
    query: str,
    intent: str,
    slots: dict[str, str],
    iteration: int,
    eval_reason: str,
    chunks: list[Any] | None = None,
) -> SearchPlan:
    """调用 LLM 生成检索参数，策略固定为 vector_keyword_hybrid。"""
    model = get_model(model_id)
    user_parts = [
        f"用户问题：{query}",
        f"意图：{intent}",
        f"已知信息：{json.dumps(slots, ensure_ascii=False)}",
        f"当前检索轮次：{iteration}",
    ]
    if eval_reason.strip():
        user_parts.append(f"上一轮评估理由：{eval_reason.strip()}")
    chunk_texts = _chunk_texts(list(chunks or []))
    if chunk_texts:
        user_parts.append("上一轮召回 chunk 原文：\n" + "\n".join(chunk_texts))
    user_parts.append("请输出检索参数 JSON。")
    user_prompt = "\n".join(user_parts)

    response = await model.ainvoke(
        [("system", SEARCH_PLANNER_SYSTEM_PROMPT), ("user", user_prompt)],
        response_format={"type": "json_object"},
    )
    content = getattr(response, "content", response)
    if isinstance(content, str):
        data = json.loads(content)
    else:
        data = content

    out = SearchPlanLLMOutput(
        rewritten_query=str(data.get("rewritten_query", query)).strip() or query,
        reason=str(data.get("reason", "")).strip(),
    )
    top_k_final = _get_top_k(intent, iteration)

    plan: SearchPlan = {
        "strategy": "vector_keyword_hybrid",
        "vector_query": out.rewritten_query,
        "top_k": top_k_final,
    }
    logger.debug(
        "SearchPlanner LLM done.\n"
        f"rewritten_query={out.rewritten_query[:60]}...\n"
        f"top_k={top_k_final}\n"
        f"reason={out.reason}"
    )
    return plan


def create_search_planner_node(*, model_id: str | None = None):
    """创建检索策略节点。model_id 存在时使用 LLM 生成参数，否则或失败时用规则兜底。"""

    async def search_planner_node(state: RAGState) -> dict:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        slots = dict(state.get("slots") or {})
        effective_slots = _mask_slots_for_query(query, slots)
        iteration = int(state.get("rag_iteration") or 0)
        eval_reason = str(state.get("eval_reason") or "")
        chunks = list(state.get("chunks") or [])

        planner_model_kind = model_id or "planner"

        if query:
            try:
                plan = await _llm_plan(
                    model_id=planner_model_kind,
                    query=query,
                    intent=intent,
                    slots=effective_slots,
                    iteration=iteration,
                    eval_reason=eval_reason,
                    chunks=chunks,
                )
            except Exception as exc:
                logger.warning(
                    f"SearchPlanner LLM failed, fallback to rule. {type(exc).__name__}: {exc}"
                )
                plan = _build_plan_rule(intent, iteration, eval_reason, query)
        else:
            plan = _build_plan_rule(intent, iteration, eval_reason, query)

        sql_plan = _build_sql_plan(intent)
        logger.debug(
            "SearchPlanner done.\n"
            f"intent={intent}\n"
            f"iteration={iteration}\n"
            f"strategy={plan.get('strategy')}\n"
            f"vector_query={plan.get('vector_query', '')[:60]}\n"
            f"top_k={plan.get('top_k')}\n"
            f"sql_enabled={sql_plan.get('enabled')}\n"
            f"sql_limit={sql_plan.get('limit')}"
        )
        return {
            "search_plan": plan,
            "sql_plan": sql_plan,
            "rag_iteration": iteration + 1,
        }

    return search_planner_node
