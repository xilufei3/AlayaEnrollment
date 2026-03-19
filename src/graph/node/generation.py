from __future__ import annotations

import logging
from typing import Any, Sequence

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.runtime import Runtime

from ...config.settings import HISTORY_LAST_K_TURNS
from ..llm import get_model
from ..prompts import (
    MISSING_SLOT_SHORT_FOLLOWUP_SYSTEM_PROMPT,
    OUT_OF_SCOPE_FALLBACK_ANSWER,
    OUT_OF_SCOPE_SYSTEM_PROMPT,
    build_generation_system_prompt,
    build_generation_user_prompt,
    build_missing_slot_context_suffix,
)
from ..state import WorkflowState

logger = logging.getLogger(__name__)


class GenerationComponent:
    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id

    @staticmethod
    def _to_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    else:
                        parts.append(str(item))
                else:
                    parts.append(str(item))
            return " ".join([part for part in parts if part]).strip()
        if content is None:
            return ""
        return str(content).strip()

    @staticmethod
    def _to_stream_piece(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
            return "".join(parts)
        if content is None:
            return ""
        return str(content)

    @staticmethod
    def _chunk_texts(chunks: Sequence[Any]) -> list[str]:
        lines: list[str] = []
        for index, chunk in enumerate(chunks, start=1):
            if isinstance(chunk, Document):
                text = chunk.page_content
            elif isinstance(chunk, dict):
                text = str(chunk.get("page_content") or chunk.get("content") or chunk.get("text") or "")
            else:
                text = str(chunk)
            text = text.strip()
            if text:
                lines.append(f"[{index}] {text}")
        return lines

    @staticmethod
    def _structured_results_text(rows: Sequence[dict[str, Any]]) -> str:
        lines: list[str] = []
        for i, row in enumerate(rows[:6], start=1):
            lines.append(f"[SQL {i}] {row}")
        return "\n".join(lines)

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

    def generate_short(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
    ) -> str:
        """单轮短回复，用于缺槽位追问、out_of_scope 等场景。"""
        active_model_kind = model_id or self.model_id or "generation"
        try:
            model = get_model(active_model_kind)
            response = model.invoke(
                [
                    ("system", system_prompt),
                    ("user", user_prompt),
                ]
            )
            return self._to_text(getattr(response, "content", response))
        except Exception:
            return ""

    def generate(
        self,
        *,
        query: str,
        intent: str,
        chunks: Sequence[Any],
        structured_results: Sequence[dict[str, Any]] | None = None,
        messages: Sequence[Any] | None = None,
        model_id: str | None = None,
        system_suffix: str = "",
    ) -> str:
        active_model_kind = model_id or self.model_id or "generation"
        model = get_model(active_model_kind)
        chunk_texts = self._chunk_texts(chunks)
        structured_text = self._structured_results_text(list(structured_results or []))
        has_context = bool(chunk_texts or structured_text)
        context_parts: list[str] = []
        if chunk_texts:
            context_parts.append("\n".join(chunk_texts))
        if structured_text:
            context_parts.append(f"SQL structured results:\n{structured_text}")
        context = "\n\n".join(context_parts) if context_parts else "（当前没有可用材料）"
        history = self._history_text(messages or [])

        system_prompt = build_generation_system_prompt(
            intent,
            has_context=has_context,
            system_suffix=system_suffix,
        )
        user_prompt = build_generation_user_prompt(
            query=query,
            history=history,
            context=context,
        )

        request = [("system", system_prompt), ("user", user_prompt)]
        answer_parts: list[str] = []
        saw_stream_chunk = False
        try:
            for chunk in model.stream(request):
                saw_stream_chunk = True
                piece = self._to_stream_piece(getattr(chunk, "content", chunk))
                if piece:
                    answer_parts.append(piece)
        except Exception:
            if not saw_stream_chunk:
                response = model.invoke(request)
                return self._to_text(getattr(response, "content", response))
            return "".join(answer_parts)

        answer = "".join(answer_parts)
        if not answer:
            if not saw_stream_chunk:
                response = model.invoke(request)
                return self._to_text(getattr(response, "content", response))
            return ""
        return answer


def _extract_query_from_state(state: WorkflowState) -> str:
    query = state.get("query")
    if query:
        return str(query).strip()

    messages = state.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, BaseMessage):
            if getattr(msg, "type", "") in ("human", "user"):
                text = GenerationComponent._to_text(getattr(msg, "content", ""))
                if text:
                    return text
        elif isinstance(msg, dict):
            role = str(msg.get("role", msg.get("type", ""))).lower()
            if role in ("user", "human"):
                text = GenerationComponent._to_text(msg.get("content", ""))
                if text:
                    return text
    return ""


