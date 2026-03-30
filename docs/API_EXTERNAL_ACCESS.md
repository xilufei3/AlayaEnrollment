# AlayaEnrollment 对外 API 访问文档

本文档说明项目在不同部署方式下的对外 API 入口、接口路径、请求/响应格式与鉴权方式。

---

## 目录

1. [部署架构与访问入口](#1-部署架构与访问入口)
2. [BFF 对外可访问接口（白名单）](#2-bff-对外可访问接口白名单)
3. [FastAPI 直连接口（全量）](#3-fastapi-直连接口全量)
4. [接口详情](#4-接口详情)
   - [健康与服务信息](#41-健康与服务信息)
   - [线程管理](#42-线程管理)
   - [流式对话（SSE）](#43-流式对话sse)
   - [管理接口](#44-管理接口)
   - [微信公众号接口](#45-微信公众号接口可选)
5. [鉴权与请求头](#5-鉴权与请求头)
6. [SSE 事件格式](#6-sse-事件格式)
7. [错误响应](#7-错误响应)
8. [限流与超时](#8-限流与超时)
9. [CORS 配置](#9-cors-配置)
10. [快速调用示例](#10-快速调用示例)
11. [环境变量参考](#11-环境变量参考)
12. [参考实现文件](#12-参考实现文件)

---

## 1. 部署架构与访问入口

项目存在两层 API 访问方式：

| 层级 | 说明 | 默认地址 |
|------|------|---------|
| **Nginx 反代** | 对外唯一入口，转发至 BFF 或 Backend | `http://<host>:8082` |
| **Next.js BFF** | 浏览器/外部系统推荐入口，注入 `X-API-Key` | `http://127.0.0.1:3001` |
| **FastAPI Backend** | 服务间直连，全量接口 | `http://<host>:8008` |

**路径说明：**
- Web 前端启用了 `basePath=/zs-ai`，浏览器默认 API 前缀为 `/zs-ai/api`
- 浏览器不直连 FastAPI，先走 BFF，BFF 注入 `X-API-Key` 后转发给后端

---

## 2. BFF 对外可访问接口（白名单）

对外基路径：`/zs-ai/api`

| 方法 | 路径 | 说明 |
|------|------|------|
| GET  | `/zs-ai/api/info` | 服务信息 |
| POST | `/zs-ai/api/threads` | 创建线程 |
| GET  | `/zs-ai/api/threads/{thread_id}` | 获取线程 |
| POST | `/zs-ai/api/threads/search` | 搜索线程 |
| GET  | `/zs-ai/api/threads/{thread_id}/state` | 获取线程状态 |
| POST | `/zs-ai/api/threads/{thread_id}/history` | 获取线程历史 |
| POST | `/zs-ai/api/threads/{thread_id}/runs/stream` | 带线程流式对话（SSE） |
| POST | `/zs-ai/api/runs/stream` | 无线程流式对话（SSE） |
| POST | `/zs-ai/api/chat/stream` | 简化流式对话（SSE） |

> **注意：** BFF 仅允许白名单路径，非白名单返回 404；客户端无需手动携带 `X-API-Key`，由 BFF 统一注入。

---

## 3. FastAPI 直连接口（全量）

直连基地址：`http://<host>:8008`

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET  | `/health` | 无 | 健康检查 |
| GET  | `/info` | 无 | 服务信息 |
| GET  | `/metrics` | 无 | Prometheus 指标 |
| POST | `/threads` | `X-API-Key` + `X-Device-Id` | 创建线程 |
| GET  | `/threads/{thread_id}` | `X-API-Key` + `X-Device-Id` | 获取线程 |
| POST | `/threads/search` | `X-API-Key` + `X-Device-Id` | 搜索线程 |
| GET  | `/threads/{thread_id}/state` | `X-API-Key` + `X-Device-Id` | 获取线程状态 |
| POST | `/threads/{thread_id}/history` | `X-API-Key` + `X-Device-Id` | 获取线程历史 |
| POST | `/threads/{thread_id}/runs/stream` | `X-API-Key` + `X-Device-Id` | 带线程流式对话（SSE） |
| POST | `/runs/stream` | `X-API-Key` + `X-Device-Id` | 无线程流式对话（SSE） |
| POST | `/api/chat/stream` | `X-API-Key` | 简化流式对话（SSE） |
| GET  | `/admin/collection/stats` | `X-API-Key` | 向量库统计 |
| POST | `/admin/ingest` | `X-API-Key` | 文件热加载入库 |
| GET  | `/wx` | 签名验证 | 微信服务器验证（需 `WECHAT_ENABLED=true`） |
| POST | `/wx` | 签名验证 | 微信消息回调（需 `WECHAT_ENABLED=true`） |

---

## 4. 接口详情

### 4.1 健康与服务信息

#### `GET /health`

无需鉴权。

**响应（200 / 503）：**
```json
{
  "ok": true,
  "runtime_ready": true
}
```

运行时未就绪时返回 503，`ok` 和 `runtime_ready` 均为 `false`。

---

#### `GET /info`

无需鉴权。

**响应（200）：**
```json
{
  "name": "alayagent-langgraph-compat",
  "version": "0.2.0",
  "runtime_ready": true,
  "assistant_id": "agent",
  "api_key_required": true
}
```

---

#### `GET /metrics`

无需鉴权。需安装 `prometheus_client`，否则返回 501。返回 Prometheus 文本格式。

---

### 4.2 线程管理

线程接口均需要 `X-API-Key` 和 `X-Device-Id` 请求头。

---

#### `POST /threads` — 创建线程

**请求体：**
```json
{
  "thread_id": "my-thread-001",
  "metadata": {"source": "web"},
  "if_exists": null
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `thread_id` | string | 否 | 自定义 ID，`[a-zA-Z0-9_\-]`，最长 128 字符；缺省时自动生成 |
| `metadata` | object | 否 | 自定义元数据，序列化后不超过 4 KiB |
| `if_exists` | string | 否 | 最长 32 字符 |

**响应（200）：**
```json
{
  "thread_id": "my-thread-001",
  "created_at": "2026-03-29T08:00:00Z",
  "updated_at": "2026-03-29T08:00:00Z",
  "state_updated_at": "2026-03-29T08:00:00Z",
  "metadata": {"source": "web", "graph_id": "agent", "device_id": "device-123"},
  "status": "idle",
  "values": {},
  "interrupts": {}
}
```

---

#### `GET /threads/{thread_id}` — 获取线程

**路径参数：** `thread_id` — 线程 ID

**响应（200）：** 同创建线程响应结构。

**错误：** 线程不存在或设备 ID 不匹配返回 404。

---

#### `POST /threads/search` — 搜索线程

**请求体：**
```json
{
  "metadata": {"source": "web"},
  "limit": 10,
  "offset": 0
}
```

| 字段 | 类型 | 默认值 | 说明 |
|------|------|--------|------|
| `metadata` | object | null | 按元数据过滤 |
| `limit` | int | 10 | 返回数量上限 |
| `offset` | int | 0 | 分页偏移 |

**响应（200）：** 线程对象数组（结构同创建线程响应）。

---

#### `GET /threads/{thread_id}/state` — 获取线程状态

**响应（200）：** 线程当前图状态字典（LangGraph checkpoint 格式）。

---

#### `POST /threads/{thread_id}/history` — 获取线程历史

**请求体：**
```json
{
  "limit": 10,
  "before": null,
  "metadata": null,
  "checkpoint": null
}
```

**响应（200）：** 历史状态数组，每项包含 checkpoint 信息。

---

### 4.3 流式对话（SSE）

所有流式接口均返回 `Content-Type: text/event-stream`，每条事件格式为：

```
event: <event_name>
data: <json_payload>

```

---

#### `POST /threads/{thread_id}/runs/stream` — 带线程流式对话

需要 `X-API-Key` 和 `X-Device-Id`。线程已有活跃 run 时返回 409。

**请求体（`RunStreamRequest`）：**
```json
{
  "input": {"messages": [{"role": "user", "content": "你好"}]},
  "stream_mode": "values",
  "assistant_id": "agent",
  "metadata": null,
  "config": null
}
```

| 字段 | 类型 | 说明 |
|------|------|------|
| `input` | any | 传入图的输入负载 |
| `stream_mode` / `streamMode` | string \| string[] | 流模式，如 `"values"`、`"updates"` |
| `assistant_id` / `assistantId` | string | 默认 `"agent"` |
| `stream_subgraphs` | bool | 是否流式输出子图事件 |
| `checkpoint` / `checkpoint_id` | object / string | 从指定检查点恢复 |
| `config` | object | 图配置覆盖 |
| `context` | object | 额外上下文 |
| `command` | object | 图命令 |
| `metadata` | object | 附加元数据（≤4 KiB） |

> 字段名同时支持 `snake_case` 和 `camelCase`。

**响应头：**
```
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
X-Accel-Buffering: no
Content-Location: /threads/{thread_id}/runs/{run_id}
```

---

#### `POST /runs/stream` — 无线程流式对话

无需指定 thread_id，自动创建线程。请求体同上。

响应头中 `Content-Location` 携带自动生成的线程和 run 路径。

---

#### `POST /api/chat/stream` — 简化流式对话

需要 `X-API-Key`，**无需** `X-Device-Id`。

**请求体（`ChatStreamRequest`）：**
```json
{
  "session_id": "session-abc123",
  "message": "我想了解招生政策",
  "trace_id": "trace-001"
}
```

| 字段 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `session_id` | string | 是 | 8–128 字符，`[a-zA-Z0-9_\-]` |
| `message` | string | 是 | 用户消息，1–4000 字符 |
| `trace_id` | string | 否 | 日志追踪 ID，最长 128 字符 |

**SSE 事件流：**

| 事件名 | 数据示例 | 说明 |
|--------|---------|------|
| `session.started` | `{"session_id": "..."}` | 会话开始 |
| `stage.started` | `{"stage": "retrieval", "session_id": "..."}` | 处理阶段开始 |
| `stage.completed` | `{"stage": "retrieval", "session_id": "...", ...}` | 处理阶段完成 |
| `message.completed` | `{"session_id": "...", "answer": "...", "elapsed_ms": 1200}` | 完整回答就绪 |
| `done` | `{"session_id": "..."}` | 流结束 |
| `error` | 见[错误响应](#7-错误响应) | 发生错误 |

---

### 4.4 管理接口

管理接口均需要 `X-API-Key`，不需要 `X-Device-Id`。

---

#### `GET /admin/collection/stats` — 向量库统计

**响应（200）：**
```json
{
  "num_entities": 1024,
  "collection_name": "alaya_docs"
}
```

---

#### `POST /admin/ingest` — 文件热加载入库

Content-Type: `multipart/form-data`

**Query 参数：**

| 参数 | 类型 | 必填 | 说明 |
|------|------|------|------|
| `category` | string | 否 | 文档分类标签 |

**Form 字段：**

| 字段 | 说明 |
|------|------|
| `file` | 上传文件，支持 `.md` `.txt` `.doc` `.docx` `.pdf` `.xlsx` |

**响应（200）：**
```json
{
  "inserted": 42,
  "collection": {
    "num_entities": 1066,
    "collection_name": "alaya_docs"
  }
}
```

**错误：**
- 400：不支持的文件类型
- 500：入库失败

---

### 4.5 微信公众号接口（可选）

需在 `.env` 中设置 `WECHAT_ENABLED=true` 才会注册以下路由。

---

#### `GET /wx` — 微信服务器验证

**Query 参数：**

| 参数 | 说明 |
|------|------|
| `signature` | 微信签名 |
| `timestamp` | 时间戳 |
| `nonce` | 随机数 |
| `echostr` | 微信发送的随机字符串 |

**响应：** 签名验证通过返回 `echostr` 明文，失败返回 403。

---

#### `POST /wx` — 微信消息回调

**Query 参数：** 同 GET `/wx`（`signature`、`timestamp`、`nonce`）

**请求体：** XML 格式（微信标准格式）

**响应：** XML 格式文本回复（微信被动回复格式）

**特性：**
- 仅支持文字消息，其他类型提示用户发文字
- 回复超过 2048 字节时自动分页，用户发任意消息获取下一页
- 支持消息去重与重试（同一 MsgId 重发时等待 AI 完成）
- AI 思考中时返回提示，用户稍后发消息获取结果

**回调地址配置示例：**
- 直接回调：`https://<domain>/wx`（需 Nginx 转发到 backend 端口）
- 带前缀回调：`https://<domain>/zs-wx-ai/wx`（Nginx 重写去前缀后转发）

---

## 5. 鉴权与请求头

### `X-API-Key`

后端通过环境变量 `API_SHARED_KEY` 配置共享密钥。以下路径**免鉴权**：

- `/health`
- `/info`
- `/metrics`
- `/wx`

其余所有接口均需在请求头中携带：

```
X-API-Key: <API_SHARED_KEY>
```

若 `API_SHARED_KEY` 未配置，后端不校验此头（开发/测试模式）。

BFF 模式下前端无需手动携带，由 BFF 统一注入。

---

### `X-Device-Id`

线程相关接口（创建、查询、运行）均需要此头，用于：

1. **线程归属校验**：只能访问自己设备创建的线程
2. **限流统计**：按设备 ID 计算滑动窗口请求数

格式要求：1–128 字符，`[a-zA-Z0-9_\-]`

```
X-Device-Id: device-abc-123
```

缺失或格式错误返回 400。

---

## 6. SSE 事件格式

所有流式接口均使用 Server-Sent Events（SSE）协议：

```
event: <event_name>
data: {"key": "value"}

```

**注意：** 每条事件后有两个换行符。

### `stream_mode` 可选值（LangGraph 兼容接口）

| 值 | 说明 |
|----|------|
| `values` | 每步输出完整图状态 |
| `updates` | 每步输出增量更新 |
| `messages` | 输出 LLM 消息流 |

### 超时事件

当流空闲超时或达到最大时长时，后端会推送 `error` 事件后关闭连接：

```json
{
  "code": "REQUEST_TIMEOUT",
  "timeout_kind": "stream_idle_timeout",
  "message": "Stream closed after 30s without events"
}
```

`timeout_kind` 可选值：
- `stream_idle_timeout`：空闲超时（默认 30s）
- `stream_max_duration_timeout`：总时长超时（默认 120s）

---

## 7. 错误响应

### 标准错误格式（非 SSE）

```json
{
  "code": "INTERNAL_ERROR",
  "message": "服务内部异常，请稍后重试。"
}
```

### 超时错误格式

```json
{
  "code": "REQUEST_TIMEOUT",
  "timeout_kind": "upstream_timeout",
  "message": "Upstream request timed out",
  "model_kind": "chat",
  "provider": "openai",
  "timeout_seconds": 60
}
```

### HTTP 状态码

| 状态码 | 含义 |
|--------|------|
| 400 | 请求参数错误（缺失必填项、格式不合法） |
| 401 | 未授权（`X-API-Key` 缺失或错误） |
| 403 | 禁止访问（微信签名验证失败） |
| 404 | 资源不存在（线程不存在或设备 ID 不匹配） |
| 409 | 冲突（线程已有活跃 run） |
| 413 | 请求体过大（超过 64 KiB） |
| 429 | 请求过频（限流） |
| 500 | 服务内部错误 |
| 503 | 服务不可用（运行时未就绪） |

### 错误代码（`code` 字段）

| 代码 | 说明 |
|------|------|
| `REQUEST_TIMEOUT` | 上游请求超时或流超时 |
| `MODEL_UNAVAILABLE` | AI 模型暂时不可用 |
| `VECTOR_STORE_ERROR` | 向量数据库检索异常 |
| `INTERNAL_ERROR` | 未分类内部错误 |
| `THREAD_BUSY` | 线程已有活跃 run（409） |
| `RUNTIME_NOT_READY` | 服务正在启动（仅出现在 SSE 错误事件） |

---

## 8. 限流与超时

### 设备级限流

基于 `X-Device-Id` 的滑动窗口计数器：

| 配置项 | 环境变量 | 默认值 |
|--------|---------|--------|
| 窗口内最大请求数 | `DEVICE_RATE_LIMIT_MAX` | 30 |
| 窗口时长（秒） | `DEVICE_RATE_LIMIT_WINDOW` | 60 |

超出限制返回 429。

免限流路径：`/health`、`/info`、`/metrics`、`/wx`

### 流式超时

| 配置项 | 环境变量 | 默认值 |
|--------|---------|--------|
| 空闲超时（秒） | `STREAM_IDLE_TIMEOUT_SECONDS` | 30 |
| 最大总时长（秒） | `STREAM_MAX_DURATION_SECONDS` | 120 |

---

## 9. CORS 配置

通过 `CORS_ALLOWED_ORIGINS` 环境变量（逗号分隔的域名列表）启用。

```env
CORS_ALLOWED_ORIGINS=https://example.com,https://app.example.com
```

启用后：
- 允许方法：`GET`、`POST`、`OPTIONS`
- 允许头：`Content-Type`、`X-Device-Id`

默认不启用（BFF 架构下浏览器不直连后端，无需 CORS）。

---

## 10. 快速调用示例

### 健康检查

```bash
curl http://localhost:8008/health
```

### 创建线程

```bash
curl -X POST "http://localhost:8008/threads" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <API_SHARED_KEY>" \
  -H "X-Device-Id: device-001" \
  -d '{"metadata": {"source": "manual"}}'
```

### 带线程流式对话

```bash
curl -N -X POST "http://localhost:8008/threads/<thread_id>/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <API_SHARED_KEY>" \
  -H "X-Device-Id: device-001" \
  -d '{"input": {"messages": [{"role": "user", "content": "你好"}]}, "stream_mode": "values"}'
```

### 简化流式对话

```bash
curl -N -X POST "http://localhost:8008/api/chat/stream" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: <API_SHARED_KEY>" \
  -d '{"session_id": "session-abc123", "message": "请介绍一下招生政策"}'
```

### 文件热加载

```bash
curl -X POST "http://localhost:8008/admin/ingest?category=policy" \
  -H "X-API-Key: <API_SHARED_KEY>" \
  -F "file=@/path/to/document.pdf"
```

### 通过 BFF 获取服务信息

```bash
curl "http://localhost:3001/zs-ai/api/info"
```

---

## 11. 环境变量参考

| 变量名 | 说明 | 默认值 |
|--------|------|--------|
| `API_SHARED_KEY` | API 鉴权密钥，为空时不校验 | （空） |
| `STREAM_IDLE_TIMEOUT_SECONDS` | 流空闲超时秒数 | `30` |
| `STREAM_MAX_DURATION_SECONDS` | 流最大总时长秒数 | `120` |
| `DEVICE_RATE_LIMIT_MAX` | 滑动窗口内最大请求数/设备 | `30` |
| `DEVICE_RATE_LIMIT_WINDOW` | 滑动窗口时长（秒） | `60` |
| `CORS_ALLOWED_ORIGINS` | 允许跨域的来源，逗号分隔 | （空，禁用） |
| `WECHAT_ENABLED` | 启用微信公众号接口（`true`/`1`/`yes`） | `false` |
| `WECHAT_TOKEN` | 微信服务器配置中的 Token | （必填，启用时） |

---

## 12. 已知注意事项

1. **`chat/stream` 路径映射差异**：FastAPI 实际端点是 `POST /api/chat/stream`，BFF 白名单使用 `chat/stream`，上游拼接后变成 `/chat/stream`。若不做兼容处理，BFF 调用该接口可能 404。

2. **`/wx` Nginx 转发**：`/wx` 已在 FastAPI 注册，但默认 Nginx 配置未单独将 `/wx` 转发至 backend。公网对接公众号需在 Nginx 增加对应 location（参考 `DEPLOY.md` 中的 `/zs-wx-ai/` 配置示例）。

---

## 13. 参考实现文件

| 文件 | 说明 |
|------|------|
| `src/api/chat_app.py` | FastAPI 主路由与中间件 |
| `src/api/wechat.py` | 微信适配路由 |
| `src/api/observability.py` | `/metrics` 与访问日志 |
| `src/runtime/graph_runtime.py` | 运行时核心 |
| `web/src/lib/server/backend-proxy.ts` | BFF 路径白名单与转发 |
| `web/src/app/api/[[...path]]/route.ts` | Next.js API 代理入口 |
| `web/next.config.mjs` | `basePath=/zs-ai` 配置 |
| `infra/nginx/alaya-enrollment.conf` | Nginx 转发规则 |
| `docker-compose.yml` | 端口映射 |
