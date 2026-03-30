# QQ 群聊接入指南

本文档说明如何将 AlayaEnrollment 的 AI 能力接入 QQ 群聊，实现群内自动问答。

---

## 目录

1. [整体架构](#1-整体架构)
2. [与微信适配器的对比](#2-与微信适配器的对比)
3. [第一步：搭建 QQ 协议层](#3-第一步搭建-qq-协议层)
4. [第二步：创建 NoneBot2 项目](#4-第二步创建-nonebot2-项目)
5. [第三步：编写群消息插件](#5-第三步编写群消息插件)
6. [第四步：session_id 策略](#6-第四步session_id-策略)
7. [第五步：启动与部署](#7-第五步启动与部署)
8. [注意事项](#8-注意事项)
9. [参考资料](#9-参考资料)

---

## 1. 整体架构

```
QQ 用户发消息
     │
     ▼
QQ 客户端（QQNT）
     │  OneBot v11 协议（反向 WebSocket）
     ▼
LLOneBot / Lagrange.Core        ← QQ 协议层（消息收发）
     │  上报群消息事件
     ▼
NoneBot2 Bot 服务（独立进程）    ← 业务逻辑层（消息路由、分页、限流）
     │  HTTP POST /api/chat/stream（SSE）
     ▼
AlayaEnrollment FastAPI          ← 现有 AI 服务（无需改动）
```

**设计原则：** NoneBot2 作为独立进程通过 HTTP 调用现有 `/api/chat/stream` 接口，无需修改 FastAPI 代码。

---

## 2. 与微信适配器的对比

| 维度 | 微信适配器（现有） | QQ 群适配器（本文档） |
|------|-----------------|-------------------|
| 接入位置 | FastAPI 内部路由 `/wx` | 独立 NoneBot2 进程 |
| 调用方式 | 直接调用 `runtime.stream_stage_events()` | HTTP 调用 `/api/chat/stream` |
| 协议限制 | XML 被动回复，5s 超时限制 | WebSocket / OneBot v11，无严格时限 |
| 长文本分页 | 用户发任意消息翻页 | 相同机制 |
| 部署复杂度 | 低（已集成于 FastAPI） | 中（需额外进程 + 协议层） |

---

## 3. 第一步：搭建 QQ 协议层

选择以下任一方案将 QQ 消息转换为 OneBot v11 协议。

### 方案 A：LLOneBot（推荐）

基于官方 QQNT 客户端，稳定性较高。

1. 在 Bot 账号的设备上安装 [QQNT 客户端](https://im.qq.com/) 并登录
2. 安装 [LLOneBot](https://llonebot.github.io/) 插件
3. 在 LLOneBot 设置中开启**反向 WebSocket**，填写 NoneBot2 地址：

```json
{
  "reverseWebsocket": [
    { "url": "ws://127.0.0.1:8080/onebot/v11/ws" }
  ]
}
```

### 方案 B：Lagrange.Core（无需 QQ 客户端）

开源实现，适合服务器无 GUI 环境。

```bash
git clone https://github.com/LagrangeGroup/Lagrange.Core
cd Lagrange.OneBot
dotnet run
```

首次运行扫码登录，之后在 `appsettings.json` 中配置反向 WebSocket 地址指向 NoneBot2。

---

## 4. 第二步：创建 NoneBot2 项目

### 安装依赖

```bash
pip install "nonebot2[fastapi]" nonebot-adapter-onebot httpx
```

### 初始化项目

```bash
nb create
# 驱动器选择：FastAPI
# 适配器选择：OneBot V11
```

生成的目录结构：

```
qq_bot/
├── bot.py
├── .env
├── pyproject.toml
└── src/
    └── plugins/
        └── alaya_qa/
            ├── __init__.py
            └── config.py
```

### `bot.py`

```python
import nonebot
from nonebot.adapters.onebot.v11 import Adapter as OneBotAdapter

nonebot.init()
driver = nonebot.get_driver()
driver.register_adapter(OneBotAdapter)
nonebot.load_plugin("src.plugins.alaya_qa")
nonebot.run()
```

### `.env`

```ini
HOST=0.0.0.0
PORT=8080

# AlayaEnrollment 后端地址与密钥
ALAYA_API_BASE=http://localhost:8008
ALAYA_API_KEY=<API_SHARED_KEY>

# 触发前缀：空 = 响应所有群消息；非空 = 仅响应 @机器人 的消息
ALAYA_TRIGGER_PREFIX=

# 群白名单（逗号分隔群号），空 = 不限制群
ALAYA_ALLOWED_GROUPS=123456789,987654321
```

---

## 5. 第三步：编写群消息插件

### `src/plugins/alaya_qa/config.py`

```python
from pydantic import BaseModel

class Config(BaseModel):
    alaya_api_base: str = "http://localhost:8008"
    alaya_api_key: str = ""
    alaya_trigger_prefix: str = ""
    alaya_allowed_groups: list[int] = []
```

### `src/plugins/alaya_qa/__init__.py`

```python
from __future__ import annotations

import asyncio
import json
import logging

import httpx
from nonebot import get_plugin_config, on_message
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent
from nonebot.rule import to_me

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


# ── 群级别并发锁与分页缓存 ───────────────────────────────────────────
_group_locks: dict[int, asyncio.Lock] = {}
_pending_pages: dict[int, list[str]] = {}  # group_id → 剩余页


def _get_lock(group_id: int) -> asyncio.Lock:
    if group_id not in _group_locks:
        _group_locks[group_id] = asyncio.Lock()
    return _group_locks[group_id]


# ── 消息处理器 ───────────────────────────────────────────────────────
_rule = to_me() if _cfg.alaya_trigger_prefix else None
_matcher = on_message(rule=_rule, priority=10, block=True)


@_matcher.handle()
async def handle_group_message(bot: Bot, event: GroupMessageEvent) -> None:
    group_id = event.group_id

    # 群白名单过滤
    if _cfg.alaya_allowed_groups and group_id not in _cfg.alaya_allowed_groups:
        return

    text = event.get_plaintext().strip()

    # 前缀过滤
    if _cfg.alaya_trigger_prefix:
        if not text.startswith(_cfg.alaya_trigger_prefix):
            return
        text = text[len(_cfg.alaya_trigger_prefix):].strip()

    if not text:
        return

    # 有缓存分页 → 发下一页
    if group_id in _pending_pages and _pending_pages[group_id]:
        page = _pending_pages[group_id].pop(0)
        if not _pending_pages[group_id]:
            del _pending_pages[group_id]
        await bot.send(event, page)
        return

    # session_id 策略（见第 6 节）
    session_id = f"qq_group_{group_id}"

    lock = _get_lock(group_id)
    if lock.locked():
        await bot.send(event, "正在处理上一条消息，请稍候…")
        return

    async with lock:
        await bot.send(event, "正在思考中，请稍候…")
        try:
            answer = await _ask_alaya(session_id, text)
        except Exception:
            _logger.exception("Failed to call Alaya API for group=%s", group_id)
            await bot.send(event, "抱歉，服务暂时不可用，请稍后重试。")
            return

        pages = _split_pages(answer)
        if len(pages) > 1:
            _pending_pages[group_id] = pages[1:]
        await bot.send(event, pages[0])
```

---

## 6. 第四步：session_id 策略

`session_id` 决定 AI 的会话上下文范围，根据业务需求选择：

| 策略 | `session_id` 值 | 效果 | 适用场景 |
|------|----------------|------|---------|
| **群维度**（默认） | `qq_group_{group_id}` | 同群所有人共享一个会话上下文 | 群内话题连贯，适合招生咨询 |
| **用户维度** | `qq_{user_id}` | 每个用户跨群独立上下文 | 用户咨询历史不受群隔离 |
| **群+用户维度** | `qq_{group_id}_{user_id}` | 每人在每个群独立上下文 | 多群部署、用户隐私要求高 |

修改插件中 `session_id` 赋值行即可切换：

```python
# 群维度
session_id = f"qq_group_{group_id}"

# 用户维度
session_id = f"qq_{event.user_id}"

# 群+用户维度
session_id = f"qq_{group_id}_{event.user_id}"
```

> **注意：** `session_id` 长度要求 8–128 字符，格式 `[a-zA-Z0-9_\-]`，以上三种写法均满足要求。

---

## 7. 第五步：启动与部署

### 单机启动

```bash
# 确保 AlayaEnrollment FastAPI 已运行在 :8008
# 确保 LLOneBot 已配置反向 WS 到 :8080

cd qq_bot
python bot.py
```

启动后 LLOneBot 会通过 WebSocket 连接到 NoneBot2，日志中出现连接成功提示即可。

### Docker Compose 整合

在现有 `docker-compose.yml` 中追加：

```yaml
services:
  # 现有服务保持不变 ...

  qq-bot:
    build:
      context: ./qq_bot
      dockerfile: Dockerfile
    environment:
      ALAYA_API_BASE: http://backend:8008
      ALAYA_API_KEY: ${API_SHARED_KEY}
      ALAYA_ALLOWED_GROUPS: ${QQ_ALLOWED_GROUPS:-}
    depends_on:
      - backend
    ports:
      - "8080:8080"   # LLOneBot 反向 WS 连接此端口
    restart: unless-stopped
```

`qq_bot/Dockerfile`：

```dockerfile
FROM python:3.11-slim
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .
CMD ["python", "bot.py"]
```

`qq_bot/requirements.txt`：

```
nonebot2[fastapi]
nonebot-adapter-onebot
httpx
```

---

## 8. 注意事项

| 问题 | 处理方式 |
|------|---------|
| AI 响应较慢 | 先发"正在思考中…"占位，AI 完成后再发结果（已实现） |
| 长文本超限 | 自动分页，每页 ≤ 900 字，用户发任意消息触发下一页 |
| 同群并发消息 | 群级别 `asyncio.Lock`，后续消息提示"请稍候" |
| Bot 账号风控 | 使用独立 Bot 账号；避免短时间内大量发消息；建议设置群白名单 |
| 协议层断线重连 | LLOneBot / Lagrange 均支持自动重连，NoneBot2 侧无需额外处理 |
| 私聊支持 | 将 `GroupMessageEvent` 改为 `PrivateMessageEvent`，`session_id` 改用 `qq_{user_id}` |
| 上下文过长 | AlayaEnrollment 内部有 thread TTL（默认 2h），超时自动清理历史 |

---

## 9. 参考资料

| 资源 | 说明 |
|------|------|
| [NoneBot2 文档](https://nonebot.dev/) | Bot 框架官方文档 |
| [LLOneBot](https://llonebot.github.io/) | QQNT 协议插件 |
| [Lagrange.Core](https://github.com/LagrangeGroup/Lagrange.Core) | 开源 QQ 协议实现 |
| [OneBot v11 规范](https://11.onebot.dev/) | 消息协议标准 |
| `src/api/chat_app.py` | `/api/chat/stream` 接口实现 |
| `src/api/wechat.py` | 微信适配器参考实现 |
| `docs/API_EXTERNAL_ACCESS.md` | 后端 API 完整文档 |