def _normalize_messages(raw_messages: Sequence[Any]) -> list[BaseMessage]:
    normalized: list[BaseMessage] = []
    for msg in raw_messages:
        if isinstance(msg, BaseMessage):
            normalized.append(msg)
            continue
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", msg.get("type", ""))).lower()
        content = GenerationComponent._to_text(msg.get("content", ""))
        if not content:
            continue
        if role in ("user", "human"):
            normalized.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            normalized.append(AIMessage(content=content))
    return normalized


def create_generation_node(*, model_id: str | None = None):
    component = GenerationComponent(model_id=model_id)

    def generation_node(state: WorkflowState, runtime: Runtime[Any]):
        try:
            query = _extract_query_from_state(state)
            intent = str(state.get("intent") or "").strip()
            missing_slots = state.get("missing_slots") or []
            messages_full = state.get("messages") or []
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)

            # 缺槽位处理：RAG 已执行，根据是否有 chunks 选择不同策略
            chunks_for_missing = state.get("chunks") or []
            if missing_slots:
                slot_names = "、".join(missing_slots)
                if chunks_for_missing:
                    # 有检索结果：先展示示例，再引导用户补充缺少的槽位
                    suffix = build_missing_slot_context_suffix(slot_names)
                    max_msgs = HISTORY_LAST_K_TURNS * 2
                    messages_for_history = list(messages_full)[-max_msgs:] if messages_full else []
                    answer = component.generate(
                        query=query,
                        intent=intent,
                        chunks=chunks_for_missing,
                        structured_results=list(state.get("structured_results") or []),
                        messages=messages_for_history,
                        model_id=runtime_model_id,
                        system_suffix=suffix,
                    )
                    if not answer:
                        answer = f"要给你更准确的答案，还需要知道你的{slot_names}。"
                else:
                    user = (
                        f"用户问题：{query}\n"
                        f"当前缺少的信息：{slot_names}\n"
                        "请输出一句追问："
                    )
                    answer = component.generate_short(
                        system_prompt=MISSING_SLOT_SHORT_FOLLOWUP_SYSTEM_PROMPT,
                        user_prompt=user,
                        model_id=runtime_model_id,
                    )
                    if not answer:
                        answer = f"要给你更准确的答案，我还需要知道你的{slot_names}。"
                history = _normalize_messages(messages_full)
                last = history[-1] if history else None
                if query and not (
                    isinstance(last, HumanMessage)
                    and str(getattr(last, "content", "")).strip() == query
                ):
                    history.append(HumanMessage(content=query))
                history.append(AIMessage(content=answer))
                return {"answer": answer, "messages": history}

            # 超出招生范围：由大模型生成一句礼貌说明并引导
            if intent == "out_of_scope":
                user = f"用户问题：{query}\n请输出一句回复："
                answer = component.generate_short(
                    system_prompt=OUT_OF_SCOPE_SYSTEM_PROMPT,
                    user_prompt=user,
                    model_id=runtime_model_id,
                )
                if not answer:
                    answer = OUT_OF_SCOPE_FALLBACK_ANSWER
                history = _normalize_messages(messages_full)
                last = history[-1] if history else None
                if query and not (
                    isinstance(last, HumanMessage)
                    and str(getattr(last, "content", "")).strip() == query
                ):
                    history.append(HumanMessage(content=query))
                history.append(AIMessage(content=answer))
                return {"answer": answer, "messages": history, "retrieval_skipped": True}

            chunks = state.get("chunks") or []
            # 拼对话历史时只取最近 k 轮，由 config 控制
            max_msgs = HISTORY_LAST_K_TURNS * 2
            messages_for_history = list(messages_full)[-max_msgs:] if messages_full else []

            answer = component.generate(
                query=query,
                intent=intent,
                chunks=chunks,
                structured_results=list(state.get("structured_results") or []),
                messages=messages_for_history,
                model_id=runtime_model_id,
            )
            logger.debug(
                "Generation done.\n"
                f"intent={intent}\n"
                f"query={query}\n"
                f"chunks={len(chunks)}\n"
                f"answer_len={len(answer)}"
            )

            history = _normalize_messages(messages_full)
            last = history[-1] if history else None
            if query and not (
                isinstance(last, HumanMessage)
                and str(getattr(last, "content", "")).strip() == query
            ):
                history.append(HumanMessage(content=query))
            if answer:
                history.append(AIMessage(content=answer))
            return {"answer": answer, "messages": history}
        except Exception as exc:
            logger.error(f"Generation error {type(exc).__name__}: {exc}")
            return {"answer": ""}

    return generation_node
