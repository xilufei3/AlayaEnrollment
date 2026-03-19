from __future__ import annotations

import logging
from typing import Any, Sequence

from langchain_core.messages import BaseMessage, HumanMessage, AIMessage, SystemMessage
from langchain_core.output_parsers import JsonOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langgraph.runtime import Runtime
from pydantic import BaseModel, Field

from ..llm import get_model
from ...config.settings import HISTORY_LAST_K_TURNS
from ..state import WorkflowState


logger = logging.getLogger(__name__)

INTENT_PROMPT_TEMPLATE = """
你是“南方科技大学研究生招生与培养助手”的领域相关性判断模块。

【任务】
判断当前用户问题是否属于以下范围：
- 研究生招生：推免、统考、报名、复试、调剂、导师、招生专业、招生政策等；
- 研究生培养与在校事务：培养方案、选课、奖助、学籍、学位、论文、答辩、毕业要求、学生管理等。

【判定标准】
- `in_scope = true`：问题与南科大研究生招生、培养或在校管理直接相关；或者问题虽表述简略，但结合上下文可合理判断为相关。
- `in_scope = false`：问题明显与上述范围无关，例如本科招生、通用闲聊、与南科大研究生事务无关的社会常识、编程问题、娱乐话题等。

【注意事项】
- 你只判断“是否属于系统处理范围”，不要判断“是否容易回答”。
- 若问题存在省略、代词或承接上一轮上下文的情况，要结合提供的对话历史理解。
- 若无法完全确定，请优先判为 `in_scope = true`，交给后续检索与生成模块处理。

【输出要求】
严格输出 JSON，且只能包含以下字段：
- `in_scope`: 布尔值
- `reason`: 不超过 30 字的简短理由
- `confidence`: 0 到 1 之间的浮点数
""".strip()


class ScopeClassificationResult(BaseModel):
    in_scope: bool = Field(..., description="whether the query is within SUSTech graduate scope")
    reason: str = Field(default="", description="short reason")
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)


class GraduateIntentClassifier:
    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id
        self._parser = JsonOutputParser(pydantic_object=ScopeClassificationResult)
        self._prompt = ChatPromptTemplate.from_template(INTENT_PROMPT_TEMPLATE)

    def classify(
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
        messages: list[BaseMessage] = [
            SystemMessage(content=system_str),
            *history,
            HumanMessage(content=user_tail),
        ]
        response = model.invoke(messages, response_format={"type": "json_object"})
        data = self._parser.parse(response.content)

        if not isinstance(data, dict):
            raise ValueError("intent gate output is not a JSON object")

        in_scope = bool(data.get("in_scope", True))
        reason = str(data.get("reason", "")).strip()
        try:
            confidence = float(data.get("confidence", 1.0))
        except (TypeError, ValueError):
            confidence = 1.0
        confidence = max(0.0, min(1.0, confidence))

        return ScopeClassificationResult(
            in_scope=in_scope,
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
    classifier = GraduateIntentClassifier(model_id=model_id)

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
            in_scope = bool(result.in_scope)
            logger.debug(
                "Intent gate classified.\n"
                f"in_scope={in_scope}\n"
                f"confidence={result.confidence:.2f}\n"
                f"reason={result.reason}"
            )
        except Exception as exc:
            in_scope = True
            logger.warning(
                "Intent gate failed, default to in_scope.\n"
                f"error={type(exc).__name__}: {exc}"
            )

        return {
            "query": query,
            "in_scope": in_scope,
        }

    return intent_classify_node
