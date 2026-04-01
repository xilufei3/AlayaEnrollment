from __future__ import annotations

import asyncio
import json
import logging

import httpx
from nonebot import get_plugin_config, on_message
from nonebot.adapters.qq import Bot, C2CMessageCreateEvent, GroupAtMessageCreateEvent

from .config import Config

_logger = logging.getLogger("alaya.qq")
_cfg = get_plugin_config(Config)

# ── 长文本分页（QQ 单条消息建议不超过 900 字） ──────────────────────
_QQ_MAX_CHARS = 900
_CONTINUE_HINT = "\n\n……（回复任意内容查看下一页）"


def _split_pages(text: str) -> list[str]:
    if len(text) <= _QQ_MAX_CHARS:
        return [text]
    pages, remaining = [], text
    while len(remaining) > _QQ_MAX_CHARS:
        cut = remaining.rfind("\n", 0, _QQ_MAX_CHARS)
        cut = cut if cut > _QQ_MAX_CHARS // 3 else _QQ_MAX_CHARS
        pages.append(remaining[:cut] + _CONTINUE_HINT)
        remaining = remaining[cut:].lstrip("\n")
    if remaining:
        pages.append(remaining)
    return pages


# ── 调用 /api/chat/stream，返回完整答案 ─────────────────────────────
async def _ask_alaya(session_id: str, message: str) -> str:
    headers = {
        "Content-Type": "application/json",
        "X-API-Key": _cfg.alaya_api_key,
    }
    payload = {"session_id": session_id, "message": message}
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


# ── 并发锁与分页缓存（key = session_id） ────────────────────────────
_locks: dict[str, asyncio.Lock] = {}
_pending_pages: dict[str, list[str]] = {}


def _get_lock(key: str) -> asyncio.Lock:
    if key not in _locks:
        _locks[key] = asyncio.Lock()
    return _locks[key]


async def _handle(bot: Bot, event: GroupAtMessageCreateEvent | C2CMessageCreateEvent) -> None:
    text = event.get_plaintext().strip()
    if not text:
        return

    # session_id：群用群 openid，私聊用用户 openid
    if isinstance(event, GroupAtMessageCreateEvent):
        if _cfg.alaya_allowed_groups and event.group_openid not in _cfg.alaya_allowed_groups:
            return
        session_id = f"qq_group_{event.group_openid}"
    else:
        session_id = f"qq_c2c_{event.author.user_openid}"

    # 有缓存分页 → 发下一页
    if session_id in _pending_pages and _pending_pages[session_id]:
        page = _pending_pages[session_id].pop(0)
        if not _pending_pages[session_id]:
            del _pending_pages[session_id]
        await bot.send(event, page)
        return

    lock = _get_lock(session_id)
    if lock.locked():
        await bot.send(event, "正在处理上一条消息，请稍候…")
        return

    async with lock:
        await bot.send(event, "正在思考中，请稍候…")
        try:
            answer = await _ask_alaya(session_id, text)
        except Exception:
            _logger.exception("Failed to call Alaya API, session=%s", session_id)
            await bot.send(event, "抱歉，服务暂时不可用，请稍后重试。")
            return

        pages = _split_pages(answer)
        if len(pages) > 1:
            _pending_pages[session_id] = pages[1:]
        await bot.send(event, pages[0])


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
