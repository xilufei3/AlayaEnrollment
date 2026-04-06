from __future__ import annotations

import json
import logging
import re
from typing import Any

from langchain_core.documents import Document

from ...llm import ModelRequestTimeoutError, get_model
from ...prompts.sufficiency_eval import SUFFICIENCY_EVAL_SYSTEM_PROMPT
from ...structured_results import StructuredTableResult, format_structured_results_for_prompt
from ..schemas import RAGState

logger = logging.getLogger(__name__)


def _chunk_summary(chunks: list[Document], max_chars: int = 20000) -> str:
    lines: list[str] = []
    total = 0
    for index, doc in enumerate(chunks, start=1):
        text = doc.page_content.strip()
        lines.append(f"[{index}] {text}")
        total += len(text)
        if total >= max_chars:
            break
    return "\n".join(lines)


def _structured_results_summary(rows: list[StructuredTableResult], max_chars: int = 10000) -> str:
    return format_structured_results_for_prompt(rows, max_chars=max_chars)


def _material_summary(
    *,
    chunks: list[Document],
    structured_results: list[StructuredTableResult],
) -> str:
    parts: list[str] = []
    chunk_text = _chunk_summary(chunks)
    structured_text = _structured_results_summary(structured_results)
    if chunk_text:
        parts.append(f"非结构化材料：\n{chunk_text}")
    if structured_text:
        parts.append(f"结构化 SQL 结果：\n{structured_text}")
    if not parts:
        return "（当前没有可用材料）"
    return "\n\n".join(parts)


def _normalize_text(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "")).strip()


def _truncate_text(text: str, max_chars: int) -> str:
    normalized = _normalize_text(text)
    if len(normalized) <= max_chars:
        return normalized
    return normalized[: max_chars - 1].rstrip() + "…"


def _extract_chunk_highlights(
    chunks: list[Document],
    *,
    max_items: int = 4,
    max_chars_per_item: int = 72,
) -> list[str]:
    highlights: list[str] = []
    seen: set[str] = set()
    for doc in chunks:
        text = _normalize_text(getattr(doc, "page_content", ""))
        if not text:
            continue
        first_span = re.split(r"[。！？!?；;\n]+", text, maxsplit=1)[0].strip()
        candidate = _truncate_text(first_span or text, max_chars_per_item)
        if not candidate or candidate in seen:
            continue
        highlights.append(candidate)
        seen.add(candidate)
        if len(highlights) >= max_items:
            break
    return highlights


def _compose_eval_reason(
    *,
    base_reason: str,
    chunks: list[Document],
    include_chunk_highlights: bool,
) -> str:
    parts: list[str] = []
    normalized_reason = _normalize_text(base_reason)
    if normalized_reason:
        parts.append(normalized_reason)
    if include_chunk_highlights:
        highlights = _extract_chunk_highlights(chunks)
        if highlights:
            numbered = "；".join(f"{index}. {item}" for index, item in enumerate(highlights, start=1))
            parts.append(f"本轮已覆盖要点：{numbered}")
        else:
            parts.append("本轮未召回到明确的非结构化要点")
    return "；".join(part for part in parts if part).strip()


