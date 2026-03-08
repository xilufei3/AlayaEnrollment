from __future__ import annotations

import json
from typing import Any

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from alayaflow.component.model import ModelManager
from alayaflow.utils.logger import AlayaFlowLogger

from ..config import ALLOWED_INTENTS, DEFAULT_FALLBACK_INTENT, INTENT_DESCRIPTIONS
from ..schemas import WorkflowState


logger = AlayaFlowLogger()

INTENT_PROMPT_TEMPLATE = """
你是南科大招生咨询智能体的意图识别模块。你的任务是把用户问题严格分类为一个意图标签。
可选意图及定义如下（键为 intent，值为定义）：
{intent_descriptions}

分类要求：
1. 只能返回一个 intent，且必须来自上面的可选意图。
2. 同时给出简短 reason（不超过40字）和 confidence（0到1之间的小数）。
3. 输出必须是 JSON 对象，字段为: intent, reason, confidence。
4. 如果问题不完整或存在歧义，选择最接近的意图。
"""


class IntentClassificationResult(BaseModel):
    intent: str = Field(..., description="intent label")
    reason: str = Field(..., description="short reason")
    confidence: float = Field(..., ge=0.0, le=1.0)


class EnrollmentIntentClassifier:
    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id
        self._model_manager = ModelManager()
        self._parser = JsonOutputParser(pydantic_object=IntentClassificationResult)
        self._prompt = ChatPromptTemplate.from_template(INTENT_PROMPT_TEMPLATE)

    @staticmethod
    def _normalize_intent(intent: str) -> str:
        value = intent.strip().lower()
        if value in ALLOWED_INTENTS:
            return value
        return DEFAULT_FALLBACK_INTENT.value

    def classify(self, *, query: str, model_id: str | None = None) -> IntentClassificationResult:
        active_model_id = model_id or self.model_id
        if not active_model_id:
            raise ValueError("intent classify model_id is required")

        model = self._model_manager.get_model(active_model_id)
        system_prompt = self._prompt.format_prompt(
            intent_descriptions=json.dumps(INTENT_DESCRIPTIONS, ensure_ascii=False, indent=2)
        )
        user_prompt = f"用户问题：{query}\n{self._parser.get_format_instructions()}"

        response = model.invoke(
            [("system", system_prompt.to_string()), ("user", user_prompt)],
            response_format={"type": "json_object"},
        )
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

        return IntentClassificationResult(
            intent=intent,
            reason=reason,
            confidence=confidence,
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
        return " ".join([p for p in parts if p]).strip()
    if content is None:
        return ""
    return str(content).strip()


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


def create_intend_classify_node(*, model_id: str | None = None):
    classifier = EnrollmentIntentClassifier(model_id=model_id)

    def intend_classify_node(state: WorkflowState, runtime: Runtime[Any]):
        try:
            query = _extract_query_from_state(state)
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)
            result = classifier.classify(query=query, model_id=runtime_model_id)
            logger.debug(
                "Intent classified.\n"
                f"intent={result.intent}\n"
                f"confidence={result.confidence:.2f}\n"
                f"reason={result.reason}"
            )
            return {"intent": result.intent}
        except Exception as exc:
            fallback_intent = DEFAULT_FALLBACK_INTENT.value
            logger.warning(
                "Intent classify failed, use fallback.\n"
                f"error={type(exc).__name__}: {exc}\n"
                f"fallback_intent={fallback_intent}"
            )
            return {"intent": fallback_intent}

    return intend_classify_node
