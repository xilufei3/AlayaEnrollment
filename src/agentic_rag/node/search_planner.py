from __future__ import annotations

from alayaflow.utils.logger import AlayaFlowLogger

from ..schemas import RAGState, SearchPlan


logger = AlayaFlowLogger()

# 意图 → 默认检索 top_k（政策类需要更多候选）
_INTENT_TOP_K: dict[str, int] = {
    "admission_policy": 10,
    "school_overview": 6,
    "major_and_training": 8,
    "career_and_development": 6,
    "campus_life": 6,
}
_DEFAULT_TOP_K = 8


def _build_plan(
    intent: str,
    slots: dict[str, str],
    iteration: int,
    eval_reason: str,
) -> SearchPlan:
    """
    规则式检索策略规划：
    - 首轮：有 province 槽位时用结构化过滤（structured），否则向量检索（vector）
    - 重试（iteration >= 1）：切换到 hybrid（先结构化再向量补充），同时扩大 top_k
    """
    province = slots.get("province", "").strip()
    year = slots.get("year", "").strip()
    top_k = _INTENT_TOP_K.get(intent, _DEFAULT_TOP_K)

    structured_filters: dict[str, str] = {}
    if province:
        structured_filters["province"] = province
    if year:
        structured_filters["year"] = year

    if iteration == 0:
        if intent == "admission_policy" and province:
            strategy: str = "structured"
        else:
            strategy = "vector"
    else:
        # 重试时扩大范围，使用 hybrid
        strategy = "hybrid"
        top_k = min(top_k + 4, 16)
        logger.debug(
            "SearchPlanner retry.\n"
            f"iteration={iteration}\n"
            f"eval_reason={eval_reason}\n"
            f"new_strategy={strategy}\n"
            f"new_top_k={top_k}"
        )

    plan: SearchPlan = {
        "strategy": strategy,
        "vector_query": "",   # 使用原始 query，retrieval 节点会读取 state.query
        "structured_filters": structured_filters,
        "top_k": top_k,
    }
    return plan


def create_search_planner_node():
    def search_planner_node(state: RAGState) -> dict:
        intent = str(state.get("intent") or "").strip()
        slots = dict(state.get("slots") or {})
        iteration = int(state.get("rag_iteration") or 0)
        eval_reason = str(state.get("eval_reason") or "")

        plan = _build_plan(intent, slots, iteration, eval_reason)

        logger.debug(
            "SearchPlanner done.\n"
            f"intent={intent}\n"
            f"iteration={iteration}\n"
            f"strategy={plan['strategy']}\n"
            f"filters={plan['structured_filters']}\n"
            f"top_k={plan['top_k']}"
        )

        return {
            "search_plan": plan,
            "rag_iteration": iteration + 1,
        }

    return search_planner_node
