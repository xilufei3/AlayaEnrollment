from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Sequence

try:  # Python 3.9+
    from zoneinfo import ZoneInfo
except ImportError:  # pragma: no cover
    ZoneInfo = None  # type: ignore[misc, assignment]

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.runtime import Runtime

from ...config.settings import HISTORY_LAST_K_TURNS
from ..llm import ModelRequestTimeoutError, get_model
from ..prompts.generation import (
    WECHAT_SYSTEM_SUFFIX,
    build_generation_system_prompt,
    build_generation_user_prompt,
)
from ..state import WorkflowState
from ..structured_results import StructuredTableResult, format_structured_results_for_prompt
from ..utils import (
    chunk_texts as shared_chunk_texts,
    extract_query_from_state as shared_extract_query_from_state,
    to_stream_piece as shared_to_stream_piece,
    to_text as shared_to_text,
)

logger = logging.getLogger(__name__)


class GenerationComponent:
    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id

    @staticmethod
    def _timezone_name() -> str:
        return os.getenv("ASSISTANT_TIMEZONE", "").strip() or "Asia/Shanghai"

    @classmethod
    def _current_datetime_hint(cls) -> str:
        tz_label = "UTC"
        tzinfo = timezone.utc
        tz_name = cls._timezone_name()
        if ZoneInfo is not None:
            try:
                tzinfo = ZoneInfo(tz_name)
                tz_label = tz_name
            except Exception:  # pragma: no cover - fall back to UTC if tz unavailable
                tzinfo = timezone.utc
                tz_label = "UTC"
        now_local = datetime.now(tzinfo)
        display_time = now_local.strftime("%Y年%m月%d日 %H:%M")
        return f"当前时间：{display_time}（{tz_label}）。当前年份：{now_local.year}年。"

    @staticmethod
    def _merge_suffixes(*parts: str | None) -> str:
        merged: list[str] = []
        for part in parts:
            if not part:
                continue
            text = str(part).strip()
            if text:
                merged.append(text)
        return "\n\n".join(merged)

    @staticmethod
    def _to_text(content: Any) -> str:
        return shared_to_text(content)

    @staticmethod
    def _to_stream_piece(content: Any) -> str:
        return shared_to_stream_piece(content)

    @staticmethod
    def _chunk_texts(chunks: Sequence[Any]) -> list[str]:
        return shared_chunk_texts(chunks)

    @staticmethod
    def _structured_results_text(rows: Sequence[StructuredTableResult]) -> str:
        return format_structured_results_for_prompt(rows)

    @staticmethod
    def _structured_results_guidance_text() -> str:
        return (
            "如果需要使用下面的 SQL 结构化数据，请优先依据表说明、字段说明和结果条目作答；"
            "除非用户明确只问单个字段，否则应尽量完整展示该表已返回的列，不要随意省略结果条目中的字段。"
            "输出表格时，优先按字段说明中的列顺序组织表头；当数据存在明确对比维度时，请整理成简洁、规范的表格返回。"
        )

    @classmethod
    def _history_text(cls, messages: Sequence[Any], max_turns: int = 6) -> str:
        rows: list[str] = []
        for msg in messages:
            role = ""
            content: Any = ""
            if isinstance(msg, BaseMessage):
                msg_type = str(getattr(msg, "type", "")).lower()
                if msg_type in ("human", "user"):
                    role = "用户"
                elif msg_type in ("ai", "assistant"):
                    role = "助手"
                content = getattr(msg, "content", "")
            elif isinstance(msg, dict):
                msg_type = str(msg.get("type", msg.get("role", ""))).lower()
                if msg_type in ("human", "user"):
                    role = "用户"
                elif msg_type in ("ai", "assistant"):
                    role = "助手"
                content = msg.get("content", "")
            if not role:
                continue
            text = cls._to_text(content)
            if text:
                rows.append(f"{role}：{text}")

        if not rows:
            return "（无）"
        return "\n".join(rows[-(max_turns * 2):])

    async def generate_short(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
        channel: str = "",
    ) -> str:
        """单轮短回复，用于 out_of_scope 等无需检索的场景。"""
        active_model_kind = model_id or self.model_id or "generation"
        try:
            model = get_model(active_model_kind, channel=channel)
            datetime_suffix = self._current_datetime_hint()
            if datetime_suffix:
                system_prompt = f"{system_prompt.strip()}\n\n{datetime_suffix}"
            response = await model.ainvoke(
                [
                    ("system", system_prompt),
                    ("user", user_prompt),
                ]
            )
            return self._to_text(getattr(response, "content", response))
        except ModelRequestTimeoutError:
            raise
        except Exception:
            return ""

    async def generate(
        self,
        *,
        query: str,
        intent: str,
        query_mode: str,
        chunks: Sequence[Any],
        structured_results: Sequence[StructuredTableResult] | None = None,
        messages: Sequence[Any] | None = None,
        model_id: str | None = None,
        system_suffix: str = "",
        channel: str = "",
        qa_doc: Any = None,
    ) -> str:
        active_model_kind = model_id or self.model_id or "generation"
        model = get_model(active_model_kind, channel=channel)
        chunk_texts = self._chunk_texts(chunks)
        structured_text = self._structured_results_text(list(structured_results or []))
        has_context = bool(chunk_texts or structured_text)
        context_parts: list[str] = []
        if chunk_texts:
            context_parts.append("\n".join(chunk_texts))
        if structured_text:
            context_parts.append(self._structured_results_guidance_text())
            context_parts.append(f"SQL 结构化结果：\n{structured_text}")
        context = "\n\n".join(context_parts) if context_parts else "（本轮无可用参考材料）"
        history = self._history_text(messages or [])

        system_prompt = build_generation_system_prompt(
            intent,
            query_mode,
            has_context=has_context,
            system_suffix=self._merge_suffixes(system_suffix, self._current_datetime_hint()),
        )
        user_prompt = build_generation_user_prompt(
            query=query,
            query_mode=query_mode,
            history=history,
            context=context,
            qa_doc=qa_doc,
        )

        request = [("system", system_prompt), ("user", user_prompt)]
        answer_parts: list[str] = []
        saw_stream_chunk = False
        try:
            async for chunk in model.astream(request):
                saw_stream_chunk = True
                piece = self._to_stream_piece(getattr(chunk, "content", chunk))
                if piece:
                    answer_parts.append(piece)
        except ModelRequestTimeoutError:
            raise
        except Exception:
            if not saw_stream_chunk:
                response = await model.ainvoke(request)
                return self._to_text(getattr(response, "content", response))
            return "".join(answer_parts)

        answer = "".join(answer_parts)
        if not answer:
            if not saw_stream_chunk:
                response = await model.ainvoke(request)
                return self._to_text(getattr(response, "content", response))
            return ""
        return answer


