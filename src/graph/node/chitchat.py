from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from ..state import WorkflowState
from ..utils import extract_query_from_state as shared_extract_query_from_state
from .generation import GenerationComponent

logger = logging.getLogger(__name__)

_CHITCHAT_SYSTEM_PROMPT = """
你是南方科技大学本科招生咨询助手。
用户在打招呼或闲聊。
请用亲切、简短的一句话回应，并顺势引导用户继续咨询本科招生相关问题。
控制在 50 字以内，不要罗列信息。
""".strip()

_CHITCHAT_FALLBACK_ANSWER = "你好！我是南科大招生咨询助手，有什么关于本科招生的问题可以问我。"


def create_chitchat_node(*, model_id: str | None = None):
    component = GenerationComponent(model_id=model_id)

    async def chitchat_node(state: WorkflowState, runtime: Runtime[Any]):
        query = shared_extract_query_from_state(state)
        runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)

        user = f"用户问题：{query}\n请输出一句回复："
        answer = await component.generate_short(
            system_prompt=_CHITCHAT_SYSTEM_PROMPT,
            user_prompt=user,
            model_id=runtime_model_id,
        )
        if not answer:
            answer = _CHITCHAT_FALLBACK_ANSWER

        logger.debug(f"Chitchat done. query={query} answer_len={len(answer)}")
        result: dict[str, Any] = {"answer": answer, "retrieval_skipped": True}
        if answer:
            result["messages"] = [AIMessage(content=answer)]
        return result

    return chitchat_node
