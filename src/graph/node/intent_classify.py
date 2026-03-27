from __future__ import annotations

import logging
from typing import Any, Literal, Sequence

from langchain_core.messages import HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from ...config.settings import HISTORY_LAST_K_TURNS
from ..llm import ModelRequestTimeoutError, get_model
from ..prompts.intent_classify import INTENT_PROMPT_TEMPLATE
from ..state import WorkflowState
from ..utils import (
    extract_query_from_state as shared_extract_query_from_state,
    normalize_messages as shared_normalize_messages,
)


logger = logging.getLogger(__name__)


class ScopeClassificationResult(BaseModel):
    in_scope: bool = Field(..., description="whether the query is within SUSTech graduate scope")
    reply_mode: Literal["hat", "expand"] = Field(
        default="hat",
        description="reply style mode inferred from conversation history",
    )
    reason: str = Field(default="", description="short reason")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GraduateIntentClassifier:
    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id
        self._parser = JsonOutputParser(pydantic_object=ScopeClassificationResult)
        self._prompt = ChatPromptTemplate.from_template(INTENT_PROMPT_TEMPLATE)

    async def classify(
        self,
        *,
        query: str,
        conversation_context: Sequence[Any] = (),
        model_id: str | None = None,
    ) -> ScopeClassificationResult:
        active_model_kind = model_id or self.model_id or "intent"
        model = get_model(active_model_kind)
        system_prompt = self._prompt.format_prompt()
        system_str = system_prompt.to_string()
        user_tail = f"当前用户问题：{query}\n{self._parser.get_format_instructions()}"
        history = _normalize_conversation_messages(conversation_context)
        messages = [
            SystemMessage(content=system_str),
            *history,
            HumanMessage(content=user_tail),
        ]
        response = await model.ainvoke(messages, response_format={"type": "json_object"})
        data = self._parser.parse(response.content)

        if not isinstance(data, dict):
            raise ValueError("intent gate output is not a JSON object")

        in_scope = bool(data.get("in_scope", True))
        reply_mode_raw = str(data.get("reply_mode", "hat")).strip().lower()
        reply_mode: Literal["hat", "expand"] = (
            "expand" if reply_mode_raw == "expand" else "hat"
        )
        reason = str(data.get("reason", "")).strip()
        try:
            confidence = float(data.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        confidence = max(0.0, min(1.0, confidence))

        return ScopeClassificationResult(
            in_scope=in_scope,
            reply_mode=reply_mode,
            reason=reason,
            confidence=confidence,
        )


def _normalize_conversation_messages(raw: Sequence[Any]):
    return shared_normalize_messages(raw)


def _get_recent_messages(state: WorkflowState, max_turns: int | None = None) -> list[Any]:
    messages = state.get("messages") or []
    if not messages:
        return []
    k = max_turns if max_turns is not None else HISTORY_LAST_K_TURNS
    previous = messages[:-1]
    if not previous:
        return []
    return list(previous)[-(k * 2) :]


def _extract_query_from_state(state: WorkflowState) -> str:
    return shared_extract_query_from_state(state)


def create_intent_classify_node(*, model_id: str | None = None):
    classifier = GraduateIntentClassifier(model_id=model_id)

    async def intent_classify_node(state: WorkflowState, runtime: Runtime[Any]):
        query = _extract_query_from_state(state)
        conversation_context = _get_recent_messages(state)

        try:
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)
            result = await classifier.classify(
                query=query,
                conversation_context=conversation_context,
                model_id=runtime_model_id,
            )
            in_scope = bool(result.in_scope)
            reply_mode = result.reply_mode
            logger.debug(
                "Intent gate classified.\n"
                f"in_scope={in_scope}\n"
                f"reply_mode={reply_mode}\n"
                f"confidence={result.confidence:.2f}\n"
                f"reason={result.reason}"
            )
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            in_scope = True
            reply_mode = "hat"
            logger.warning(
                "Intent gate failed, default to in_scope.\n"
                f"error={type(exc).__name__}: {exc}"
            )

        return {
            "query": query,
            "in_scope": in_scope,
            "reply_mode": reply_mode,
        }

    return intent_classify_node
