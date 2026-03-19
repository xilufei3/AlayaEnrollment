from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.documents import Document

from ...llm import get_model
from ..schemas import RAGState


logger = logging.getLogger(__name__)

_EVAL_SYSTEM_PROMPT = """
你是“南方科技大学研究生招生与培养助手”的检索充分性评估模块。

【任务】
根据用户问题和当前检索到的文档摘要，判断这些材料是否足以支撑生成阶段给出可靠回答。

【判定标准】
- `sufficient`：
  - 文档与问题主题高度相关；
  - 能覆盖用户问题的核心诉求，或至少足以支持安全、明确的答复；
  - 对流程、条件、政策解释类问题，已有足够依据说明关键步骤或关键限制。
- `insufficient_docs`：
  - 文档为空；
  - 文档与问题相关性弱；
  - 文档只覆盖了边缘信息，无法支撑回答核心问题；
  - 用户问题包含多个重点，但当前文档无法覆盖主要部分。

【输出要求】
严格输出 JSON，且只包含：
- `eval_result`: `"sufficient"` 或 `"insufficient_docs"`
- `reason`: 不超过 50 字的简短理由

【注意】
- 评估的是“是否足以支撑回答”，不是“是否与问题略有相关”。
- 不要输出任何 JSON 之外的内容。
""".strip()


def _chunk_summary(chunks: list[Document], max_chars: int = 800) -> str:
    if not chunks:
        return "（无检索文档）"
    lines = []
    total = 0
    for i, doc in enumerate(chunks[:5], start=1):
        text = doc.page_content[:200].strip()
        lines.append(f"[{i}] {text}")
        total += len(text)
        if total >= max_chars:
            break
    return "\n".join(lines)


class SufficiencyEvaluator:
    def __init__(self, *, model_id: str) -> None:
        self.model_id = model_id

    def evaluate(
        self,
        *,
        query: str,
        chunks: list[Document],
    ) -> dict[str, Any]:
        # 快速规则：空文档直接 insufficient_docs
        if not chunks:
            return {
                "eval_result": "insufficient_docs",
                "eval_reason": "检索结果为空",
            }

        # 快速规则：有足够文档 → sufficient（减少 LLM 调用）
        if len(chunks) >= 2:
            try:
                return self._llm_evaluate(query=query, chunks=chunks)
            except Exception as exc:
                logger.warning(f"SufficiencyEval LLM failed, fallback to sufficient. {exc}")
                return {
                    "eval_result": "sufficient",
                    "eval_reason": "LLM eval failed, fallback",
                }

        # 只有 1 条文档，尝试 LLM 评估
        try:
            return self._llm_evaluate(query=query, chunks=chunks)
        except Exception as exc:
            logger.warning(f"SufficiencyEval LLM failed, fallback to sufficient. {exc}")
            return {
                "eval_result": "sufficient",
                "eval_reason": "LLM eval failed, fallback",
            }

    def _llm_evaluate(
        self,
        *,
        query: str,
        chunks: list[Document],
    ) -> dict[str, Any]:
        model = get_model(self.model_id)
        user_prompt = (
            f"【用户问题】\n{query}\n"
            f"【检索文档摘要】\n{_chunk_summary(chunks)}\n"
            "请判断这些材料是否足以支持生成可靠回答。"
        )
        response = model.invoke(
            [("system", _EVAL_SYSTEM_PROMPT), ("user", user_prompt)],
            response_format={"type": "json_object"},
        )
        content = getattr(response, "content", response)
        if isinstance(content, str):
            data = json.loads(content)
        else:
            data = content

        eval_result = str(data.get("eval_result", "sufficient"))
        if eval_result not in ("sufficient", "insufficient_docs"):
            eval_result = "sufficient"

        return {
            "eval_result": eval_result,
            "eval_reason": str(data.get("reason", "")),
        }


def create_sufficiency_eval_node(*, model_id: str | None = None):
    evaluator = SufficiencyEvaluator(model_id=model_id or "eval")

    def sufficiency_eval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        chunks = list(state.get("chunks") or [])
        iteration = int(state.get("rag_iteration") or 0)
        max_iter = int(state.get("max_iterations") or 2)

        # 已达到最大迭代次数：强制 sufficient（生成节点处理空文档）
        if iteration > max_iter:
            logger.debug(f"SufficiencyEval: max_iterations reached ({iteration} > {max_iter}), force sufficient.")
            return {
                "eval_result": "sufficient",
                "eval_reason": "max_iterations reached",
            }

        result = evaluator.evaluate(query=query, chunks=chunks)
        logger.debug(
            "SufficiencyEval done.\n"
            f"chunks={len(chunks)}\n"
            f"eval_result={result['eval_result']}\n"
            f"reason={result['eval_reason']}"
        )
        return {
            "eval_result": result["eval_result"],
            "eval_reason": result["eval_reason"],
        }

    return sufficiency_eval_node
