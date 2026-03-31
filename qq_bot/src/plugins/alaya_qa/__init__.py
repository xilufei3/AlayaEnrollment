from __future__ import annotations

import asyncio
import json
import logging
import re
import time

import httpx
from nonebot import get_plugin_config, on_message
from nonebot.adapters.qq import Bot, C2CMessageCreateEvent, GroupAtMessageCreateEvent

from .config import Config

_logger = logging.getLogger("alaya.qq")
_cfg = get_plugin_config(Config)

# ── Markdown → 纯文本（QQ 暂不支持 Markdown 渲染时使用） ─────────────
def _strip_markdown(text: str) -> str:
    # 代码块（```...```）整块替换为缩进文本
    text = re.sub(r"```[^\n]*\n?(.*?)```", lambda m: m.group(1).strip(), text, flags=re.DOTALL)
    # 行内代码
    text = re.sub(r"`(.+?)`", r"\1", text)
    # 标题（## 标题 → 标题）
    text = re.sub(r"^#{1,6}\s+", "", text, flags=re.MULTILINE)
    # 加粗 / 斜体
    text = re.sub(r"\*{1,2}(.+?)\*{1,2}", r"\1", text)
    text = re.sub(r"_{1,2}(.+?)_{1,2}", r"\1", text)
    # 链接 [文字](url) → 文字
    text = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", text)
    # 图片 ![alt](url) → alt
    text = re.sub(r"!\[.*?\]\(.+?\)", "", text)
    # Markdown 表格行（含 | 的行）→ 空格分隔
    text = re.sub(r"^\|(.+)\|$", lambda m: "  ".join(c.strip() for c in m.group(1).split("|") if c.strip()), text, flags=re.MULTILINE)
    # 表格分隔行（|---|---|）
    text = re.sub(r"^\|[-| :]+\|$", "", text, flags=re.MULTILINE)
    # 水平线
    text = re.sub(r"^[-*_]{3,}\s*$", "", text, flags=re.MULTILINE)
    # 合并连续空行
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


# ── 长文本分页（QQ 单条消息建议不超过 900 字） ──────────────────────
_QQ_MAX_CHARS = 900


def _split_pages(text: str) -> list[str]:
    if len(text) <= _QQ_MAX_CHARS:
        return [text]
    pages, remaining = [], text
    while len(remaining) > _QQ_MAX_CHARS:
        cut = remaining.rfind("\n", 0, _QQ_MAX_CHARS)
        cut = cut if cut > _QQ_MAX_CHARS // 3 else _QQ_MAX_CHARS
        pages.append(remaining[:cut])
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        pages.append(remaining)
    return pages


# ── session_id 解析（含超时自动重置上下文） ──────────────────────────
_SESSION_TIMEOUT = 3600  # 1 小时无活动则开新 session，可通过环境变量覆盖

_last_active: dict[str, float] = {}


def _resolve_session_id(base_id: str) -> str:
    """根据 base_id 和最后活跃时间返回实际 session_id。

    超过 _SESSION_TIMEOUT 秒未活动时，以时间槽编号作后缀生成新 session，
    后端 LangGraph 会为新 thread_id 创建空白上下文，旧历史不再载入。
    """
    now = time.time()
    last = _last_active.get(base_id, 0)
    _last_active[base_id] = now
    if now - last > _SESSION_TIMEOUT:
        slot = int(now // _SESSION_TIMEOUT)
        return f"{base_id}_{slot}"
    # 活跃期内保持与上次相同的 slot
    slot = int(last // _SESSION_TIMEOUT)
    return f"{base_id}_{slot}"


# ── 调用 /api/chat/stream，返回完整答案 ─────────────────────────────
async def _ask_alaya(session_id: str, message: str) -> str:
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": _cfg.alaya_api_key,
    }
    payload = {"session_id": session_id, "message": message, "channel": "qq"}
    current_event = ""

    async with httpx.AsyncClient(timeout=120) as client:
        async with client.stream(
            "POST",
            f"{_cfg.alaya_api_base}/api/chat/stream",
            headers=headers,
            json=payload,
        ) as resp:
            resp.raise_for_status()
            async for line in resp.aiter_lines():
                if line.startswith("event:"):
                    current_event = line[6:].strip()
                elif line.startswith("data:"):
                    data = json.loads(line[5:].strip())
                    if current_event == "message.completed":
                        return data.get("answer", "")
                    if current_event == "error":
                        _logger.error("Alaya error event: %s", data)
                        return "抱歉，AI 服务出现异常，请稍后重试。"

    return "抱歉，未获取到回答，请稍后重试。"


# ── 并发锁 & 待处理消息队列（key = base_session_id） ────────────────
# _pending 存储 (消息文本, event对象)，只保留最新一条
_locks: dict[str, asyncio.Lock] = {}
_pending: dict[str, tuple[str, GroupAtMessageCreateEvent | C2CMessageCreateEvent]] = {}


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def _process(
    bot: Bot,
    event: GroupAtMessageCreateEvent | C2CMessageCreateEvent,
    text: str,
    base_id: str,
) -> None:
    """发起一次 Alaya 调用并将结果回复给用户。"""
    session_id = _resolve_session_id(base_id)
    await bot.send(event, "正在思考中，请稍候…")
    try:
        answer = await _ask_alaya(session_id, text)
    except Exception:
        _logger.exception("Failed to call Alaya API, session=%s", session_id)
        await bot.send(event, "抱歉，服务暂时不可用，请稍后重试。")
        return

    pages = _split_pages(_strip_markdown(answer))
    for page in pages:
        await bot.send(event, page)
        if len(pages) > 1:
            await asyncio.sleep(0.5)


async def _handle(bot: Bot, event: GroupAtMessageCreateEvent | C2CMessageCreateEvent) -> None:
    text = event.get_plaintext().strip()
    if not text:
        return

    # base_id：群聊按「群+用户」隔离，私聊按用户隔离
    if isinstance(event, GroupAtMessageCreateEvent):
        if _cfg.alaya_allowed_groups and event.group_openid not in _cfg.alaya_allowed_groups:
            return
        base_id = f"qq_group_{event.group_openid}_{event.author.member_openid}"
    else:
        base_id = f"qq_c2c_{event.author.user_openid}"

    lock = _get_lock(base_id)
    if lock.locked():
        # 正忙：将最新消息存入待处理队列（覆盖旧的），不丢弃
        _pending[base_id] = (text, event)
        return

    async with lock:
        await _process(bot, event, text, base_id)
        # 处理完后，若有排队消息则继续消费（最多消费一次，避免无限循环）
        if base_id in _pending:
            queued_text, queued_event = _pending.pop(base_id)
            await _process(bot, queued_event, queued_text, base_id)


# ── 群消息处理器（@机器人触发） ──────────────────────────────────────
_group_matcher = on_message(priority=10, block=True)


@_group_matcher.handle()
async def handle_group(bot: Bot, event: GroupAtMessageCreateEvent) -> None:
    await _handle(bot, event)


# ── 私聊消息处理器 ────────────────────────────────────────────────────
_c2c_matcher = on_message(priority=10, block=True)


@_c2c_matcher.handle()
async def handle_c2c(bot: Bot, event: C2CMessageCreateEvent) -> None:
    await _handle(bot, event)
