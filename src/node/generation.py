from __future__ import annotations

from typing import Any, Sequence

from langchain_core.documents import Document
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage
from langgraph.runtime import Runtime

from alayaflow.utils.logger import AlayaFlowLogger

from ..config import HISTORY_LAST_K_TURNS
from ..schemas import WorkflowState
from .model_provider import get_model

logger = AlayaFlowLogger()

# ── 场景化 System Prompt（按意图分支）────────────────────────────────────────

_SYSTEM_PROMPTS: dict[str, str] = {
    "other": (
        "你是南科大招生咨询助手，正在接待一位高中生或家长。\n"
        "用户发出的是问候或简单交互，请以亲切、简洁的方式回应，"
        "并适当引导对方说出真正想了解的招生问题。\n"
        "回复控制在 50 字以内，不要罗列信息，不要捏造任何数据。"
    ),
    "school_overview": (
        "你是南科大招生咨询助手，正在向一位高中生或家长介绍学校。\n"
        "回复目标：帮助用户在 5 分钟内建立整体印象，判断南科大是否值得深入了解。\n"
        "回复结构：① 学校定位（1-2句）② 核心特色（3点以内）③ 校园与城市（1句）④ 建议进一步了解的方向\n"
        "回复长度：200-300 字，结构清晰，避免堆砌。\n"
        "重要：所有信息以检索到的文档为准，不得补充未经文档支撑的内容。"
    ),
    "admission_policy": (
        "你是南科大招生咨询助手，正在向准备报考的考生或家长解答招生政策。\n"
        "回复要求：\n"
        "- 数字（分数线、比例、日期）必须有文档依据，不得自行估算\n"
        "- 如文档信息不完整，明确说明「以招生网最新公告为准」\n"
        "- 对631计算方式等核心规则需完整解释，不可含糊\n"
        "警告：招生政策每年变化，如涉及时间节点或录取规则，必须提醒用户以当年官方通知为准。\n"
        "如检索文档为空，请回答：「该信息暂无记录，建议访问 admission.sustech.edu.cn 或联系招办（0755-88010401）。」"
    ),
    "major_and_training": (
        "你是南科大招生咨询助手，正在向纠结选专业的高中生或家长介绍专业情况。\n"
        "回复结构：① 专业定位与培养目标 ② 核心课程与实践机会 ③ 深造/就业方向（如有数据）\n"
        "如用户同时问及就业/深造，说明「具体就业数据请参考学校年度就业质量报告」。\n"
        "重要：所有课程、方向信息以检索到的文档为准，不得捏造课程名或比例。"
    ),
    "career_and_development": (
        "你是南科大招生咨询助手，正在回答关于毕业去向的问题。\n"
        "回复要求：深造率、就业率等数据严格以文档为准，不得引用行业平均数据替代。\n"
        "如文档信息不足，明确告知：「具体数据请参考南科大官网发布的年度就业质量报告。」\n"
        "如检索文档为空，请如实说明暂无数据，并引导用户至官网查询。"
    ),
    "campus_life": (
        "你是南科大招生咨询助手，正在回答关于校园生活的问题。\n"
        "回复要求：住宿费、学费等具体数字严格以文档为准，不得估算。\n"
        "如信息不完整，引导用户：「具体费用标准请联系南科大学生事务处或查阅官网。」\n"
        "如检索文档为空，请如实说明并提供官网引导。"
    ),
}

_DEFAULT_SYSTEM_PROMPT = (
    "你是南科大招生咨询助手，目标用户为高中生及家长。\n"
    "回复要求：\n"
    "1. 优先依据检索到的文档回答，不得捏造数字、日期或比例\n"
    "2. 若文档不足，明确说明并建议用户查阅官网或联系招办\n"
    "3. 回复简洁直接，使用中文"
)

_NO_RETRIEVAL_SUFFIX = (
    "\n\n注意：当前暂无相关检索文档。请勿编造任何具体数字、时间节点、录取比例或分数线。"
    "如无法从已知信息中给出可靠回答，请直接引导用户至官方渠道：\n"
    "招生网：https://admission.sustech.edu.cn\n"
    "招办电话：0755-88010401"
)