class SufficiencyEvaluator:
    def __init__(self, *, model_id: str) -> None:
        self.model_id = model_id

    async def evaluate(
        self,
        *,
        query: str,
        intent: str,
        chunks: list[Document],
        structured_results: list[StructuredTableResult],
        channel: str = "",
    ) -> dict[str, Any]:
        # 快速规则：无非结构化材料且无结构化结果时直接 insufficient_docs
        if not chunks and not structured_results:
            return {
                "eval_result": "insufficient_docs",
                "eval_reason": "检索结果为空",
                "qa_doc": None,
            }

        # LLM 只判断文档充分性（sufficient / insufficient_docs）
        try:
            return await self._llm_evaluate(
                query=query,
                intent=intent,
                chunks=chunks,
                structured_results=structured_results,
                channel=channel,
            )
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            logger.warning(f"SufficiencyEval LLM failed, fallback to insufficient_docs. {exc}")
            return {
                "eval_result": "insufficient_docs",
                "eval_reason": "大模型评估失败，回退后重试",
                "qa_doc": None,
            }

    @staticmethod
    def _parse_qa_doc(data: dict[str, Any], query: str) -> Document | None:
        raw = data.get("qa_doc")
        if not raw or not isinstance(raw, dict):
            return None
        question = str(raw.get("question") or "").strip()
        answer = str(raw.get("answer") or "").strip()
        if not question or not answer:
            return None
        return Document(
            page_content=f"Q: {question}\nA: {answer}",
            metadata={"qa_extracted": True, "qa_source": "eval_llm", "original_query": query},
        )

    async def _llm_evaluate(
        self,
        *,
        query: str,
        intent: str,
        chunks: list[Document],
        structured_results: list[StructuredTableResult],
        channel: str = "",
    ) -> dict[str, Any]:
        model = get_model(self.model_id, channel=channel)
        user_prompt = (
            f"原始用户问题：{query}\n"
            f"意图：{intent}\n"
            f"可用材料摘要：\n{_material_summary(chunks=chunks, structured_results=structured_results)}\n"
            "请评估这些材料是否足以直接回答用户，并提取匹配的 QA 条目（如有）。"
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
                    "eval_reason": "大模型返回的 JSON 无效",
                    "qa_doc": None,
                }
        else:
            data = content

        eval_result = str(data.get("eval_result", "sufficient"))
        if eval_result not in ("sufficient", "insufficient_docs"):
            eval_result = "sufficient"

        return {
            "eval_result": eval_result,
            "eval_reason": str(data.get("reason", "")),
            "qa_doc": self._parse_qa_doc(data, query),
        }


def create_sufficiency_eval_node(*, model_id: str | None = None):
    evaluator = SufficiencyEvaluator(model_id=model_id or "eval")

    async def sufficiency_eval_node(state: RAGState) -> dict[str, Any]:
        query = str(state.get("query") or "").strip()
        intent = str(state.get("intent") or "").strip()
        chunks = list(state.get("chunks") or [])
        structured_results = list(state.get("structured_results") or [])
        channel = str(state.get("channel") or "").strip().lower()
        iteration = int(state.get("rag_iteration") or 0)
        max_iter = int(state.get("max_iterations") or 2)

        # 已达到最大迭代次数：强制 sufficient（生成节点处理空文档）
        if iteration > max_iter:
            logger.debug(f"SufficiencyEval: max_iterations reached ({iteration} > {max_iter}), force sufficient.")
            return {
                "eval_result": "sufficient",
                "eval_reason": "已达到最大迭代次数",
                "qa_doc": None,
            }

        result = await evaluator.evaluate(
            query=query,
            intent=intent,
            chunks=chunks,
            structured_results=structured_results,
            channel=channel,
        )
        qa_doc = result.get("qa_doc")
        eval_result = result["eval_result"]
        # 命中 QA 直接视为 sufficient，无需继续检索
        if qa_doc is not None:
            eval_result = "sufficient"
        include_chunk_highlights = eval_result != "sufficient" and iteration < max_iter
        eval_reason = _compose_eval_reason(
            base_reason=str(result.get("eval_reason", "")),
            chunks=chunks,
            include_chunk_highlights=include_chunk_highlights,
        )
        logger.debug(
            "SufficiencyEval done.\n"
            f"intent={intent}\n"
            f"chunks={len(chunks)}\n"
            f"structured_results={len(structured_results)}\n"
            f"eval_result={eval_result}\n"
            f"qa_doc={'yes' if qa_doc else 'no'}\n"
            f"reason={eval_reason}"
        )
        return {
            "eval_result": eval_result,
            "eval_reason": eval_reason,
            "qa_doc": qa_doc,
        }

    return sufficiency_eval_node
