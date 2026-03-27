from __future__ import annotations

import json
import logging
from typing import Any

from langchain_core.documents import Document

from ...llm import ModelRequestTimeoutError, get_model
from ...prompts.sufficiency_eval import (
    SUFFICIENCY_EVAL_SYSTEM_PROMPT,
    build_sufficiency_eval_user_prompt,
)
from ..schemas import RAGState

logger = logging.getLogger(__name__)

# Reranker relevance_score 低于此阈值的 chunk 不会被累积到 candidate 池
_RELEVANCE_SCORE_THRESHOLD = 0.3
_MAX_CANDIDATE_CHUNKS = 25


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


def _doc_key(doc: Document) -> tuple[str, str]:
    """Stable dedup key: prefer metadata id, fallback to content."""
    doc_id = str(doc.metadata.get("id", "")).strip()
    if doc_id:
        return ("id", doc_id)
    return ("content", doc.page_content)


def _filter_high_relevance(
    chunks: list[Document],
    threshold: float = _RELEVANCE_SCORE_THRESHOLD,
) -> list[Document]:
    """保留 reranker relevance_score >= threshold 的 chunk。"""
    result: list[Document] = []
    for doc in chunks:
        score = doc.metadata.get("relevance_score")
        if score is None:
            # 没有 score 的 chunk（如未经过 reranker）全部保留
            result.append(doc)
        elif float(score) >= threshold:
            result.append(doc)
    return result


def _merge_candidates(
    existing: list[Document],
    incoming: list[Document],
    *,
    limit: int = _MAX_CANDIDATE_CHUNKS,
) -> list[Document]:
    """将新的高质量 chunk 合并到已有候选池，按 id/content 去重。"""
    merged: list[Document] = []
    seen: set[tuple[str, str]] = set()

    for doc in [*existing, *incoming]:
        key = _doc_key(doc)
        if key in seen:
            continue
        seen.add(key)
        merged.append(doc)
        if len(merged) >= limit:
            break

    return merged


class SufficiencyEvaluator:
    def __init__(self, *, model_id: str) -> None:
        self.model_id = model_id

    async def evaluate(
        self,
        *,
        query: str,
        chunks: list[Document],
    ) -> dict[str, Any]:
        if not chunks:
            return {
                "eval_result": "insufficient_docs",
                "eval_reason": "检索结果为空",
            }

        try:
            return await self._llm_evaluate(
                query=query,
                chunks=chunks,
            )
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            logger.warning(f"SufficiencyEval LLM failed, fallback to insufficient_docs. {exc}")
            return {
                "eval_result": "insufficient_docs",
                "eval_reason": "LLM eval failed, fallback to retry",
            }

    async def _llm_evaluate(
        self,
        *,
        query: str,
        chunks: list[Document],
    ) -> dict[str, Any]:
        model = get_model(self.model_id)
        user_prompt = build_sufficiency_eval_user_prompt(
            query=query, chunk_summary=_chunk_summary(chunks),
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
                    "eval_reason": "LLM returned invalid JSON",
                }
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

    async def sufficiency_eval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        reranked_chunks = list(state.get("reranked_vector_chunks") or [])
        existing_candidates = list(state.get("candidate_vector_chunks") or [])
        iteration = int(state.get("rag_iteration") or 0)
        max_iter = int(state.get("max_iterations") or 2)

        # ── 按 rerank score 过滤，累积到 candidate 池 ──
        high_relevance = _filter_high_relevance(reranked_chunks)
        candidates = _merge_candidates(existing_candidates, high_relevance)

        logger.debug(
            f"SufficiencyEval: reranked={len(reranked_chunks)} "
            f"high_relevance={len(high_relevance)} "
            f"candidates_total={len(candidates)}"
        )

        # 已达到最大迭代次数：强制 sufficient（生成节点处理空文档）
        if iteration > max_iter:
            logger.debug(f"SufficiencyEval: max_iterations reached ({iteration} > {max_iter}), force sufficient.")
            return {
                "candidate_vector_chunks": candidates,
                "chunks": candidates,
                "eval_result": "sufficient",
                "eval_reason": "max_iterations reached",
            }

        # ── 用累积的 candidates 评估充分性 ──
        result = await evaluator.evaluate(query=query, chunks=candidates)
        logger.debug(
            "SufficiencyEval done.\n"
            f"candidates={len(candidates)}\n"
            f"eval_result={result['eval_result']}\n"
            f"reason={result['eval_reason']}"
        )
        return {
            "candidate_vector_chunks": candidates,
            "chunks": candidates,
            "eval_result": result["eval_result"],
            "eval_reason": result["eval_reason"],
        }

    return sufficiency_eval_node