class GenerationComponent:
    def __init__(self, *, model_id: str | None = None) -> None:
        self.model_id = model_id

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
                    role = "用户"
                elif t in ("ai", "assistant"):
                    role = "助手"
                content = getattr(msg, "content", "")
            elif isinstance(msg, dict):
                t = str(msg.get("type", msg.get("role", ""))).lower()
                if t in ("human", "user"):
                    role = "用户"
                elif t in ("ai", "assistant"):
                    role = "助手"
                content = msg.get("content", "")
            if not role:
                continue
            text = cls._to_text(content)
            if text:
                rows.append(f"{role}：{text}")

        if not rows:
            return "（无）"
        return "\n".join(rows[-(max_turns * 2):])

    def generate_short(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        model_id: str | None = None,
    ) -> str:
        """单轮短回复，用于缺槽位追问、out_of_scope 等场景。"""
        active_model_kind = model_id or self.model_id or "generation"
        try:
            model = get_model(active_model_kind)
            response = model.invoke([
                ("system", system_prompt),
                ("user", user_prompt),
            ])
            return self._to_text(getattr(response, "content", response))
        except Exception:
            return ""

    def generate(
        self,
        *,
        query: str,
        intent: str,
        chunks: Sequence[Any],
        messages: Sequence[Any] | None = None,
        model_id: str | None = None,
        system_suffix: str = "",
    ) -> str:
        active_model_kind = model_id or self.model_id or "generation"
        model = get_model(active_model_kind)
        chunk_texts = self._chunk_texts(chunks)
        has_context = bool(chunk_texts)
        context = "\n".join(chunk_texts) if has_context else "（无检索文档）"
        history = self._history_text(messages or [])

        system_prompt = _SYSTEM_PROMPTS.get(intent, _DEFAULT_SYSTEM_PROMPT)
        if not has_context:
            system_prompt += _NO_RETRIEVAL_SUFFIX
        if system_suffix:
            system_prompt += "\n\n" + system_suffix

        user_prompt = (
            f"用户问题：{query}\n"
            f"对话历史：\n{history}\n"
            f"检索到的参考文档：\n{context}\n"
            "请根据以上信息作答："
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
            missing_slots = state.get("missing_slots") or []
            messages_full = state.get("messages") or []
            runtime_model_id = getattr(getattr(runtime, "context", None), "chat_model_id", None)

            # 缺槽位处理：RAG 已执行，根据是否有 chunks 选择不同策略
            chunks_for_missing = state.get("chunks") or []
            if missing_slots:
                slot_names = "、".join(missing_slots)
                if chunks_for_missing:
                    # 有检索结果：先展示示例，再引导用户补充缺少的槽位
                    suffix = (
                        f"【重要提示】用户问题需要补充「{slot_names}」才能给出精确回答。\n"
                        "请按以下结构作答：\n"
                        "1. 先从检索文档中提取 1-2 个示例（如有多个省份/年份数据，选有代表性的列举），帮助用户建立参考；\n"
                        "2. 在回复末尾用一句自然的话引导用户告知具体的信息（如所在省份、目标年份等）。\n"
                        "所有数据必须来自检索文档，不得捏造。"
                    )
                    max_msgs = HISTORY_LAST_K_TURNS * 2
                    messages_for_history = list(messages_full)[-max_msgs:] if messages_full else []
                    answer = component.generate(
                        query=query,
                        intent=intent,
                        chunks=chunks_for_missing,
                        messages=messages_for_history,
                        model_id=runtime_model_id,
                        system_suffix=suffix,
                    )
                    if not answer:
                        answer = f"为了给您精确的答案，请补充「{slot_names}」。"
                else:
                    # 无检索结果：仅生成一句追问
                    sys = (
                        "你是南科大招生咨询助手。用户的问题需要补充一些信息才能准确回答。"
                        "请用一句话礼貌地追问用户补充上述信息，语气亲切，控制在 40 字以内。不要重复用户原话，直接输出追问内容。"
                    )
                    user = f"用户问题：{query}\n当前缺少的信息：{slot_names}\n请输出一句追问："
                    answer = component.generate_short(
                        system_prompt=sys,
                        user_prompt=user,
                        model_id=runtime_model_id,
                    )
                    if not answer:
                        answer = f"为了准确回答，请先告诉我您的{slot_names}。"
                history = _normalize_messages(messages_full)
                last = history[-1] if history else None
                if query and not (
                    isinstance(last, HumanMessage)
                    and str(getattr(last, "content", "")).strip() == query
                ):
                    history.append(HumanMessage(content=query))
                history.append(AIMessage(content=answer))
                return {"answer": answer, "messages": history}

            # 超出招生范围：由大模型生成一句礼貌说明并引导
            if intent == "out_of_scope":
                sys = (
                    "你是南科大招生咨询助手。用户的问题与南科大本科招生无关。"
                    "请用一句话礼貌说明你主要回答招生相关问题，并引导用户提问。控制在 60 字以内。直接输出回复内容。"
                )
                user = f"用户问题：{query}\n请输出一句回复："
                answer = component.generate_short(
                    system_prompt=sys,
                    user_prompt=user,
                    model_id=runtime_model_id,
                )
                if not answer:
                    answer = "我目前主要回答南科大本科招生相关问题，你可以问我学校概况、招生政策、专业培养或校园生活。"
                history = _normalize_messages(messages_full)
                last = history[-1] if history else None
                if query and not (
                    isinstance(last, HumanMessage)
                    and str(getattr(last, "content", "")).strip() == query
                ):
                    history.append(HumanMessage(content=query))
                history.append(AIMessage(content=answer))
                return {"answer": answer, "messages": history, "retrieval_skipped": True}

            chunks = state.get("chunks") or []
            # 拼对话历史时只取最近 k 轮，由 config 控制
            max_msgs = HISTORY_LAST_K_TURNS * 2
            messages_for_history = list(messages_full)[-max_msgs:] if messages_full else []

            answer = component.generate(
                query=query,
                intent=intent,
                chunks=chunks,
                messages=messages_for_history,
                model_id=runtime_model_id,
            )
            logger.debug(
                "Generation done.\n"
                f"intent={intent}\n"
                f"query={query}\n"
                f"chunks={len(chunks)}\n"
                f"answer_len={len(answer)}"
            )

            history = _normalize_messages(messages_full)
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
