from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.documents import Document

from ...llm import ModelRequestTimeoutError, get_model
from ...prompts import SUFFICIENCY_EVAL_SYSTEM_PROMPT
from ..schemas import RAGState

logger = logging.getLogger(__name__)

def _chunk_summary(chunks: list[Document], max_chars: int = 6000) -> str:
    if not chunks:
        return "（当前没有可用材料）"
    lines: list[str] = []
    total = 0
    for index, doc in enumerate(chunks, start=1):
        text = doc.page_content.strip()
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
        missing_slots: list[str],
        chunks: list[Document],
    ) -> dict[str, Any]:
        # 快速规则：空文档直接 insufficient_docs
        if not chunks:
            return {
                "eval_result": "insufficient_docs",
                "missing_slots": [],
                "eval_reason": "检索结果为空",
            }

        # 缺槽位由 intent_classify 统一判定，直接透传
        if missing_slots:
            return {
                "eval_result": "missing_slots",
                "missing_slots": missing_slots,
                "eval_reason": f"缺少关键信息: {missing_slots}",
            }

        # LLM 只判断文档充分性（sufficient / insufficient_docs）
        try:
            return await self._llm_evaluate(
                query=query,
                intent=intent,
                chunks=chunks,
            )
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            logger.warning(f"SufficiencyEval LLM failed, fallback to insufficient_docs. {exc}")
            return {
                "eval_result": "insufficient_docs",
                "missing_slots": [],
                "eval_reason": "LLM eval failed, fallback to retry",
            }

    async def _llm_evaluate(
        self,
        *,
        query: str,
        intent: str,
        chunks: list[Document],
    ) -> dict[str, Any]:
        model = get_model(self.model_id)
        user_prompt = (
            f"用户问题：{query}\n"
            f"意图：{intent}\n"
            f"可用材料摘要：\n{_chunk_summary(chunks)}\n"
            "请评估这些材料是否足以直接回答用户。"
        )
        response = await model.ainvoke(
            [("system", SUFFICIENCY_EVAL_SYSTEM_PROMPT), ("user", user_prompt)],
            response_format={"type": "json_object"},
        )
        content = getattr(response, "content", response)
        if isinstance(content, str):
            try:
                data = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                logger.warning("SufficiencyEval: LLM returned invalid JSON, fallback insufficient_docs. content=%s", content[:200])
                return {
                    "eval_result": "insufficient_docs",
                    "missing_slots": [],
                    "eval_reason": "LLM returned invalid JSON",
                }
        else:
            data = content

        eval_result = str(data.get("eval_result", "sufficient"))
        if eval_result not in ("sufficient", "insufficient_docs"):
            eval_result = "sufficient"

        return {
            "eval_result": eval_result,
            "missing_slots": [],
            "eval_reason": str(data.get("reason", "")),
        }


def create_sufficiency_eval_node(*, model_id: str | None = None):
    evaluator = SufficiencyEvaluator(model_id=model_id or "eval")

    async def sufficiency_eval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        missing_slots = list(state.get("missing_slots") or [])
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
            missing_slots=missing_slots,
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
