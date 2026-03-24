"""WeChat Official Account (公众号) adapter for AlayaEnrollment.

Bridges WeChat's XML-based messaging protocol with the existing
AdmissionGraphRuntime.  Designed for **subscription accounts** (订阅号)
that do NOT have the Customer Service Message API — replies are sent
exclusively via the passive-reply mechanism, leveraging WeChat's
automatic retry (up to 3 attempts within ~15 s) to wait for the AI
answer to become ready.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import xml.etree.ElementTree as ET
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import PlainTextResponse

_logger = logging.getLogger("alaya.wechat")

# WeChat imposes a 2048-char limit on text replies.
_WX_TEXT_REPLY_MAX_LEN = 2048

# How long to keep a pending entry before garbage-collecting it.
_PENDING_TTL_SECONDS = 300  # 5 minutes

# After this many seconds since the first request we give up waiting
# and return a "please retry" hint instead of an empty response.
_LAST_RETRY_THRESHOLD_SECONDS = 12

# ── In-memory pending-answer cache ────────────────────────────────

# {openid: {"msg_id": str, "answer": str|None, "error": str|None,
#            "task": asyncio.Task, "timestamp": float}}
_pending: dict[str, dict[str, Any]] = {}


def _gc_pending() -> None:
    """Remove stale entries older than *_PENDING_TTL_SECONDS*."""
    now = time.time()
    stale = [k for k, v in _pending.items() if now - v["timestamp"] > _PENDING_TTL_SECONDS]
    for k in stale:
        entry = _pending.pop(k, None)
        if entry and "task" in entry:
            task: asyncio.Task = entry["task"]  # type: ignore[assignment]
            if not task.done():
                task.cancel()


# ── XML helpers ───────────────────────────────────────────────────

def _parse_xml(body: bytes) -> dict[str, str]:
    """Parse a WeChat XML message into a flat dict."""
    root = ET.fromstring(body)  # noqa: S314 — input is from WeChat servers
    return {child.tag: (child.text or "") for child in root}


def _text_reply(from_user: str, to_user: str, content: str) -> str:
    """Build a WeChat passive text-reply XML string."""
    if len(content) > _WX_TEXT_REPLY_MAX_LEN:
        content = content[: _WX_TEXT_REPLY_MAX_LEN - 20] + "\n\n（回复过长，已截断）"
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


# ── Signature verification ────────────────────────────────────────

def _check_signature(token: str, signature: str, timestamp: str, nonce: str) -> bool:
    parts = sorted([token, timestamp, nonce])
    digest = hashlib.sha1("".join(parts).encode()).hexdigest()  # noqa: S324
    return digest == signature


# ── AI task runner ────────────────────────────────────────────────

async def _run_ai(openid: str, message: str, entry: dict[str, Any]) -> None:
    """Run the AI graph and store the answer in *entry*."""
    from ..runtime.graph_runtime import AdmissionGraphRuntime

    runtime: AdmissionGraphRuntime = entry["runtime"]
    try:
        answer = ""
        async for evt in runtime.stream_stage_events(session_id=openid, message=message):
            if evt.get("event") == "message.completed":
                answer = evt.get("data", {}).get("answer", "")
                break
        entry["answer"] = answer or "抱歉，暂时无法回答您的问题，请稍后再试。"
    except Exception:
        _logger.exception("WeChat AI task failed for openid=%s", openid)
        entry["answer"] = "抱歉，系统处理出错，请稍后再试。"


# ── Route factory ─────────────────────────────────────────────────

def mount_wechat_routes(app_state: Any) -> APIRouter:
    """Create and return the WeChat router bound to *app_state*.

    Call this from ``create_app`` so that the router can access the
    shared runtime and configuration.
    """
    import os

    wechat_token = os.getenv("WECHAT_TOKEN", "").strip()
    if not wechat_token:
        _logger.warning("WECHAT_TOKEN is empty — signature verification will reject all requests")

    router = APIRouter()

    @router.get("/wx")
    async def wx_verify(
        signature: str = Query(""),
        timestamp: str = Query(""),
        nonce: str = Query(""),
        echostr: str = Query(""),
    ) -> PlainTextResponse:
        """WeChat server URL verification."""
        if not _check_signature(wechat_token, signature, timestamp, nonce):
            raise HTTPException(status_code=403, detail="Invalid signature")
        return PlainTextResponse(echostr)

    @router.post("/wx")
    async def wx_message(request: Request) -> PlainTextResponse:
        """Receive a user message from WeChat and reply."""
        # Verify signature from query params
        params = request.query_params
        sig = params.get("signature", "")
        ts = params.get("timestamp", "")
        nonce = params.get("nonce", "")
        if not _check_signature(wechat_token, sig, ts, nonce):
            raise HTTPException(status_code=403, detail="Invalid signature")

        body = await request.body()
        msg = _parse_xml(body)

        msg_type = msg.get("MsgType", "")
        if msg_type != "text":
            return PlainTextResponse(
                _text_reply(
                    msg.get("ToUserName", ""),
                    msg.get("FromUserName", ""),
                    "您好，目前仅支持文字咨询，请直接输入您的问题~",
                ),
                media_type="application/xml",
            )

        openid = msg.get("FromUserName", "")
        gh_id = msg.get("ToUserName", "")
        content = msg.get("Content", "").strip()
        msg_id = msg.get("MsgId", "")

        if not openid or not content:
            return PlainTextResponse("success")

        # Periodic garbage collection
        _gc_pending()

        runtime = app_state.runtime

        # ── Case 1: cached answer from a PREVIOUS question ────────
        if openid in _pending:
            prev = _pending[openid]
            prev_answer = prev.get("answer")

            if prev_answer and prev.get("msg_id") != msg_id:
                # Deliver the cached answer, then start processing
                # the new question in the background.
                cached = _pending.pop(openid)["answer"]
                entry: dict[str, Any] = {
                    "msg_id": msg_id,
                    "answer": None,
                    "runtime": runtime,
                    "timestamp": time.time(),
                }
                task = asyncio.create_task(_run_ai(openid, content, entry))
                entry["task"] = task
                _pending[openid] = entry
                return PlainTextResponse(
                    _text_reply(gh_id, openid, cached),
                    media_type="application/xml",
                )

        # ── Case 2: retry of the SAME message (same MsgId) ───────
        if openid in _pending and _pending[openid].get("msg_id") == msg_id:
            entry = _pending[openid]
            if entry.get("answer"):
                answer = _pending.pop(openid)["answer"]
                return PlainTextResponse(
                    _text_reply(gh_id, openid, answer),
                    media_type="application/xml",
                )
            elapsed = time.time() - entry["timestamp"]
            if elapsed > _LAST_RETRY_THRESHOLD_SECONDS:
                return PlainTextResponse(
                    _text_reply(gh_id, openid, "正在思考中，请稍后发送任意消息获取回复~"),
                    media_type="application/xml",
                )
            # Return empty so WeChat retries
            return PlainTextResponse("success")

        # ── Case 3: brand new message ─────────────────────────────
        # Cancel any stale pending task for this user
        if openid in _pending:
            old = _pending.pop(openid)
            if "task" in old:
                old_task: asyncio.Task = old["task"]  # type: ignore[assignment]
                if not old_task.done():
                    old_task.cancel()

        entry = {
            "msg_id": msg_id,
            "answer": None,
            "runtime": runtime,
            "timestamp": time.time(),
        }
        task = asyncio.create_task(_run_ai(openid, content, entry))
        entry["task"] = task
        _pending[openid] = entry

        # Return empty — WeChat will retry in ~5 s
        return PlainTextResponse("success")

    return router
