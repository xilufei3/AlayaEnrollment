from __future__ import annotations

import logging
from typing import Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.runtime import Runtime

from ...config.settings import HISTORY_LAST_K_TURNS
from ..llm import ModelRequestTimeoutError, get_model
from ..prompts.generation import (
    GRAD_SYSTEM_PROMPT,
    NO_RETRIEVAL_SUFFIX,
    OUT_OF_SCOPE_FALLBACK_ANSWER,
    OUT_OF_SCOPE_SYSTEM_PROMPT,
    build_generation_user_prompt,
    build_out_of_scope_user_prompt,
)
from ..state import WorkflowState
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
    def _to_text(content: Any) -> str:
        return shared_to_text(content)

    @staticmethod
    def _to_stream_piece(content: Any) -> str:
        return shared_to_stream_piece(content)

    @staticmethod
    def _chunk_texts(chunks: Sequence[Any]) -> list[str]:
        return shared_chunk_texts(chunks)

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
    ) -> str:
        """单轮短回复，用于范围外兜底等场景。"""
        active_model_kind = model_id or self.model_id or "generation"
        try:
            model = get_model(active_model_kind)
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
        reply_mode: str = "hat",
        chunks: Sequence[Any],
        messages: Sequence[Any] | None = None,
        model_id: str | None = None,
        system_suffix: str = "",
    ) -> str:
        active_model_kind = model_id or self.model_id or "generation"
        model = get_model(active_model_kind)
        chunk_texts = self._chunk_texts(chunks)
        has_context = bool(chunk_texts)
        context = "\n".join(chunk_texts) if has_context else "（无检索文档）"
        history = self._history_text(messages or [])

        system_prompt = GRAD_SYSTEM_PROMPT
        if not has_context:
            system_prompt += NO_RETRIEVAL_SUFFIX
        if system_suffix:
            system_prompt += "\n\n" + system_suffix

        user_prompt = build_generation_user_prompt(
            query=query,
            history=history,
            context=context,
            reply_mode=reply_mode,
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
            messages_full = state.get("messages") or []
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)
            in_scope = state.get("in_scope")

            if in_scope is False:
                answer = await component.generate_short(
                    system_prompt=OUT_OF_SCOPE_SYSTEM_PROMPT,
                    user_prompt=build_out_of_scope_user_prompt(query),
                    model_id=runtime_model_id,
                )
                if not answer:
                    answer = OUT_OF_SCOPE_FALLBACK_ANSWER

                result: dict[str, Any] = {"answer": answer}
                if answer:
                    result["messages"] = [AIMessage(content=answer)]
                return result

            chunks = state.get("chunks") or []
            reply_mode = str(state.get("reply_mode") or "hat").strip().lower()
            if reply_mode not in {"hat", "expand"}:
                reply_mode = "hat"
            messages_for_history = _messages_for_history(
                messages_full,
                query=query,
                max_turns=HISTORY_LAST_K_TURNS,
            )

            answer = await component.generate(
                query=query,
                reply_mode=reply_mode,
                chunks=chunks,
                messages=messages_for_history,
                model_id=runtime_model_id,
            )
            logger.debug(
                "Generation done.\n"
                f"query={query}\n"
                f"reply_mode={reply_mode}\n"
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
