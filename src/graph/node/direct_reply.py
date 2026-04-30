from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from ..prompts.direct_reply import get_direct_reply_prompt_bundle
from ..state import WorkflowState
from ..utils import extract_query_from_state as shared_extract_query_from_state
from .generation import GenerationComponent

logger = logging.getLogger(__name__)


def create_direct_reply_node(*, model_id: str | None = None):
    component = GenerationComponent(model_id=model_id)

    async def direct_reply_node(state: WorkflowState, runtime: Runtime[Any]):
        query = shared_extract_query_from_state(state)
        intent = str(state.get("intent") or "").strip()
        channel = str(state.get("channel") or "").strip().lower()
        runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)
        system_prompt, fallback_answer = get_direct_reply_prompt_bundle(intent)

        user = query
        answer = await component.generate_short(
            system_prompt=system_prompt,
            user_prompt=user,
            model_id=runtime_model_id,
            channel=channel,
        )
        if not answer:
            answer = fallback_answer

        logger.debug(
            "DirectReply done. intent=%s query=%s answer_len=%s",
            intent,
            query,
            len(answer),
        )
        result: dict[str, Any] = {"answer": answer}
        if answer:
            result["messages"] = [AIMessage(content=answer)]
        return result

    return direct_reply_node
