from __future__ import annotations

import logging
import json
from typing import Any, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from ...config.settings import (
    ALLOWED_INTENTS,
    DEFAULT_FALLBACK_INTENT,
    HISTORY_LAST_K_TURNS,
    INTENT_DESCRIPTIONS,
    REQUIRED_SLOTS_BY_INTENT,
    SLOT_DESCRIPTIONS,
)
from ..llm import get_model
from ..prompts import INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
from ..state import WorkflowState


logger = logging.getLogger(__name__)

class IntentClassificationResult(BaseModel):
    intent: str = Field(..., description="intent label")
    reason: str = Field(..., description="short reason")
    confidence: float = Field(..., ge=0.0, le=1.0)
    slots: dict[str, str] = Field(default_factory=dict, description="extracted slots: province, year")


def get_missing_slots_for_intent(intent: str, slots: dict[str, str]) -> list[str]:
    required = REQUIRED_SLOTS_BY_INTENT.get(intent, [])
    missing: list[str] = []
    for name in required:
        value = str(slots.get(name, "")).strip()
        if not value:
            missing.append(name)
    return missing


class EnrollmentIntentClassifier:
    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id
        self._parser = JsonOutputParser(pydantic_object=IntentClassificationResult)
        self._prompt = ChatPromptTemplate.from_template(INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE)

    @staticmethod
    def _normalize_intent(intent: str) -> str:
        value = intent.strip().lower()
        if value in ALLOWED_INTENTS:
            return value
        return DEFAULT_FALLBACK_INTENT.value

    def classify(
        self,
        *,
        query: str,
        conversation_context: Sequence[Any] = (),
        model_id: str | None = None,
    ) -> IntentClassificationResult:
        active_model_kind = model_id or self.model_id or "intent"
        model = get_model(active_model_kind)
        system_prompt = self._prompt.format_prompt(
            intent_descriptions=json.dumps(INTENT_DESCRIPTIONS, ensure_ascii=False, indent=2),
            slot_descriptions=json.dumps(SLOT_DESCRIPTIONS, ensure_ascii=False, indent=2),
        )
        system_str = system_prompt.to_string()
        user_tail = f"当前用户问题：{query}\n{self._parser.get_format_instructions()}"
        history = _normalize_conversation_messages(conversation_context)
        messages: list[BaseMessage] = [
            SystemMessage(content=system_str),
            *history,
            HumanMessage(content=user_tail),
        ]
        response = model.invoke(messages, response_format={"type": "json_object"})
        data = self._parser.parse(response.content)

        if not isinstance(data, dict):
            raise ValueError("intent classify output is not a JSON object")

        intent = self._normalize_intent(str(data.get("intent", "")))
        reason = str(data.get("reason", "")).strip()
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        raw_slots = data.get("slots")
        if isinstance(raw_slots, dict):
            slots = {k: str(v).strip() for k, v in raw_slots.items() if v and str(v).strip()}
        else:
            slots = {}

        return IntentClassificationResult(
            intent=intent,
            reason=reason,
            confidence=confidence,
            slots=slots,
        )


def _to_text(content: Any) -> str:
    if isinstance(content, str):
        return content.strip()
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
            elif isinstance(item, dict) and "text" in item:
                parts.append(str(item["text"]))
            else:
                parts.append(str(item))
        return " ".join([part for part in parts if part]).strip()
    if content is None:
        return ""
    return str(content).strip()


def _normalize_conversation_messages(raw: Sequence[Any]) -> list[BaseMessage]:
    """把对话上下文转为 BaseMessage 列表，供模型多轮调用。"""
    out: list[BaseMessage] = []
    for msg in raw:
        if isinstance(msg, BaseMessage):
            out.append(msg)
            continue
        if not isinstance(msg, dict):
            continue
        role = str(msg.get("role", msg.get("type", ""))).lower()
        content = _to_text(msg.get("content", ""))
        if not content:
            continue
        if role in ("user", "human"):
            out.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            out.append(AIMessage(content=content))
    return out


def _get_recent_messages(state: WorkflowState, max_turns: int | None = None) -> list[Any]:
    """从 state["messages"] 取当前问题之前的最近 max_turns 轮，返回原始消息列表（不转 str）。"""
    messages = state.get("messages") or []
    if not messages:
        return []
    k = max_turns if max_turns is not None else HISTORY_LAST_K_TURNS
    previous = messages[:-1]
    if not previous:
        return []
    return list(previous)[-(k * 2) :]


def _extract_query_from_state(state: WorkflowState) -> str:
    query = state.get("query")
    if query:
        return str(query).strip()

    messages = state.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, BaseMessage):
            if getattr(msg, "type", "") in ("human", "user"):
                text = _to_text(getattr(msg, "content", ""))
                if text:
                    return text
        elif isinstance(msg, dict):
            role = str(msg.get("role", "")).lower()
            if role in ("user", "human"):
                text = _to_text(msg.get("content", ""))
                if text:
                    return text
    return ""


def create_intent_classify_node(*, model_id: str | None = None):
    classifier = EnrollmentIntentClassifier(model_id=model_id)

    def intent_classify_node(state: WorkflowState, runtime: Runtime[Any]):
        query = _extract_query_from_state(state)
        conversation_context = _get_recent_messages(state)

        try:
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)
            result = classifier.classify(
                query=query,
                conversation_context=conversation_context,
                model_id=runtime_model_id,
            )
            intent = result.intent
            confidence = result.confidence
            slots = dict(result.slots or {})
            logger.debug(
                "Intent classified.\n"
                f"intent={result.intent}\n"
                f"confidence={result.confidence:.2f}\n"
                f"reason={result.reason}\n"
                f"slots={slots}"
            )
        except Exception as exc:
            intent = DEFAULT_FALLBACK_INTENT.value
            confidence = 0.0
            slots = {}
            logger.warning(
                "Intent classify failed, use fallback.\n"
                f"error={type(exc).__name__}: {exc}\n"
                f"fallback_intent={intent}"
            )

        merged_slots = dict(state.get("slots") or {})
        merged_slots.update(slots)
        missing_slots = get_missing_slots_for_intent(intent, merged_slots)
        return {
            "query": query,
            "intent": intent,
            "confidence": confidence,
            "slots": merged_slots,
            "missing_slots": missing_slots,
        }

    return intent_classify_node
