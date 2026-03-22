from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from ...config.settings import HISTORY_LAST_K_TURNS
from ..prompts import (
    MISSING_SLOT_SHORT_FOLLOWUP_SYSTEM_PROMPT,
    build_missing_slot_context_suffix,
)
from ..state import WorkflowState
from ..utils import extract_query_from_state as shared_extract_query_from_state
from .generation import GenerationComponent, _messages_for_history

logger = logging.getLogger(__name__)


def create_slot_followup_node(*, model_id: str | None = None):
    component = GenerationComponent(model_id=model_id)

    async def slot_followup_node(state: WorkflowState, runtime: Runtime[Any]):
        query = shared_extract_query_from_state(state)
        intent = str(state.get("intent") or "").strip()
        missing_slots = state.get("missing_slots") or []
        chunks = state.get("chunks") or []
        messages_full = state.get("messages") or []
        runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)

        slot_names = "、".join(missing_slots)

        if chunks:
            # 有检索结果：先展示一般性参考，再引导用户补充缺少的槽位
            suffix = build_missing_slot_context_suffix(slot_names)
            messages_for_history = _messages_for_history(
                messages_full,
                query=query,
                max_turns=HISTORY_LAST_K_TURNS,
            )
            answer = await component.generate(
                query=query,
                intent=intent,
                chunks=chunks,
                structured_results=list(state.get("structured_results") or []),
                messages=messages_for_history,
                model_id=runtime_model_id,
                system_suffix=suffix,
            )
            if not answer:
                answer = f"要给你更准确的答案，还需要知道你的{slot_names}。"
        else:
            # 无检索结果：直接追问
            user = (
                f"用户问题：{query}\n"
                f"当前缺少的信息：{slot_names}\n"
                "请输出一句追问："
            )
            answer = await component.generate_short(
                system_prompt=MISSING_SLOT_SHORT_FOLLOWUP_SYSTEM_PROMPT,
                user_prompt=user,
                model_id=runtime_model_id,
            )
            if not answer:
                answer = f"要给你更准确的答案，我还需要知道你的{slot_names}。"

        logger.debug(
            "SlotFollowup done.\n"
            f"missing_slots={missing_slots}\n"
            f"has_chunks={bool(chunks)}\n"
            f"answer_len={len(answer)}"
        )
        result: dict[str, Any] = {"answer": answer}
        if answer:
            result["messages"] = [AIMessage(content=answer)]
        return result

    return slot_followup_node
