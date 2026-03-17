from __future__ import annotations

import json
from typing import Any

from langchain_core.documents import Document

from alayaflow.utils.logger import AlayaFlowLogger

from ...config import REQUIRED_SLOTS_BY_INTENT
from ...node.model_provider import get_model
from ..schemas import RAGState


logger = AlayaFlowLogger()

_EVAL_SYSTEM_PROMPT = """你是一个检索质量评估器。
根据用户问题和检索到的文档，判断当前检索结果的充分性。

输出严格 JSON，包含三个字段：
- eval_result: 必须是以下之一：
  - "sufficient"：文档能够支撑回答用户问题
  - "missing_slots"：文档中涉及多个省份/年份等维度，需要用户补充具体信息才能精确回答
  - "insufficient_docs"：文档内容与用户问题相关性低，或文档为空
- missing_slots: 列表，如 ["province"]；仅 missing_slots 时填写，其余填 []
- reason: 简短评估理由（不超过50字）
"""


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
        intent: str,
        slots: dict[str, str],
        chunks: list[Document],
    ) -> dict[str, Any]:
        # 快速规则：空文档直接 insufficient_docs
        if not chunks:
            return {
                "eval_result": "insufficient_docs",
                "missing_slots": [],
                "eval_reason": "检索结果为空",
            }

        # 快速规则：已满足所需槽位 且 有足够文档 → sufficient（减少 LLM 调用）
        required = REQUIRED_SLOTS_BY_INTENT.get(intent, [])
        slots_ok = all(slots.get(s, "").strip() for s in required)
        if slots_ok and len(chunks) >= 2:
            try:
                return self._llm_evaluate(query=query, intent=intent, slots=slots, chunks=chunks)
            except Exception as exc:
                logger.warning(f"SufficiencyEval LLM failed, fallback to sufficient. {exc}")
                return {
                    "eval_result": "sufficient",
                    "missing_slots": [],
                    "eval_reason": "LLM eval failed, fallback",
                }

        if not slots_ok:
            missing = [s for s in required if not slots.get(s, "").strip()]
            return {
                "eval_result": "missing_slots",
                "missing_slots": missing,
                "eval_reason": f"缺少槽位: {missing}",
            }

        # 只有 1 条文档，尝试 LLM 评估
        try:
            return self._llm_evaluate(query=query, intent=intent, slots=slots, chunks=chunks)
        except Exception as exc:
            logger.warning(f"SufficiencyEval LLM failed, fallback to sufficient. {exc}")
            return {
                "eval_result": "sufficient",
                "missing_slots": [],
                "eval_reason": "LLM eval failed, fallback",
            }

    def _llm_evaluate(
        self,
        *,
        query: str,
        intent: str,
        slots: dict[str, str],
        chunks: list[Document],
    ) -> dict[str, Any]:
        model = get_model(self.model_id)
        user_prompt = (
            f"用户问题：{query}\n"
            f"意图：{intent}\n"
            f"已知槽位：{json.dumps(slots, ensure_ascii=False)}\n"
            f"检索到的文档摘要：\n{_chunk_summary(chunks)}\n"
            "请评估上述检索结果是否充分。"
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
        if eval_result not in ("sufficient", "missing_slots", "insufficient_docs"):
            eval_result = "sufficient"

        return {
            "eval_result": eval_result,
            "missing_slots": list(data.get("missing_slots") or []),
            "eval_reason": str(data.get("reason", "")),
        }


def create_sufficiency_eval_node(*, model_id: str | None = None):
    evaluator = SufficiencyEvaluator(model_id=model_id or "eval")

    def sufficiency_eval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        slots = dict(state.get("slots") or {})
        chunks = list(state.get("chunks") or [])
        iteration = int(state.get("rag_iteration") or 0)
        max_iter = int(state.get("max_iterations") or 2)

        # 已达到最大迭代次数：强制 sufficient（生成节点处理空文档）
        if iteration > max_iter:
            logger.debug(f"SufficiencyEval: max_iterations reached ({iteration} > {max_iter}), force sufficient.")
            return {
                "eval_result": "sufficient",
                "missing_slots": [],
                "eval_reason": "max_iterations reached",
            }

        result = evaluator.evaluate(query=query, intent=intent, slots=slots, chunks=chunks)
        logger.debug(
            "SufficiencyEval done.\n"
            f"intent={intent}\n"
            f"chunks={len(chunks)}\n"
            f"eval_result={result['eval_result']}\n"
            f"reason={result['eval_reason']}"
        )
        return {
            "eval_result": result["eval_result"],
            "missing_slots": result["missing_slots"],
            "eval_reason": result["eval_reason"],
        }

    return sufficiency_eval_node
