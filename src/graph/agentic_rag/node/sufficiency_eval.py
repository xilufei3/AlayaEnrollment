from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.documents import Document

from ...llm import get_model
from ...prompts import SUFFICIENCY_EVAL_SYSTEM_PROMPT
from ..schemas import RAGState

logger = logging.getLogger(__name__)

def _chunk_summary(chunks: list[Document], max_chars: int = 800) -> str:
    if not chunks:
        return "（当前没有可用材料）"
    lines: list[str] = []
    total = 0
    for index, doc in enumerate(chunks[:5], start=1):
        text = doc.page_content[:200].strip()
        lines.append(f"[{index}] {text}")
        total += len(text)
        if total >= max_chars:
            break
    return "\n".join(lines)


class SufficiencyEvaluator:
    def __init__(self, *, model_id: str) -> None:
        self.model_id = model_id

    async def evaluate(
        self,
        *,
        query: str,
        intent: str,
        slots: dict[str, str],
        required_slots: list[str],
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
        slots_ok = all(slots.get(s, "").strip() for s in required_slots)
        if slots_ok and len(chunks) >= 2:
            try:
                return await self._llm_evaluate(
                    query=query,
                    intent=intent,
                    slots=slots,
                    required_slots=required_slots,
                    chunks=chunks,
                )
            except Exception as exc:
                logger.warning(f"SufficiencyEval LLM failed, fallback to sufficient. {exc}")
                return {
                    "eval_result": "sufficient",
                    "missing_slots": [],
                    "eval_reason": "LLM eval failed, fallback",
                }

        if not slots_ok:
            missing = [name for name in required_slots if not slots.get(name, "").strip()]
            return {
                "eval_result": "missing_slots",
                "missing_slots": missing,
                "eval_reason": f"缺少关键信息: {missing}",
            }

        # 只有 1 条文档，尝试 LLM 评估
        try:
            return await self._llm_evaluate(
                query=query,
                intent=intent,
                slots=slots,
                required_slots=required_slots,
                chunks=chunks,
            )
        except Exception as exc:
            logger.warning(f"SufficiencyEval LLM failed, fallback to sufficient. {exc}")
            return {
                "eval_result": "sufficient",
                "missing_slots": [],
                "eval_reason": "LLM eval failed, fallback",
            }

    async def _llm_evaluate(
        self,
        *,
        query: str,
        intent: str,
        slots: dict[str, str],
        required_slots: list[str],
        chunks: list[Document],
    ) -> dict[str, Any]:
        model = get_model(self.model_id)
        user_prompt = (
            f"用户问题：{query}\n"
            f"意图：{intent}\n"
            f"已知信息：{json.dumps(slots, ensure_ascii=False)}\n"
            f"当前问题真正依赖的槽位：{json.dumps(required_slots, ensure_ascii=False)}\n"
            f"可用材料摘要：\n{_chunk_summary(chunks)}\n"
            "请评估这些材料是否足以直接回答用户。"
        )
        response = await model.ainvoke(
            [("system", SUFFICIENCY_EVAL_SYSTEM_PROMPT), ("user", user_prompt)],
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

    async def sufficiency_eval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        slots = dict(state.get("slots") or {})
        required_slots = list(state.get("required_slots") or [])
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

        result = await evaluator.evaluate(
            query=query,
            intent=intent,
            slots=slots,
            required_slots=required_slots,
            chunks=chunks,
        )
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
