# AlayaEnrollment

招生问答项目，包含：

- FastAPI 后端服务
- LangGraph 对话编排
- Milvus 向量检索
- `web/` 前端页面

## 本地部署

### 1. 环境准备

需要先安装：

- Python
- Node.js
- Docker / Docker Desktop

### 2. 配置环境变量

将 `.env.example` 复制为 `.env`，并至少检查这些变量：

- `AlayaData_URL`
- `MILVUS_URI`
- `EMBED_DIM`
- `DEEPSEEK_API_KEY` 或 `QWEN_API_KEY`

示例：

```bash
cp .env.example .env
```

PowerShell 可用：

```powershell
Copy-Item .env.example .env
```

### 3. 启动后端

先安装 Python 依赖：

```bash
pip install -r requirements.txt
```

启动 Milvus 及 API：

```bash
python main.py
```

如果只启动 API：

```bash
python main.py --skip-infra
```

默认端口：

- API: `http://localhost:8008`
- Attu: `http://localhost:8000`
- Milvus: `localhost:19530`

健康检查：

```bash
curl http://localhost:8008/health
```

### 4. 启动前端

开发模式：

```bash
cd web
npm install
npm run dev
```

生产模式：

```bash
cd web
npm install
npm run build
npm run start
```

默认地址：

- `http://localhost:3000`

## 数据导入与检索

导入整个目录：

```bash
python -m script.ingest_all --dir ./data/raw/unstructured
```

导入单个文件：

```bash
python -m script.ingest_file --file ./data/raw/unstructured/本科专业.md --category major
```

检索验证：

```bash
python -m script.demo_vector_search --query "本科专业" --top-k 3
```

## 结构化 SQL 数据

当前结构化录取数据改为手工维护流程：

- 手工创建 `data/db/admissions.db`
- 手工执行建表 SQL
- 手工把 Excel / CSV 数据导入 SQLite
- `src/config/table_registry.yaml` 只保留查询元数据，不再负责建表或导入
- `src/knowledge/sql_queries.py` 保存手写 SQL 查询函数

校验已注册表和查询键：

```bash
python -m src.knowledge.manage validate-sql
```

调试 `admission_scores` 查询：

```bash
python -m src.knowledge.manage query-admission-scores --province 安徽 --year 2024
```

## 服务器部署

适用于单机部署场景，默认后端 `8008`、前端 `3000`。

### 环境变量拆分

- `.env`（服务器上）包含私密变量：`API_SHARED_KEY`、`BACKEND_INTERNAL_URL`、`STREAM_MAX_DURATION_SECONDS`、`STREAM_IDLE_TIMEOUT_SECONDS`、各大模型 Key、Milvus/Langfuse 配置等；该文件只给后端 / Next.js 服务端读取。
- `web/.env.local` 只保留 `NEXT_PUBLIC_*` 这类前端需要暴露的变量，部署脚本在构建前写入或由 CI 注入。

示例：

```bash
cp .env.example .env         # 服务器私密变量
cp web/.env.example web/.env.local  # 如果需要前端自定义公开变量
```

### 1. 拉取代码并配置环境变量

```bash
git clone <your-repo-url>
cd AlayaEnrollment
cp .env.example .env
```

生产环境建议额外配置：

```bash
export RUNTIME_ROOT=/var/lib/alaya-enrollment/runtime
```

- `RUNTIME_ROOT` 应指向仓库外的持久目录。
- 运行时文件会落在 `$RUNTIME_ROOT/chat-api/` 下，包括 `checkpoints.sqlite`
  和 `thread_registry.sqlite`。
- 当前后端运行时模型仍然是单 worker；`RUNTIME_ROOT` 只解决持久化与重启
  一致性，不会让多 worker 自动变安全。

### 2. 启动后端

前台启动：

```bash
python main.py --host 127.0.0.1 --port 8008
```

后台启动：

