from __future__ import annotations

import logging
import json
from typing import Any, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from ...config.settings import (
    ALLOWED_INTENTS,
    ALLOWED_QUERY_MODES,
    DEFAULT_FALLBACK_INTENT,
    DEFAULT_QUERY_MODE,
    HISTORY_LAST_K_TURNS,
    INTENT_DESCRIPTIONS,
    QUERY_MODE_DESCRIPTIONS,
    SLOT_DESCRIPTIONS,
)
from ..llm import ModelRequestTimeoutError, get_model
from ..prompts.intent_classify import INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
from ..state import WorkflowState
from ..utils import (
    extract_year_slot_from_query,
    extract_query_from_state as shared_extract_query_from_state,
    normalize_messages as shared_normalize_messages,
    to_text as shared_to_text,
)


logger = logging.getLogger(__name__)
GLOBAL_SLOT_NAMES: tuple[str, ...] = ("province", "year")

class IntentClassificationResult(BaseModel):
    intent: str = Field(..., description="intent label")
    query_mode: str = Field(..., description="question shape label")
    reason: str = Field(..., description="short reason")
    confidence: float = Field(..., ge=0.0, le=1.0)
    slots: dict[str, str] = Field(default_factory=dict, description="extracted slots: province, year")
    required_slots: list[str] = Field(
        default_factory=list,
        description="query-aware slots needed for a more precise answer",
    )


def normalize_slots(raw_slots: Any) -> dict[str, str]:
    if not isinstance(raw_slots, dict):
        return {}

    slots: dict[str, str] = {}
    for raw_name, value in raw_slots.items():
        name = str(raw_name).strip().lower()
        if name not in GLOBAL_SLOT_NAMES:
            continue
        if value is None:
            continue
        text = str(value).strip()
        if text:
            slots[name] = text
    return slots


def normalize_required_slots(raw_required_slots: Any) -> list[str]:
    if not isinstance(raw_required_slots, list):
        return []

    required_slots: list[str] = []
    for item in raw_required_slots:
        name = str(item).strip().lower()
        if name in GLOBAL_SLOT_NAMES and name not in required_slots:
            required_slots.append(name)
    return required_slots


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

    @staticmethod
    def _normalize_query_mode(query_mode: str) -> str:
        value = query_mode.strip().lower()
        if value in ALLOWED_QUERY_MODES:
            return value
        return DEFAULT_QUERY_MODE.value

    async def classify(
        self,
        *,
        query: str,
        conversation_context: Sequence[Any] = (),
        model_id: str | None = None,
        channel: str = "",
    ) -> IntentClassificationResult:
        active_model_kind = model_id or self.model_id or "intent"
        model = get_model(active_model_kind, channel=channel)
        system_prompt = self._prompt.format_prompt(
            intent_descriptions=json.dumps(INTENT_DESCRIPTIONS, ensure_ascii=False, indent=2),
            query_mode_descriptions=json.dumps(
                QUERY_MODE_DESCRIPTIONS,
                ensure_ascii=False,
                indent=2,
            ),
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
        response = await model.ainvoke(messages, response_format={"type": "json_object"})
        data = self._parser.parse(response.content)

        if not isinstance(data, dict):
            raise ValueError("intent classify output is not a JSON object")

        intent = self._normalize_intent(str(data.get("intent", "")))
        query_mode = self._normalize_query_mode(str(data.get("query_mode", "")))
        reason = str(data.get("reason", "")).strip()
        try:
            confidence = float(data.get("confidence", 0.0))
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))

        slots = normalize_slots(data.get("slots"))
        required_slots = normalize_required_slots(data.get("required_slots"))

        return IntentClassificationResult(
            intent=intent,
            query_mode=query_mode,
            reason=reason,
            confidence=confidence,
            slots=slots,
            required_slots=required_slots,
        )


def _to_text(content: Any) -> str:
    return shared_to_text(content)


def _normalize_conversation_messages(raw: Sequence[Any]) -> list[BaseMessage]:
    """把对话上下文转为 BaseMessage 列表，供模型多轮调用。"""
    return shared_normalize_messages(raw)


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
    return shared_extract_query_from_state(state)


def create_intent_classify_node(*, model_id: str | None = None):
    classifier = EnrollmentIntentClassifier(model_id=model_id)

    async def intent_classify_node(state: WorkflowState, runtime: Runtime[Any]):
        query = _extract_query_from_state(state)
        conversation_context = _get_recent_messages(state)

        try:
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)
            channel = str(state.get("channel") or "").strip().lower()
            result = await classifier.classify(
                query=query,
                conversation_context=conversation_context,
                model_id=runtime_model_id,
                channel=channel,
            )
            intent = result.intent
            query_mode = result.query_mode
            confidence = result.confidence
            slots = dict(result.slots or {})
            required_slots = list(result.required_slots or [])
            logger.debug(
                "Intent classified.\n"
                f"intent={result.intent}\n"
                f"query_mode={result.query_mode}\n"
                f"confidence={result.confidence:.2f}\n"
                f"reason={result.reason}\n"
                f"slots={slots}\n"
                f"required_slots={required_slots}"
            )
        except ModelRequestTimeoutError:
            raise
        except Exception as exc:
            intent = DEFAULT_FALLBACK_INTENT.value
            query_mode = DEFAULT_QUERY_MODE.value
            confidence = 0.0
            slots = {}
            required_slots = []
            logger.warning(
                "Intent classify failed, use fallback.\n"
                f"error={type(exc).__name__}: {exc}\n"
                f"fallback_intent={intent}"
            )

        current_query_year = extract_year_slot_from_query(query)
        if current_query_year:
            slots["year"] = current_query_year
        else:
            slots.pop("year", None)

        merged_slots = normalize_slots(state.get("slots") or {})
        merged_slots.update(slots)
        if current_query_year:
            merged_slots["year"] = current_query_year
        else:
            merged_slots.pop("year", None)
        return {
            "query": query,
            "intent": intent,
            "query_mode": query_mode,
            "confidence": confidence,
            "slots": merged_slots,
            "required_slots": required_slots,
            "missing_slots": [],
        }

    return intent_classify_node
