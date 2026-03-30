# AlayaEnrollment 内网访问指南（其他机器）

本文档面向需要从**内网其他机器**调用 AlayaEnrollment API 的开发者或集成方。

---

## 端口可达性

| 服务 | 宿主机绑定 | 内网其他机器是否可达 | 说明 |
|------|-----------|-------------------|------|
| FastAPI Backend | `0.0.0.0:8008` | **可达** | 全量接口，需手动携带鉴权头 |
| Nginx | `0.0.0.0:8082` | **可达** | 代理到 BFF，白名单接口 |
| Next.js BFF | `127.0.0.1:3001` | **不可达** | 仅本机可访问，其他机器无法直连 |

> 以下示例中将部署机 IP 记为 `<HOST>`，请替换为实际 IP（例如 `192.168.1.100`）。

---

## 方式一：直连 FastAPI（推荐用于服务间调用）

**基础地址：** `http://<HOST>:8008`

### 鉴权

需要在每个请求中携带：

```
X-API-Key: <API_SHARED_KEY>        # 对应 .env 中的 API_SHARED_KEY
X-Device-Id: <your-device-id>      # 格式：1-128字符，[a-zA-Z0-9_\-]
```

`/health`、`/info`、`/metrics`、`/wx` 四个路径无需鉴权。

### 可用接口

| 方法 | 路径 | 鉴权 | 说明 |
|------|------|------|------|
| GET  | `/health` | 无 | 健康检查 |
| GET  | `/info` | 无 | 服务信息 |
| GET  | `/metrics` | 无 | Prometheus 指标 |
| POST | `/threads` | Key + Device | 创建线程 |
| GET  | `/threads/{thread_id}` | Key + Device | 获取线程 |
| POST | `/threads/search` | Key + Device | 搜索线程 |
| GET  | `/threads/{thread_id}/state` | Key + Device | 获取线程状态 |
| POST | `/threads/{thread_id}/history` | Key + Device | 获取线程历史 |
| POST | `/threads/{thread_id}/runs/stream` | Key + Device | 带线程流式对话（SSE） |
| POST | `/runs/stream` | Key + Device | 无线程流式对话（SSE） |
| POST | `/api/chat/stream` | Key（无需 Device） | 简化流式对话（SSE） |
| GET  | `/admin/collection/stats` | Key（无需 Device） | 向量库统计 |
| POST | `/admin/ingest` | Key（无需 Device） | 文件热加载入库 |

### 调用示例

**健康检查：**
```bash
curl http://<HOST>:8008/health
```

**创建线程：**
```bash
curl -X POST "http://<HOST>:8008/threads" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "X-Device-Id: intranet-client-01" \
  -d '{"metadata": {"source": "intranet"}}'
```

**带线程流式对话（SSE）：**
```bash
curl -N -X POST "http://<HOST>:8008/threads/<thread_id>/runs/stream" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -H "X-Device-Id: intranet-client-01" \
  -d '{
    "input": {"messages": [{"role": "user", "content": "介绍一下招生政策"}]},
    "stream_mode": "values"
  }'
```

**简化流式对话（SSE，无需线程管理）：**
```bash
curl -N -X POST "http://<HOST>:8008/api/chat/stream" \
  -H "Content-Type: application/json" \
  -H "X-API-Key: change-me" \
  -d '{
    "session_id": "intranet-session-001",
    "message": "录取分数线是多少？"
  }'
```

**文件热加载入库：**
```bash
curl -X POST "http://<HOST>:8008/admin/ingest?category=policy" \
  -H "X-API-Key: change-me" \
  -F "file=@/path/to/document.pdf"
```

---

## 方式二：经由 Nginx（与公网行为一致）

**基础地址：** `http://<HOST>:8082`

适合不需要管理接口、只需对话功能的场景。客户端**无需携带** `X-API-Key`，由 BFF 统一注入。

### 限流

Nginx 对流式接口按来源 IP 限流：**每分钟 20 次，允许突发 10 次**。大批量调用请使用方式一（直连 FastAPI）。

### 可用接口

路径前缀 `/zs-ai/api`：

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

> **注意：** 非白名单路径（如 `/admin/*`）经 BFF 会返回 404。

### 调用示例

`X-Device-Id` 仍需客户端自行携带（BFF 只注入 `X-API-Key`）。

**服务信息：**
```bash
curl "http://<HOST>:8082/zs-ai/api/info"
```

**创建线程：**
```bash
curl -X POST "http://<HOST>:8082/zs-ai/api/threads" \
  -H "Content-Type: application/json" \
  -H "X-Device-Id: intranet-client-01" \
  -d '{"metadata": {"source": "intranet"}}'
```

**简化流式对话（SSE）：**
```bash
curl -N -X POST "http://<HOST>:8082/zs-ai/api/chat/stream" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "intranet-session-001",
    "message": "录取分数线是多少？"
  }'
```

---

## 选择方式对比

| 需求 | 推荐方式 |
|------|---------|
| 对话功能、简单集成 | 方式二（Nginx，无需管鉴权） |
| 管理接口（入库、统计） | 方式一（直连 FastAPI） |
| 高频调用、批量请求 | 方式一（直连 FastAPI，无 Nginx 限流） |
| 线程管理 + 对话 | 任一方式（方式一路径更短） |

---

## SSE 接收注意事项

所有流式接口返回 `text/event-stream`，事件格式：

```
event: <event_name>
data: {"key": "value"}

```

客户端需设置：
- 不缓冲响应（`-N` in curl）
- 连接超时需大于 `STREAM_MAX_DURATION_SECONDS`（默认 120s）

Python 示例（使用 `httpx`）：

```python
import httpx

with httpx.Client(timeout=130) as client:
    with client.stream(
        "POST",
        "http://<HOST>:8008/api/chat/stream",
        headers={
            "Content-Type": "application/json",
            "X-API-Key": "change-me",
        },
        json={"session_id": "session-001", "message": "介绍招生政策"},
    ) as resp:
        for line in resp.iter_lines():
            print(line)
```

---

## 常见错误

| 状态码 | 原因 | 处理 |
|--------|------|------|
| 400 | `X-Device-Id` 缺失或格式错误 | 检查格式 `[a-zA-Z0-9_\-]`，1-128字符 |
| 401 | `X-API-Key` 错误或缺失 | 检查 `.env` 中的 `API_SHARED_KEY` |
| 404 | 线程不存在，或设备 ID 与创建时不符 | 使用创建线程时的同一 `X-Device-Id` |
| 409 | 线程已有活跃 run | 等待上一个请求完成后再发起 |
| 429 | 触发限流 | 方式二：Nginx 20次/分钟限制；方式一：设备级 30次/60秒限制 |
| 503 | 服务尚未就绪 | 等待启动完成，`/health` 返回 `ok: true` 后再调用 |