```bash
export RUNTIME_ROOT="${RUNTIME_ROOT:-/var/lib/alaya-enrollment/runtime}"
mkdir -p "$RUNTIME_ROOT"
nohup python main.py --host 127.0.0.1 --port 8008 > "$RUNTIME_ROOT"/backend.log 2>&1 &
```

- 如果需要关闭自动拉起 Milvus，可提前在服务器上运行 `docker compose -f infra/docker/milvus-compose.yml up -d`，再在后端命令追加 `--skip-infra`。
- `API_SHARED_KEY` 会被 FastAPI 中间件校验，但密钥只由 Next.js BFF 在服务端注入；浏览器和 Nginx 都不再直接携带该值。
- `STREAM_MAX_DURATION_SECONDS` 和 `STREAM_IDLE_TIMEOUT_SECONDS` 会保护三个流式入口：`/api/chat/stream`、`/runs/stream`、`/threads/{id}/runs/stream`。
- 生产环境不要把 `RUNTIME_ROOT` 指回仓库目录；否则部署或清理工作区时仍然可能误删运行时数据。
- Nginx 需要对公网流式入口做基础 IP 限流，示例：

```
limit_req_zone $binary_remote_addr zone=alaya_stream_per_ip:10m rate=20r/m;

server {
  limit_req_status 429;

  location = /api/chat/stream {
    limit_req zone=alaya_stream_per_ip burst=10 nodelay;
    proxy_pass http://127.0.0.1:3000;
    proxy_buffering off;
    proxy_read_timeout 600s;
  }
}
```

### 3. 启动前端

```bash
cd web
npm install
npm run build
export RUNTIME_ROOT="${RUNTIME_ROOT:-/var/lib/alaya-enrollment/runtime}"
mkdir -p "$RUNTIME_ROOT"
nohup npm run start -- --hostname 0.0.0.0 --port 3000 > "$RUNTIME_ROOT"/frontend.log 2>&1 &
```

### 4. 导入知识库

```bash
cd ..
python -m script.ingest_all --dir ./data/raw/unstructured
```

### 5. 验证服务

```bash
curl http://127.0.0.1:8008/health
curl http://127.0.0.1:3000
python -m script.demo_vector_search --query "本科专业" --top-k 3
```

## API 保护与限流

- 设置 `API_SHARED_KEY` 后，所有除 `/health`、`/info` 以外的 FastAPI 接口都需要 `X-Api-Key` 请求头；在当前单机部署中，这个头只由 Next.js BFF 在服务端注入。
- `/threads/{id}/runs/stream` 启用 per-thread single-flight；同一线程已有流式运行时，后续请求会返回 `409 THREAD_BUSY`，避免线程状态并发写乱。
- `STREAM_MAX_DURATION_SECONDS` 和 `STREAM_IDLE_TIMEOUT_SECONDS` 会限制 `/api/chat/stream`、`/runs/stream`、`/threads/{id}/runs/stream` 的总时长和空闲时长，防止请求长期挂死占住资源。
- 公网入口的基础 IP 限流由 Nginx `limit_req` 实现，默认只对上述三个流式路径生效，超限返回 `429`。
- 当前 single-flight 为进程内实现，适用于单机单 worker；后续如果部署多个 worker，需要改成 Redis 或网关层的共享租约/配额模型。

## Langfuse

- 只有在 `LANGFUSE_ENABLED=true` 时，后端才会初始化 Langfuse 并上报追踪数据。
- 即使配置了 `LANGFUSE_PUBLIC_KEY`、`LANGFUSE_SECRET_KEY`、`LANGFUSE_HOST`，只要 `LANGFUSE_ENABLED` 未开启或为 `false`，就不会上报。
- 当前运行时会在请求结束时显式调用 Langfuse client 的 `flush()`，并在服务关闭时调用 `shutdown()`，避免对话 trace 长时间留在本地队列里不出现在 Langfuse UI。

## 推荐顺序

```bash
cp .env.example .env
python main.py
python -m script.ingest_all --dir ./data/raw/unstructured
python -m script.demo_vector_search --query "本科专业" --top-k 3
```