def _extract_query_from_state(state: WorkflowState) -> str:
    return shared_extract_query_from_state(state)


def _is_current_query_message(message: Any, query: str) -> bool:
    if not query:
        return False
    if isinstance(message, BaseMessage):
        msg_type = str(getattr(message, "type", "")).lower()
        if msg_type not in ("human", "user"):
            return False
        return shared_to_text(getattr(message, "content", "")) == query
    if isinstance(message, dict):
        msg_type = str(message.get("type", message.get("role", ""))).lower()
        if msg_type not in ("human", "user"):
            return False
        return shared_to_text(message.get("content", "")) == query
    return False


def _messages_for_history(
    raw_messages: Sequence[Any],
    *,
    query: str,
    max_turns: int,
) -> list[Any]:
    messages = list(raw_messages)
    if messages and _is_current_query_message(messages[-1], query):
        messages = messages[:-1]
    return messages[-(max_turns * 2) :] if messages else []


def create_generation_node(*, model_id: str | None = None):
    component = GenerationComponent(model_id=model_id)

    async def generation_node(state: WorkflowState, runtime: Runtime[Any]):
        try:
            query = _extract_query_from_state(state)
            intent = str(state.get("intent") or "").strip()
            query_mode = str(state.get("query_mode") or "").strip()
            messages_full = state.get("messages") or []
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)

            chunks = state.get("chunks") or []
            qa_doc = state.get("qa_doc")
            messages_for_history = _messages_for_history(
                messages_full,
                query=query,
                max_turns=HISTORY_LAST_K_TURNS,
            )

            channel = str(state.get("channel") or "").strip().lower()
            system_suffix = WECHAT_SYSTEM_SUFFIX if channel == "wechat" else ""

            answer = await component.generate(
                query=query,
                intent=intent,
                query_mode=query_mode,
                chunks=chunks,
                structured_results=list(state.get("structured_results") or []),
                messages=messages_for_history,
                model_id=runtime_model_id,
                system_suffix=system_suffix,
                channel=channel,
                qa_doc=qa_doc,
            )
            logger.debug(
                "Generation done.\n"
                f"intent={intent}\n"
                f"query_mode={query_mode}\n"
                f"query={query}\n"
                f"chunks={len(chunks)}\n"
                f"answer_len={len(answer)}"
            )

            result: dict[str, Any] = {"answer": answer}
            if answer:
                result["messages"] = [AIMessage(content=answer)]
            return result
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            logger.error(f"Generation error {type(exc).__name__}: {exc}")
            return {"answer": ""}

    return generation_node
