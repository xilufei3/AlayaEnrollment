# 部署指南

本文档说明 AlayaEnrollment 系统的完整部署流程，适用于单机 Linux 服务器。

---

## 目录

- [架构概览](#架构概览)
- [前置条件](#前置条件)
- [方式一：Docker Compose 部署（推荐）](#方式一docker-compose-部署推荐)
- [方式二：裸机部署](#方式二裸机部署)
- [Nginx 与 HTTPS](#nginx-与-https)
- [知识库初始化](#知识库初始化)
- [运行验证](#运行验证)
- [运维操作](#运维操作)
- [环境变量参考](#环境变量参考)
- [常见问题](#常见问题)

---

## 架构概览

```
                    ┌──────────┐
    用户浏览器 ───→ │  Nginx   │ :80 / :443
                    │ 限流+安全头│
                    └────┬─────┘
                         │
                    ┌────▼─────┐
                    │  Next.js │ :3000（BFF 代理）
                    │  注入 API Key
                    └────┬─────┘
                         │
                    ┌────▼─────┐        ┌──────────┐
                    │ FastAPI  │ :8008 → │  Milvus  │ :19530
                    │ LangGraph│        │ 向量检索  │
                    └────┬─────┘        └──────────┘
                         │
                    ┌────▼─────┐
                    │  SQLite  │ checkpoint / thread_registry / admissions.db
                    └──────────┘
```

> Docker Compose 模式默认通过 `WEB_HOST_PORT=3001` 将 Next.js 暴露到宿主机（默认 `http://localhost:3001`），可在 `.env` 中自定义；裸机或本地 `npm run dev` 仍使用 3000。

关键设计：
- **浏览器永远不直连 FastAPI**，通过 Next.js BFF 代理，API Key 在服务端注入
- **Nginx** 统一入口，处理限流、安全头、HTTPS
- **Milvus** 向量数据库运行在 Docker 中，etcd + MinIO 作为依赖

---

## 前置条件

| 依赖 | 最低版本 | 说明 |
|---|---|---|
| Docker + Docker Compose | Docker 24+ / Compose v2 | 所有服务容器化 |
| 磁盘 | 10 GB 可用 | Milvus 索引 + MinIO 存储 |
| 内存 | 4 GB+ | Milvus standalone 约占 2 GB |
| 网络 | 可达外部 API | Qwen/DeepSeek API、Qwen Reranker、Embedding 服务 |

裸机部署额外需要：Python 3.11+、Node.js 20+。

---

## 方式一：Docker Compose 部署（推荐）

### 1. 获取代码

```bash
git clone <repo-url>
cd AlayaEnrollment
```

### 2. 配置环境变量

```bash
cp .env.example .env
```

必须修改的变量：

```bash
# 至少配置一个 LLM Provider
QWEN_API_KEY=your-qwen-key
QWEN_BASE_URL=http://star.sustech.edu.cn/service/model/qwen35/v1

# Reranker（默认 Qwen）
RERANK_PROVIDER=qwen
RERANK_MODEL_NAME=qwen3-rerank
# 如需单独密钥可填写；留空时默认复用 QWEN_API_KEY
RERANK_API_KEY=

# BFF 共享密钥（生产环境务必修改）
API_SHARED_KEY=your-random-secret-here

# MinIO 密码（生产环境务必修改）
MINIO_ACCESS_KEY=your-minio-access-key
MINIO_SECRET_KEY=your-minio-secret-key
```

### 3. 启动全部服务

```bash
docker compose up --build -d
```

启动顺序由 Compose 自动管理：

```
etcd → minio → milvus (healthcheck 通过后) → backend → web → nginx
```

### 4. 验证

```bash
# 检查所有服务状态
docker compose ps

# 健康检查
curl http://localhost/health

# 查看日志
docker compose logs -f backend
docker compose logs -f web
```

### 5. 导入知识库

```bash
# 进入后端容器执行
docker compose exec backend python -m script.ingest_all --dir ./data/raw/unstructured

# 导入 SQL 结构化数据
docker compose exec backend python sql/demo_admission_scores.py --reset
```

或者通过 API 热灌库（服务运行中）：

```bash
curl -X POST -H "X-API-Key: your-api-key" \
  -F "file=@data/raw/unstructured/some_doc.md" \
  -F "category=admissions" \
  http://localhost:8008/admin/ingest
```

### 6. 停止 / 重启

```bash
docker compose down          # 停止所有服务（数据保留在 volume 中）
docker compose up -d         # 重新启动（无需 --build，除非代码有变）
docker compose down -v       # 停止并删除所有数据（慎用！）
```

---

## 方式二：裸机部署

适用于需要直接调试或无法使用 Docker 全栈的场景。

### 1. 安装依赖

```bash
pip install -r requirements.txt
cd web && npm install && cd ..
```

### 2. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，配置 API Key、Milvus 地址等

# 生产环境建议将运行时数据放在仓库外
export RUNTIME_ROOT=/var/lib/alaya-enrollment/runtime
mkdir -p "$RUNTIME_ROOT"
```

### 3. 启动后端

```bash
# 前台启动（调试用）
python main.py --host 127.0.0.1 --port 8008

# 后台启动
nohup python main.py --host 127.0.0.1 --port 8008 \
  > "$RUNTIME_ROOT/backend.log" 2>&1 &

# 如果 Milvus 已经在跑
python main.py --skip-infra --host 127.0.0.1 --port 8008
```

### 4. 启动前端

```bash
cd web
npm run build
nohup npm run start -- --hostname 0.0.0.0 --port 3000 \
  > "$RUNTIME_ROOT/frontend.log" 2>&1 &
```

### 5. 配置 Nginx

```bash
# 复制配置文件
sudo cp infra/nginx/alaya-enrollment.conf /etc/nginx/conf.d/alaya.conf

# 裸机部署需要修改 upstream 地址
# 编辑 /etc/nginx/conf.d/alaya.conf，将：
#   server web:3000;
# 改为：
#   server 127.0.0.1:3000;

sudo nginx -t && sudo systemctl reload nginx
```

### 6. 进程守护（推荐）

创建 systemd service 文件，避免进程挂了无人拉起：

```ini
# /etc/systemd/system/alaya-backend.service
[Unit]
Description=AlayaEnrollment Backend
After=docker.service

[Service]
Type=simple
User=deploy
WorkingDirectory=/opt/AlayaEnrollment
EnvironmentFile=/opt/AlayaEnrollment/.env
Environment=RUNTIME_ROOT=/var/lib/alaya-enrollment/runtime
ExecStart=/usr/bin/python main.py --skip-infra --host 127.0.0.1 --port 8008
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
```

```bash
sudo systemctl enable alaya-backend
sudo systemctl start alaya-backend
```

---

## Nginx 与 HTTPS

### 当前 Nginx 功能

| 功能 | 说明 |
|---|---|
| 反向代理 | 所有请求 → Next.js (web:3000) |
| 流式限流 | 20 req/min per IP（三个 SSE 端点） |
| 安全响应头 | X-Frame-Options / X-Content-Type-Options / Referrer-Policy |
| Gzip 压缩 | 压缩前端资源（不压缩 SSE） |

### 启用 HTTPS

`infra/nginx/alaya-enrollment.conf` 底部有注释版 HTTPS 模板。步骤：

```bash
# 1. 安装 certbot
sudo apt install certbot python3-certbot-nginx

# 2. 获取证书
sudo certbot --nginx -d your-domain.com

# 3. 编辑 nginx 配置，取消 HTTPS server block 的注释
#    将 YOUR_DOMAIN 替换为实际域名

# 4. 重载
sudo nginx -t && sudo systemctl reload nginx
```

---

## 知识库初始化

### 向量知识库

将文档（.md / .txt / .docx / .pdf）放入 `data/raw/unstructured/` 目录，然后：

```bash
# 批量导入（清空重建 collection）
python -m script.ingest_all --dir ./data/raw/unstructured

# 单文件追加（不清空）
python -m script.ingest_file --file ./data/raw/unstructured/new_doc.md --category admissions

# 查看向量库状态
curl -H "X-API-Key: $API_SHARED_KEY" http://localhost:8008/admin/collection/stats
```

### SQL 结构化数据

录取分数等结构化数据存在 SQLite 中：

```bash
# 建表 + 导入录取分数数据
python sql/demo_admission_scores.py --reset

# 验证
python -m src.knowledge.manage validate-sql
python -m src.knowledge.manage query-admission-scores --province 广东 --year 2024
```

SQL 建表脚本位于 `sql/manual/admission_scores/`，数据更新时修改 `import.sql` 后重新执行。

---

## 运行验证

### 健康检查

```bash
curl http://localhost/health            # Nginx → Web → Backend
curl http://localhost:8008/health       # Backend 直连
```

### Prometheus 指标

```bash
curl http://localhost:8008/metrics
```

关键指标：

| 指标 | 说明 |
|---|---|
| `http_requests_total` | HTTP 请求总量（按 method/path/status） |
| `http_request_duration_seconds` | 请求延迟分布 |
| `llm_requests_total` | LLM 调用总量（按 model_kind/status） |
| `llm_request_duration_seconds` | LLM 调用延迟 |
| `retrieval_requests_total` | 向量检索调用（按 mode/status） |
| `sql_query_total` | SQL 查询调用 |
| `embedding_requests_total` | Embedding 服务调用 |

### 日志

```bash
# Docker 模式
docker compose logs -f backend     # 后端日志
docker compose logs -f web         # 前端日志
docker compose logs -f nginx       # Nginx access log

# 裸机模式
tail -f "$RUNTIME_ROOT/backend.log"
```

Access log 为 JSON 格式，包含 method、path、status、latency_ms、device_id（脱敏）。

---

## 运维操作

### 热更新知识库（无需重启）

```bash
curl -X POST -H "X-API-Key: $API_SHARED_KEY" \
  -F "file=@new_policy.pdf" \
  -F "category=admissions" \
  http://localhost:8008/admin/ingest
```

### 查看向量库状态

```bash
curl -H "X-API-Key: $API_SHARED_KEY" http://localhost:8008/admin/collection/stats
```

### 数据备份

```bash
# SQLite 备份（checkpoint + thread_registry）
RUNTIME_ROOT=/var/lib/alaya-enrollment/runtime
sqlite3 "$RUNTIME_ROOT/chat-api/checkpoints.sqlite" ".backup /backup/checkpoints_$(date +%Y%m%d).db"
sqlite3 "$RUNTIME_ROOT/chat-api/thread_registry.sqlite" ".backup /backup/registry_$(date +%Y%m%d).db"

# Milvus 备份（Docker volume 快照）
docker run --rm -v alayaenrollment_milvus_data:/data -v /backup:/backup \
  alpine tar czf /backup/milvus_$(date +%Y%m%d).tar.gz -C /data .
```

### 重建服务

```bash
docker compose down
docker compose up --build -d    # 重新构建镜像并启动
```

---

## 环境变量参考

### 必填

| 变量 | 说明 |
|---|---|
| `QWEN_API_KEY` | Qwen 模型密钥 |
| `RERANK_API_KEY \| QWEN_API_KEY` | Reranker 密钥（默认复用 `QWEN_API_KEY`） |

### 强烈建议修改

| 变量 | 默认值 | 说明 |
|---|---|---|
| `API_SHARED_KEY` | `change-me` | BFF → Backend 共享密钥 |
| `MINIO_ACCESS_KEY` | `minioadmin` | MinIO 访问密钥 |
| `MINIO_SECRET_KEY` | `minioadmin` | MinIO 密码 |

### 可选

| 变量 | 默认值 | 说明 |
|---|---|---|
| `DEEPSEEK_API_KEY` | 空 | DeepSeek 模型密钥（可替代 Qwen） |
| `DEEPSEEK_BASE_URL` | `https://api.deepseek.com/v1` | DeepSeek API 地址 |
| `QWEN_BASE_URL` | `http://star.sustech.edu.cn/...` | Qwen API 地址 |
| `RERANK_PROVIDER` | `qwen` | 文档重排 provider，支持 `qwen` / `jina` |
| `RERANK_MODEL_NAME` | `qwen3-rerank` | 文档重排模型名 |
| `RERANK_BASE_URL` | DashScope text-rerank API | Qwen 文档重排接口地址 |
| `AlayaData_URL` | `http://100.64.0.30:6000` | Embedding 服务地址 |
| `MILVUS_URI` | `http://localhost:19530` | Milvus 连接地址 |
| `MILVUS_COLLECTION` | `admissions_knowledge` | 向量集合名 |
| `CORS_ALLOWED_ORIGINS` | 空（禁用） | 逗号分隔的 CORS 允许源 |
| `DEVICE_RATE_LIMIT_MAX` | `30` | 单设备请求上限/窗口 |
| `DEVICE_RATE_LIMIT_WINDOW` | `60` | 限流窗口秒数 |
| `STREAM_MAX_DURATION_SECONDS` | `120` | 流式请求最大时长 |
| `STREAM_IDLE_TIMEOUT_SECONDS` | `30` | 流式请求空闲超时 |
| `RUNTIME_ROOT` | 空（用 `.runtime/`） | 运行时数据目录 |
| `THREAD_CACHE_MAX` | `2000` | 内存 thread 缓存上限 |
| `THREAD_CACHE_TTL` | `7200` | thread 缓存过期秒数 |
| `LOG_LEVEL` | `INFO` | 日志级别 |
| `LANGFUSE_ENABLED` | `false` | 开启 Langfuse 追踪 |
| `LANGFUSE_PUBLIC_KEY` | 空 | Langfuse 公钥 |
| `LANGFUSE_SECRET_KEY` | 空 | Langfuse 私钥 |
| `LANGFUSE_HOST` | `https://cloud.langfuse.com` | Langfuse 服务地址 |

### 模型超时与重试（按模型类型）

每种模型类型支持独立的超时和重试配置：

| 前缀 | 默认超时 | 默认重试 |
|---|---|---|
| `INTENT_MODEL_*` | 8s | 0 |
| `GENERATION_MODEL_*` | 25s | 0 |
| `PLANNER_MODEL_*` | 12s | 0 |
| `EVAL_MODEL_*` | 8s | 0 |
| `RERANK_MODEL_*` | 8s | 0 |

格式：`{PREFIX}_TIMEOUT_SECONDS`、`{PREFIX}_MAX_RETRIES`

---

## 常见问题

### Milvus 启动失败

```bash
# 检查 Milvus 日志
docker compose logs milvus

# 常见原因：端口被占用
lsof -i :19530

# 清理重建
docker compose down -v   # 删除 volume（会丢失向量数据！）
docker compose up -d
```

### Backend 启动时报 "Missing required environment variables"

启动时会校验 LLM 所需密钥，以及当前 rerank provider 对应的密钥。
默认 `RERANK_PROVIDER=qwen` 时，需要 `QWEN_API_KEY` 或 `RERANK_API_KEY` 至少一个可用；如果切回 `RERANK_PROVIDER=jina`，则需要 `JINA_API_KEY`。

### 前端 502 / "Backend connection failed"

```bash
# 确认后端在跑
curl http://localhost:8008/health

# Docker 模式下检查容器网络
docker compose exec web curl http://backend:8008/health
```

### 向量检索返回空

```bash
# 检查 collection 是否有数据
curl -H "X-API-Key: $API_SHARED_KEY" http://localhost:8008/admin/collection/stats

# 如果 row_count 为 0，需要先导入数据
python -m script.ingest_all --dir ./data/raw/unstructured
```
