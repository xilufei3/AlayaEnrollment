from __future__ import annotations

import logging
from typing import Any

from langchain_core.messages import AIMessage
from langgraph.runtime import Runtime

from ..prompts import OUT_OF_SCOPE_FALLBACK_ANSWER, OUT_OF_SCOPE_SYSTEM_PROMPT
from ..state import WorkflowState
from ..utils import extract_query_from_state as shared_extract_query_from_state
from .generation import GenerationComponent

logger = logging.getLogger(__name__)


def create_out_of_scope_node(*, model_id: str | None = None):
    component = GenerationComponent(model_id=model_id)

    async def out_of_scope_node(state: WorkflowState, runtime: Runtime[Any]):
        query = shared_extract_query_from_state(state)
        runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)

        user = f"用户问题：{query}\n请输出一句回复："
        answer = await component.generate_short(
            system_prompt=OUT_OF_SCOPE_SYSTEM_PROMPT,
            user_prompt=user,
            model_id=runtime_model_id,
        )
        if not answer:
            answer = OUT_OF_SCOPE_FALLBACK_ANSWER

        logger.debug(f"OutOfScope done. query={query} answer_len={len(answer)}")
        result: dict[str, Any] = {"answer": answer, "retrieval_skipped": True}
        if answer:
            result["messages"] = [AIMessage(content=answer)]
        return result

    return out_of_scope_node
