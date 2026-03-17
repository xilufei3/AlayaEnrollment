from __future__ import annotations

import json

from pydantic import BaseModel, Field

from alayaflow.utils.logger import AlayaFlowLogger

from ...node.model_provider import get_model

from ..schemas import RAGState, SearchPlan


logger = AlayaFlowLogger()

# 意图 → 默认检索 top_k（规则定义，与 LLM 无关）
_INTENT_TOP_K: dict[str, int] = {
    "admission_policy": 10,
    "school_overview": 6,
    "major_and_training": 8,
    "career_and_development": 6,
    "campus_life": 6,
}
_DEFAULT_TOP_K = 8

def _get_top_k(intent: str, iteration: int) -> int:
    """按意图与轮次计算 top_k：首轮用意图默认值，重试时放大。"""
    top_k = _INTENT_TOP_K.get(intent, _DEFAULT_TOP_K)
    if iteration >= 1:
        top_k = min(top_k + 4, 16)
    return top_k


SEARCH_PLANNER_SYSTEM = """你是南科大招生咨询的检索策略规划模块。根据用户问题和上下文，生成检索参数。

请完成以下任务：
1. **Query Rewrite**：将用户问题改写为更适合向量检索的表述（补全指代、去掉口语化），若已清晰可原样返回。
2. **子问题拆分**：若问题包含多个独立子问题（如同时问分数线和专业），拆成若干条子问题；否则返回包含改写后问题的单元素列表。

输出严格为 JSON，且只包含以下字段（不要多余字段）：
- rewritten_query: 字符串，改写后的主查询（用于向量检索）
- sub_queries: 字符串数组，子问题列表（至少包含 rewritten_query）
- reason: 字符串，简短理由（不超过 50 字）
"""


class SearchPlanLLMOutput(BaseModel):
    rewritten_query: str = Field(..., description="改写后的主查询")
    sub_queries: list[str] = Field(default_factory=list, description="子问题列表")
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


def _llm_plan(
    model_id: str,
    query: str,
    intent: str,
    slots: dict[str, str],
    iteration: int,
    eval_reason: str,
) -> SearchPlan:
    """调用 LLM 生成检索参数，策略固定为 vector_keyword_hybrid。"""
    model = get_model(model_id)
    user_parts = [
        f"用户问题：{query}",
        f"意图：{intent}",
        f"已知槽位：{json.dumps(slots, ensure_ascii=False)}",
        f"当前检索轮次：{iteration}",
    ]
    if eval_reason.strip():
        user_parts.append(f"上一轮评估理由：{eval_reason.strip()}")
    user_parts.append("请输出检索参数 JSON。")
    user_prompt = "\n".join(user_parts)

    response = model.invoke(
        [("system", SEARCH_PLANNER_SYSTEM), ("user", user_prompt)],
        response_format={"type": "json_object"},
    )
    content = getattr(response, "content", response)
    if isinstance(content, str):
        data = json.loads(content)
    else:
        data = content

    out = SearchPlanLLMOutput(
        rewritten_query=str(data.get("rewritten_query", query)).strip() or query,
        sub_queries=list(data.get("sub_queries") or []),
        reason=str(data.get("reason", "")).strip(),
    )
    top_k_final = _get_top_k(intent, iteration)
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
    """创建检索策略节点。model_id 存在时使用 LLM 生成参数，否则或失败时用规则兜底。"""
    def search_planner_node(state: RAGState) -> dict:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        slots = dict(state.get("slots") or {})
        iteration = int(state.get("rag_iteration") or 0)
        eval_reason = str(state.get("eval_reason") or "")

        planner_model_kind = model_id or "planner"

        if query:
            try:
                plan = _llm_plan(
                    model_id=planner_model_kind,
                    query=query,
                    intent=intent,
                    slots=slots,
                    iteration=iteration,
                    eval_reason=eval_reason,
                )
            except Exception as exc:
                logger.warning(
                    f"SearchPlanner LLM failed, fallback to rule. {type(exc).__name__}: {exc}"
                )
                plan = _build_plan_rule(intent, iteration, eval_reason, query)
        else:
            plan = _build_plan_rule(intent, iteration, eval_reason, query)

        logger.debug(
            "SearchPlanner done.\n"
            f"intent={intent}\n"
            f"iteration={iteration}\n"
            f"strategy={plan.get('strategy')}\n"
            f"filters={plan.get('structured_filters')}\n"
            f"top_k={plan.get('top_k')}"
        )
        return {
            "search_plan": plan,
            "rag_iteration": iteration + 1,
        }

    return search_planner_node
