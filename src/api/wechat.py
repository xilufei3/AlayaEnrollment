"""WeChat Official Account (公众号) adapter for AlayaEnrollment.

Bridges WeChat's XML-based messaging protocol with the existing
AdmissionGraphRuntime.  Designed for **subscription accounts** (订阅号)
that do NOT have the Customer Service Message API — replies are sent
exclusively via the passive-reply mechanism.

Long answers are automatically split into multiple pages.  The first
page is delivered immediately; the user sends any message (e.g. "继续")
to retrieve subsequent pages.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import JSONResponse, PlainTextResponse

_logger = logging.getLogger("alaya.wechat")

# WeChat imposes a 2048-byte limit on the Content field of text replies.
_WX_TEXT_REPLY_MAX_BYTES = 2048

# How long to keep a pending entry before garbage-collecting it.
_PENDING_TTL_SECONDS = 300  # 5 minutes

# ── In-memory state per user ──────────────────────────────────────

_pending: dict[str, dict[str, Any]] = {}


def _gc_pending() -> None:
    """Remove stale entries older than *_PENDING_TTL_SECONDS*."""
    now = time.time()
    stale = [k for k, v in _pending.items() if now - v["timestamp"] > _PENDING_TTL_SECONDS]
    for k in stale:
        entry = _pending.pop(k, None)
        if entry and "task" in entry:
            task: asyncio.Task = entry["task"]
            if not task.done():
                task.cancel()


# ── Text splitting helpers ────────────────────────────────────────

_CONTINUE_HINT = "\n\n——回复任意消息查看下一页——"
_CONTINUE_HINT_BYTES = len(_CONTINUE_HINT.encode("utf-8"))


def _split_to_pages(text: str, max_bytes: int = _WX_TEXT_REPLY_MAX_BYTES) -> list[str]:
    """Split *text* into pages each fitting within *max_bytes* UTF-8."""
    if len(text.encode("utf-8")) <= max_bytes:
        return [text]

    pages: list[str] = []
    remaining = text

    while remaining:
        remaining_bytes = len(remaining.encode("utf-8"))
        if remaining_bytes <= max_bytes:
            pages.append(remaining)
            break

        budget = max_bytes - _CONTINUE_HINT_BYTES
        encoded = remaining.encode("utf-8")[:budget]
        truncated = encoded.decode("utf-8", errors="ignore")

        # Try to break at last newline for cleaner splits
        nl = truncated.rfind("\n")
        if nl > len(truncated) // 3:
            truncated = truncated[:nl]

        pages.append(truncated + _CONTINUE_HINT)
        remaining = remaining[len(truncated):].lstrip("\n")

    return pages


# ── XML helpers ───────────────────────────────────────────────────

def _parse_xml(body: bytes) -> dict[str, str]:
    root = ET.fromstring(body)  # noqa: S314
    return {child.tag: (child.text or "") for child in root}


def _text_reply(from_user: str, to_user: str, content: str) -> str:
    ts = int(time.time())
    return (
        "<xml>"
        f"<ToUserName><![CDATA[{to_user}]]></ToUserName>"
        f"<FromUserName><![CDATA[{from_user}]]></FromUserName>"
        f"<CreateTime>{ts}</CreateTime>"
        "<MsgType><![CDATA[text]]></MsgType>"
        f"<Content><![CDATA[{content}]]></Content>"
        "</xml>"
    )


def _check_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    parts = sorted([token, timestamp, nonce])
    digest = hashlib.sha1("".join(parts).encode()).hexdigest()  # noqa: S324
    return digest == signature


# ── AI task runner ────────────────────────────────────────────────

async def _run_ai(openid: str, message: str, entry: dict[str, Any]) -> None:
    from ..runtime.graph_runtime import AdmissionGraphRuntime

    runtime: AdmissionGraphRuntime = entry["runtime"]
    try:
        answer = ""
        async for evt in runtime.stream_stage_events(
            session_id=openid,
            message=message,
            channel="wechat",
        ):
            if evt.get("event") == "message.completed":
                answer = evt.get("data", {}).get("answer", "")
                break
        entry["answer"] = answer or "抱歉，暂时无法回答您的问题，请稍后再试。"
    except Exception:
        _logger.exception("WeChat AI task failed for openid=%s", openid)
        entry["answer"] = "抱歉，系统处理出错，请稍后再试。"


def _deliver_answer(entry: dict[str, Any], gh_id: str, openid: str) -> PlainTextResponse:
    """Pop the first page from the entry and return it as a reply."""
    if "pages" not in entry or not entry["pages"]:
        entry["pages"] = _split_to_pages(entry["answer"])

    page = entry["pages"].pop(0)

    if not entry["pages"]:
        _pending.pop(openid, None)

    return PlainTextResponse(
        _text_reply(gh_id, openid, page),
        media_type="application/xml",
    )


# ── WeChat API helpers ────────────────────────────────────────────

_WX_TOKEN_URL = "https://api.weixin.qq.com/cgi-bin/token"
_WX_MENU_URL = "https://api.weixin.qq.com/cgi-bin/menu/create"

_WX_MENU = {
    "button": [
        {
            "type": "view",
            "name": "走进南科",
            "url": "https://mp.weixin.qq.com/s/WyU8kvhAyqsVxbNrQH35CQ",
        },
        {
            "name": "报考指南",
            "sub_button": [
                {
                    "type": "view",
                    "name": "综评报名",
                    "url": "https://mp.weixin.qq.com/s/WeSo2JzCpgElIJX9250Bow?click_id=7",
                },
                {
                    "type": "view",
                    "name": "招生简章",
                    "url": "https://mp.weixin.qq.com/s/YRJlCvBZiLdviAFVB_Auaw?click_id=8",
                },
            ],
        },
        {
            "type": "view",
            "name": "网上报名",
            "url": "https://register.sustech.edu.cn",
        },
    ]
}


async def _get_access_token(appid: str, appsecret: str) -> str:
    async with httpx.AsyncClient(timeout=10) as client:
        r = await client.get(
            _WX_TOKEN_URL,
            params={"grant_type": "client_credential", "appid": appid, "secret": appsecret},
        )
    data = r.json()
    if "access_token" not in data:
        raise RuntimeError(f"Failed to get access_token: {data}")
    return data["access_token"]


# ── Route factory ─────────────────────────────────────────────────

def mount_wechat_routes(app_state: Any) -> APIRouter:
    import os

    wechat_token = os.getenv("WECHAT_TOKEN", "").strip()
    wechat_appid = os.getenv("WECHAT_APPID", "").strip()
    wechat_appsecret = os.getenv("WECHAT_APPSECRET", "").strip()
    if not wechat_token:
        _logger.warning("WECHAT_TOKEN is empty — signature verification will reject all requests")

    router = APIRouter()

    @router.post("/wx/admin/init-menu")
    async def wx_init_menu(
        request: Request,
        token: str = Query("", alias="token"),
    ) -> JSONResponse:
        """One-time endpoint to create the WeChat custom menu via API.

        Call with ?token=<WECHAT_APPSECRET> to authenticate.
        """
        if not token or token != wechat_appsecret:
            raise HTTPException(status_code=403, detail="Invalid token")
        if not wechat_appid or not wechat_appsecret:
            raise HTTPException(status_code=500, detail="WECHAT_APPID / WECHAT_APPSECRET not configured")
        try:
            access_token = await _get_access_token(wechat_appid, wechat_appsecret)
        except RuntimeError as e:
            raise HTTPException(status_code=502, detail=str(e)) from e
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.post(
                _WX_MENU_URL,
                params={"access_token": access_token},
                json=_WX_MENU,
            )
        result = r.json()
        if result.get("errcode", -1) != 0:
            _logger.error("WeChat menu create failed: %s", result)
        else:
            _logger.info("WeChat menu created successfully")
        return JSONResponse(result)

    @router.get("/wx")
    async def wx_verify(
        signature: str = Query(""),
        timestamp: str = Query(""),
        nonce: str = Query(""),
        echostr: str = Query(""),
    ) -> PlainTextResponse:
        if not _check_signature(wechat_token, signature, timestamp, nonce):
            raise HTTPException(status_code=403, detail="Invalid signature")
        return PlainTextResponse(echostr)

    @router.post("/wx")
    async def wx_message(request: Request) -> PlainTextResponse:
        params = request.query_params
        sig = params.get("signature", "")
        ts = params.get("timestamp", "")
        nonce = params.get("nonce", "")
        if not _check_signature(wechat_token, sig, ts, nonce):
            raise HTTPException(status_code=403, detail="Invalid signature")

        body = await request.body()
        msg = _parse_xml(body)

        msg_type = msg.get("MsgType", "")
        openid = msg.get("FromUserName", "")
        gh_id = msg.get("ToUserName", "")

        if msg_type == "event":
            event = msg.get("Event", "").upper()
            if event == "SUBSCRIBE":
                welcome = (
                    "欢迎关注南方科技大学招生办公室官方微信！\n"
                    "我们将与您分享南科大的办学特色、办学成就和招生政策，"
                    "并为您第一时间推送南科大招生资讯。\n"
                    "南科大2026年本科综合评价招生报名已经启动，"
                    "报名网址 https://register.sustech.edu.cn\n"
                    "让我们一起逐梦追光，向极而行！"
                )
                return PlainTextResponse(_text_reply(gh_id, openid, welcome), media_type="application/xml")
            elif event in ("UNSUBSCRIBE", "VIEW"):
                return PlainTextResponse("success")
            elif event == "CLICK":
                event_key = msg.get("EventKey", "").strip()
                if not event_key:
                    return PlainTextResponse("success")
                content = event_key
                msg_id = f"click_{int(time.time())}"
            else:
                return PlainTextResponse("success")
        elif msg_type != "text":
            return PlainTextResponse(
                _text_reply(gh_id, openid, "您好，目前仅支持文字咨询，请直接输入您的问题~"),
                media_type="application/xml",
            )
        else:
            content = msg.get("Content", "").strip()
            msg_id = msg.get("MsgId", "")

        if not openid or not content:
            return PlainTextResponse("success")

        _gc_pending()
        runtime = app_state.runtime

        # ── Remaining pages from a previous answer ────────────────
        if openid in _pending:
            prev = _pending[openid]

            # Has undelivered pages → send next page
            if prev.get("pages"):
                page = prev["pages"].pop(0)
                if not prev["pages"]:
                    _pending.pop(openid, None)
                return PlainTextResponse(
                    _text_reply(gh_id, openid, page),
                    media_type="application/xml",
                )

            # Has a complete answer not yet paged (different question)
            if prev.get("answer") and prev.get("msg_id") != msg_id:
                return _deliver_answer(prev, gh_id, openid)

        # ── Retry of the SAME message (same MsgId) ───────────────
        if openid in _pending and _pending[openid].get("msg_id") == msg_id:
            entry = _pending[openid]
            if entry.get("answer"):
                return _deliver_answer(entry, gh_id, openid)
            for _ in range(9):
                await asyncio.sleep(0.5)
                if entry.get("answer"):
                    return _deliver_answer(entry, gh_id, openid)
            return PlainTextResponse(
                _text_reply(gh_id, openid, "正在思考中，请稍等片刻后发送任意消息获取回复~"),
                media_type="application/xml",
            )

        # ── Brand new message ─────────────────────────────────────
        if openid in _pending:
            old = _pending.pop(openid)
            if "task" in old:
                old_task: asyncio.Task = old["task"]
                if not old_task.done():
                    old_task.cancel()

        entry: dict[str, Any] = {
            "msg_id": msg_id,
            "answer": None,
            "pages": [],
            "runtime": runtime,
            "timestamp": time.time(),
        }
        task = asyncio.create_task(_run_ai(openid, content, entry))
        entry["task"] = task
        _pending[openid] = entry

        for _ in range(9):
            await asyncio.sleep(0.5)
            if entry.get("answer"):
                return _deliver_answer(entry, gh_id, openid)

        return PlainTextResponse(
            _text_reply(gh_id, openid, "正在思考中，请稍等片刻后发送任意消息获取回复~"),
            media_type="application/xml",
        )

    return router
