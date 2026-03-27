from __future__ import annotations

import json
import logging
from typing import Any

from pydantic import BaseModel, Field

from ...llm import ModelRequestTimeoutError, get_model
from ..schemas import RAGState, SearchPlan

logger = logging.getLogger(__name__)

_DEFAULT_TOP_K = 8

SEARCH_PLANNER_SYSTEM = """
你是“南方科技大学研究生招生与培养助手”的检索规划模块。

【目标】
根据用户问题，为后续知识检索生成更稳定、召回率更高的检索查询。

【你的任务】
1. 重写主查询：
   - 保留用户真实意图、关键实体、时间范围和限定条件；
   - 补全口语、省略和代词，使查询更适合向量检索；
   - 不要凭空新增用户未提及的事实。
2. 拆分子问题：
   - 若用户一次问了多个独立问题，拆成若干可以分别检索的子问题；
   - 若只是一个问题，返回仅包含主查询的单元素列表。
3. 重试策略：
   - 若提供了上一轮评估理由，优先根据该理由调整查询粒度；
   - 当上一轮信息不足时，优先做“适度泛化”而不是机械重复原问题。

【输出要求】
严格输出 JSON，且只允许包含以下字段：
- `rewritten_query`: 字符串，主检索查询
- `sub_queries`: 字符串数组，子问题列表，至少包含主查询
- `reason`: 字符串，简要说明本次改写/拆分思路，不超过 50 字

【约束】
- 不要输出任何 JSON 之外的内容。
- 不要生成与南科大研究生语境无关的泛化检索词。
""".strip()


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


async def _llm_plan(
    model_id: str,
    query: str,
    iteration: int,
    eval_reason: str,
) -> SearchPlan:
    model = get_model(model_id)
    user_parts = [
        f"【用户问题】\n{query}",
        f"【当前检索轮次】\n{iteration}",
    ]
    if eval_reason.strip():
        user_parts.append(f"【上一轮评估理由】\n{eval_reason.strip()}")
    user_parts.append("请输出检索规划 JSON。")
    user_prompt = "\n".join(user_parts)

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
        f"top_k={top_k_final}\n"
        f"reason={out.reason}"
    )
    return plan


def create_search_planner_node(*, model_id: str | None = None):
    async def search_planner_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        iteration = int(state.get("rag_iteration") or 0)
        eval_reason = str(state.get("eval_reason") or "")

        planner_model_kind = model_id or "planner"

        if query:
            try:
                plan = await _llm_plan(
                    model_id=planner_model_kind,
                    query=query,
                    iteration=iteration,
                    eval_reason=eval_reason,
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
            f"strategy={plan.get('strategy')}\n"
            f"vector_query={plan.get('vector_query', '')[:60]}\n"
            f"top_k={plan.get('top_k')}"
        )
        return {
            "search_plan": plan,
            "rag_iteration": iteration + 1,
        }

    return search_planner_node
