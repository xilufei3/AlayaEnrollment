from __future__ import annotations

from typing import Any, Sequence

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.runtime import Runtime

from alayaflow.component.model import ModelManager
from alayaflow.utils.logger import AlayaFlowLogger

from ..schemas import WorkflowState


logger = AlayaFlowLogger()


class GenerationComponent:
    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id
        self._model_manager = ModelManager()

    @staticmethod
    def _to_text(content: Any) -> str:
        if isinstance(content, str):
            return content.strip()
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
                    else:
                        parts.append(str(item))
                else:
                    parts.append(str(item))
            return " ".join([p for p in parts if p]).strip()
        if content is None:
            return ""
        return str(content).strip()

    @staticmethod
    def _to_stream_piece(content: Any) -> str:
        if isinstance(content, str):
            return content
        if isinstance(content, list):
            parts: list[str] = []
            for item in content:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    if "text" in item:
                        parts.append(str(item["text"]))
                    elif item.get("type") == "text":
                        parts.append(str(item.get("text", "")))
            return "".join(parts)
        if content is None:
            return ""
        return str(content)

    @staticmethod
    def _chunk_texts(chunks: Sequence[Any]) -> list[str]:
        lines: list[str] = []
        for i, chunk in enumerate(chunks, start=1):
            if isinstance(chunk, Document):
                text = chunk.page_content
            elif isinstance(chunk, dict):
                text = str(chunk.get("page_content") or chunk.get("content") or chunk.get("text") or "")
            else:
                text = str(chunk)
            text = text.strip()
            if text:
                lines.append(f"[{i}] {text}")
        return lines

    @classmethod
    def _history_text(cls, messages: Sequence[Any], max_turns: int = 6) -> str:
        rows: list[str] = []
        for msg in messages:
            role = ""
            content: Any = ""
            if isinstance(msg, BaseMessage):
                t = str(getattr(msg, "type", "")).lower()
                if t in ("human", "user"):
                    role = "user"
                elif t in ("ai", "assistant"):
                    role = "assistant"
                content = getattr(msg, "content", "")
            elif isinstance(msg, dict):
                t = str(msg.get("type", msg.get("role", ""))).lower()
                if t in ("human", "user"):
                    role = "user"
                elif t in ("ai", "assistant"):
                    role = "assistant"
                content = msg.get("content", "")
            if not role:
                continue
            text = cls._to_text(content)
            if text:
                rows.append(f"{role}: {text}")

        if not rows:
            return "(none)"
        return "\n".join(rows[-(max_turns * 2) :])

    def generate(
        self,
        *,
        query: str,
        intent: str,
        chunks: Sequence[Any],
        messages: Sequence[Any] | None = None,
        model_id: str | None = None,
    ) -> str:
        active_model_id = model_id or self.model_id
        if not active_model_id:
            raise ValueError("generation model_id is required")

        model = self._model_manager.get_model(active_model_id)
        context = "\n".join(self._chunk_texts(chunks))
        if not context:
            context = "(no retrieved documents)"
        history = self._history_text(messages or [])

        system_prompt = (
            "You are an admission assistant for SUSTech. "
            "Answer based on retrieved documents and conversation history.\n"
            "Rules:\n"
            "1) Prioritize retrieved evidence;\n"
            "2) If evidence is insufficient, say so clearly and suggest next steps;\n"
            "3) Keep answer concise and direct.\n"
        )
        user_prompt = (
            f"User question: {query}\n"
            f"Intent: {intent}\n"
            f"Conversation history:\n{history}\n"
            f"Retrieved context:\n{context}\n"
        )

        request = [("system", system_prompt), ("user", user_prompt)]
        answer_parts: list[str] = []
        saw_stream_chunk = False
        try:
            for chunk in model.stream(request):
                saw_stream_chunk = True
                piece = self._to_stream_piece(getattr(chunk, "content", chunk))
                if piece:
                    answer_parts.append(piece)
        except Exception:
            # Fallback to non-stream invoke if streaming is unavailable.
            if not saw_stream_chunk:
                response = model.invoke(request)
                return self._to_text(getattr(response, "content", response))
            return "".join(answer_parts)

        answer = "".join(answer_parts)
        if not answer:
            if not saw_stream_chunk:
                response = model.invoke(request)
                return self._to_text(getattr(response, "content", response))
            return ""
        return answer


def _extract_query_from_state(state: WorkflowState) -> str:
    query = state.get("query")
    if query:
        return str(query).strip()

    messages = state.get("messages") or []
    for msg in reversed(messages):
        if isinstance(msg, BaseMessage):
            if getattr(msg, "type", "") in ("human", "user"):
                text = GenerationComponent._to_text(getattr(msg, "content", ""))
                if text:
                    return text
        elif isinstance(msg, dict):
            role = str(msg.get("role", msg.get("type", ""))).lower()
            if role in ("user", "human"):
                text = GenerationComponent._to_text(msg.get("content", ""))
                if text:
                    return text
    return ""


def _normalize_messages(raw_messages: Sequence[Any]) -> list[BaseMessage]:
    normalized: list[BaseMessage] = []
    for msg in raw_messages:
        if isinstance(msg, BaseMessage):
            normalized.append(msg)
            continue
        if not isinstance(msg, dict):
            continue

        role = str(msg.get("role", msg.get("type", ""))).lower()
        content = GenerationComponent._to_text(msg.get("content", ""))
        if not content:
            continue

        if role in ("user", "human"):
            normalized.append(HumanMessage(content=content))
        elif role in ("assistant", "ai"):
            normalized.append(AIMessage(content=content))
    return normalized


def create_generation_node(*, model_id: str | None = None):
    component = GenerationComponent(model_id=model_id)

    def generation_node(state: WorkflowState, runtime: Runtime[Any]):
        try:
            query = _extract_query_from_state(state)
            intent = str(state.get("intent") or "").strip()
            chunks = state.get("chunks", [])
            messages = state.get("messages") or []
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)

            answer = component.generate(
                query=query,
                intent=intent,
                chunks=chunks,
                messages=messages,
                model_id=runtime_model_id,
            )
            logger.debug(
                "Generation done.\n"
                f"intent={intent}\n"
                f"query={query}\n"
                f"chunks={len(chunks)}\n"
                f"answer_len={len(answer)}"
            )

            history = _normalize_messages(messages)
            last = history[-1] if history else None
            if query and not (
                isinstance(last, HumanMessage)
                and str(getattr(last, "content", "")).strip() == query
            ):
                history.append(HumanMessage(content=query))
            if answer:
                history.append(AIMessage(content=answer))
            return {"answer": answer, "messages": history}
        except Exception as exc:
            logger.error(f"Generation error {type(exc).__name__}: {exc}")
            return {"answer": ""}

    return generation_node
