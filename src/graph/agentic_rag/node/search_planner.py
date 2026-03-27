from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from langchain_core.documents import Document

from ...llm import ModelRequestTimeoutError, get_model
from ...prompts.search_planner import (
    SEARCH_PLANNER_SYSTEM,
    build_search_planner_user_prompt,
)
from ..schemas import RAGState, SearchPlan

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 8


class SearchPlanLLMOutput(BaseModel):
    rewritten_query: str = Field(..., description="改写后的主查询")
    sub_queries: list[str] = Field(default_factory=list, description="子问题列表")
    reason: str = Field(default="", description="规划理由")


def _get_top_k(iteration: int) -> int:
    top_k = _DEFAULT_TOP_K
    if iteration >= 1:
        top_k = min(top_k + 4, 16)
    return top_k


def _build_plan_rule(
    iteration: int,
    eval_reason: str,
    query: str,
) -> SearchPlan:
    top_k = _get_top_k(iteration)

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


def _candidates_summary(
    candidates: list[Document],
    max_chars: int = 3000,
) -> str:
    """将已有 candidate chunks 摘要为文本，供 search planner 参考。"""
    if not candidates:
        return ""
    lines: list[str] = []
    total = 0
    for i, doc in enumerate(candidates, start=1):
        text = doc.page_content.strip()[:200]
        lines.append(f"[{i}] {text}")
        total += len(text)
        if total >= max_chars:
            break
    return "\n".join(lines)


async def _llm_plan(
    model_id: str,
    query: str,
    reply_mode: str,
    iteration: int,
    eval_reason: str,
    candidates: list[Document] | None = None,
) -> SearchPlan:
    model = get_model(model_id)
    candidates_text = _candidates_summary(candidates or [])
    user_prompt = build_search_planner_user_prompt(
        query=query,
        reply_mode=reply_mode,
        iteration=iteration,
        eval_reason=eval_reason,
        candidates_text=candidates_text,
    )

    response = await model.ainvoke(
        [("system", SEARCH_PLANNER_SYSTEM), ("user", user_prompt)],
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
        sub_queries=list(data.get("sub_queries") or []),
        reason=str(data.get("reason", "")).strip(),
    )
    top_k_final = _get_top_k(iteration)
    sub_queries_final = out.sub_queries if out.sub_queries else [out.rewritten_query]

    plan: SearchPlan = {
        "strategy": "vector_keyword_hybrid",
        "vector_query": out.rewritten_query,
        "sub_queries": sub_queries_final,
        "top_k": top_k_final,
    }
    logger.debug(
        "SearchPlanner LLM done.\n"
        f"rewritten_query={out.rewritten_query[:60]}...\n"
        f"reply_mode={reply_mode}\n"
        f"top_k={top_k_final}\n"
        f"reason={out.reason}"
    )
    return plan


def create_search_planner_node(*, model_id: str | None = None):
    async def search_planner_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        reply_mode = str(state.get("reply_mode") or "hat").strip().lower()
        if reply_mode not in {"hat", "expand"}:
            reply_mode = "hat"
        iteration = int(state.get("rag_iteration") or 0)
        eval_reason = str(state.get("eval_reason") or "")
        candidates = list(state.get("candidate_vector_chunks") or [])

        planner_model_kind = model_id or "planner"

        if query:
            try:
                plan = await _llm_plan(
                    model_id=planner_model_kind,
                    query=query,
                    reply_mode=reply_mode,
                    iteration=iteration,
                    eval_reason=eval_reason,
                    candidates=candidates,
                )
            except ModelRequestTimeoutError:
                raise
            except Exception as exc:
                logger.warning(
                    "SearchPlanner LLM failed, fallback to rule. %s: %s",
                    type(exc).__name__,
                    exc,
                )
                plan = _build_plan_rule(iteration, eval_reason, query)
        else:
            plan = _build_plan_rule(iteration, eval_reason, query)
        logger.debug(
            "SearchPlanner done.\n"
            f"iteration={iteration}\n"
            f"reply_mode={reply_mode}\n"
            f"strategy={plan.get('strategy')}\n"
            f"vector_query={plan.get('vector_query', '')[:60]}\n"
            f"top_k={plan.get('top_k')}"
        )
        return {
            "search_plan": plan,
            "rag_iteration": iteration + 1,
        }

    return search_planner_node
