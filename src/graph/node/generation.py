from __future__ import annotations

import logging
from typing import Any, Sequence

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.runtime import Runtime

from ...config.settings import HISTORY_LAST_K_TURNS
from ..llm import ModelRequestTimeoutError, get_model
from ..state import WorkflowState
from ..utils import (
    chunk_texts as shared_chunk_texts,
    extract_query_from_state as shared_extract_query_from_state,
    to_stream_piece as shared_to_stream_piece,
    to_text as shared_to_text,
)

logger = logging.getLogger(__name__)

_GRAD_SYSTEM_PROMPT = """
你是“南方科技大学研究生招生与培养助手”。

【职责范围】
- 仅回答与南科大研究生招生、学籍、培养、学位、奖助、导师选择、论文答辩及在校管理相关的问题。
- 面向研究生考生与在读研究生，提供政策解读、流程说明和材料梳理。

【信息来源要求】
- 只能依据提供的参考材料、学校正式通知、教育主管部门正式文件作答。
- 严禁编造分数线、名额、日期、费用、政策条款、联系方式或办事流程细节。
- 若参考材料之间存在冲突或表述不完整，必须明确说明“不确定/信息不足”，并提示以最新官方通知为准。

【回答要求】
- 默认使用中文，语气专业、友好、克制，避免营销化表达。
- 优先直接回答用户问题，再补充依据、条件限制或操作步骤。
- 涉及流程类问题时，优先使用分点或分步骤表达。
- 涉及政策适用条件时，要明确前提、对象和可能的例外情况。
- 若用户一次提多个问题，按主题分点回答，避免遗漏。

【禁止事项】
- 不要臆测学校尚未公布的信息。
- 不要把本科招生政策混入研究生语境。
- 不要输出“我是 AI”之类与任务无关的自我描述。
""".strip()

_NO_RETRIEVAL_SUFFIX = """
【额外约束】
当前没有检索到可直接支撑答案的参考材料。
- 不得补充未经证实的具体政策或数字。
- 若只能给出原则性建议，请明确说明“需以南科大研究生院/研究生招生官网最新通知为准”。
- 必要时引导用户查看官方公告、招生简章、培养方案或联系对应培养单位/研招办。
""".strip()

_OUT_OF_SCOPE_SYSTEM_PROMPT = """
你是南方科技大学研究生招生与培养助手的范围提醒模块。

任务：
- 判断到用户问题不属于南科大研究生招生与培养相关范围后，输出一句简短回复。

回复要求：
- 仅用一句中文回复，控制在 60 字以内。
- 先说明你的职责范围，再自然邀请用户提问研究生相关问题。
- 不要展开解释，不要给出与问题无关的建议。
""".strip()


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

        system_prompt = _GRAD_SYSTEM_PROMPT
        if not has_context:
            system_prompt += _NO_RETRIEVAL_SUFFIX
        if system_suffix:
            system_prompt += "\n\n" + system_suffix

        user_prompt = (
            "请基于给定材料生成最终回复。\n\n"
            f"【当前问题】\n{query}\n\n"
            f"【最近对话历史】\n{history}\n\n"
            f"【参考材料】\n{context}\n\n"
            "请遵循以下输出原则：\n"
            "1. 先给出直接结论；\n"
            "2. 再补充依据、条件或操作步骤；\n"
            "3. 若材料不足，明确说明不足之处，并提示用户以官方最新通知为准。"
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
                    system_prompt=_OUT_OF_SCOPE_SYSTEM_PROMPT,
                    user_prompt=f"用户问题：{query}\n请输出一句回复：",
                    model_id=runtime_model_id,
                )
                if not answer:
                    answer = "我主要解答南科大研究生招生与培养相关问题，欢迎告诉我想了解的项目、流程或政策。"

                result: dict[str, Any] = {"answer": answer}
                if answer:
                    result["messages"] = [AIMessage(content=answer)]
                return result

            chunks = state.get("chunks") or []
            messages_for_history = _messages_for_history(
                messages_full,
                query=query,
                max_turns=HISTORY_LAST_K_TURNS,
            )

            answer = await component.generate(
                query=query,
                chunks=chunks,
                messages=messages_for_history,
                model_id=runtime_model_id,
            )
            logger.debug(
                "Generation done.\n"
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
