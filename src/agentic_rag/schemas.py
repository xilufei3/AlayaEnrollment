from __future__ import annotations

from typing import Any, Literal, TypedDict

from langchain_core.documents import Document


class SearchPlan(TypedDict, total=False):
    strategy: Literal["vector", "structured", "hybrid"]
    vector_query: str            # 向量检索使用的查询（可经改写）
    structured_filters: dict[str, str]  # 元数据过滤条件，如 {"province": "浙江", "year": "2025"}
    top_k: int


class RAGState(TypedDict, total=False):
    # ── 从 WorkflowState 传入（只读输入）─────────────────────────────
    query: str
    intent: str
    slots: dict[str, str]

    # ── 子图内部循环状态 ──────────────────────────────────────────────
    search_plan: SearchPlan
    rag_iteration: int           # 当前第几轮（从 0 开始，每次 search_planner 调用后 +1）
    max_iterations: int          # 最大允许轮数，默认 2

    # ── 各路检索中间结果 ──────────────────────────────────────────────
    vector_chunks: list[Document]
    structured_results: list[dict[str, Any]]

    # ── 重排后的最终文档（子图输出到 WorkflowState.chunks）────────────
    chunks: list[Document]

    # ── 充分性评估结果（子图输出到 WorkflowState.missing_slots）───────
    eval_result: Literal["sufficient", "missing_slots", "insufficient_docs"]
    missing_slots: list[str]    # eval 发现还需要的槽位
    eval_reason: str            # 评估理由（用于重试时 search_planner 参考）
