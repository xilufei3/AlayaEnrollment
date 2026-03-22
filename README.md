# AlayaEnrollment

南方科技大学本科招生咨询 AI 系统，包含：

- **FastAPI 后端** — LangGraph 对话编排 + Agentic RAG
- **Milvus 向量检索** — 混合检索（Dense + BM25 + RRF）
- **Next.js 前端** — BFF 代理架构
- **Nginx 反向代理** — 限流 + 安全头

## 快速开始

### 方式一：Docker 全栈（推荐）

```bash
cp .env.example .env          # 配置环境变量（至少填 QWEN_API_KEY 或 DEEPSEEK_API_KEY）
docker compose up --build -d  # 一键启动所有服务
```

启动后访问 `http://localhost`（Nginx → Web → Backend → Milvus）。

### 方式二：本地开发

```bash
# 1. 环境准备
pip install -r requirements.txt
cp .env.example .env

# 2. 启动后端（自动拉起 Milvus Docker）
python main.py

# 3. 启动前端（另开终端）
cd web && npm install && npm run dev
```

访问 `http://localhost:3000`。

后端参数：

| 参数 | 默认值 | 说明 |
|---|---|---|
| `--host` | `0.0.0.0` | 绑定地址 |
| `--port` | `8008` | 端口 |
| `--reload` | off | 开发热重载 |
| `--skip-infra` | off | 跳过 Docker（Milvus 已在跑时用） |

## 服务端口

| 服务 | 端口 | 说明 |
|---|---|---|
| Nginx | 80 | 生产入口（仅 Docker 全栈模式） |
| Web (Next.js) | 3000 | BFF 代理层 |
| Backend (FastAPI) | 8008 | API 服务 |
| Milvus | 19530 | 向量数据库 |
| Attu | 8000 | Milvus 管理 UI（仅开发模式） |
| MinIO Console | 9001 | 对象存储管理 |

## 数据导入

### 向量数据（知识库文档）

```bash
# 批量导入目录下所有文件（会清空重建 collection）
python -m script.ingest_all --dir ./data/raw/unstructured

# 单文件导入（追加，不清空）
python -m script.ingest_file --file ./data/raw/unstructured/本科专业.md --category major
```

支持的文件格式：`.md` `.txt` `.doc` `.docx` `.pdf` `.xlsx`

分类可选值：`school_info` `admissions` `major` `career` `campus`

运行中也可通过 API 热灌库（无需重启）：

```bash
curl -X POST -H "X-API-Key: $API_SHARED_KEY" \
  -F "file=@data/raw/unstructured/new_doc.md" \
  -F "category=admissions" \
  http://localhost:8008/admin/ingest
```

### SQL 结构化数据（录取分数）

```bash
# 建表 + 导入数据
python sql/demo_admission_scores.py --reset

# 校验表注册
python -m src.knowledge.manage validate-sql

# 查询测试
python -m src.knowledge.manage query-admission-scores --province 安徽 --year 2024
```

## 环境变量

完整列表见 [.env.example](.env.example)，关键变量：

| 变量 | 必填 | 说明 |
|---|---|---|
| `QWEN_API_KEY` | 是 | Qwen 模型密钥（启动时校验） |
| `JINA_API_KEY` | 是 | Jina Reranker 密钥（启动时校验） |
| `API_SHARED_KEY` | 推荐 | BFF → Backend 的共享密钥 |
| `MILVUS_URI` | 否 | 默认 `http://localhost:19530` |
| `AlayaData_URL` | 否 | Embedding 服务地址 |
| `LANGFUSE_ENABLED` | 否 | 设为 `true` 开启 Langfuse 追踪 |
| `CORS_ALLOWED_ORIGINS` | 否 | 空=禁用 CORS（BFF 架构下推荐） |
| `LOG_LEVEL` | 否 | 默认 `INFO` |

## API 端点

| 端点 | 说明 |
|---|---|
| `GET /health` | 健康检查（无需鉴权） |
| `GET /info` | 服务信息（无需鉴权） |
| `GET /metrics` | Prometheus 指标（无需鉴权） |
| `POST /threads` | 创建对话线程 |
| `GET /threads/{id}` | 获取线程信息 |
| `POST /threads/{id}/runs/stream` | 流式对话（SSE） |
| `POST /api/chat/stream` | 兼容聊天流式接口 |
| `GET /admin/collection/stats` | 向量库状态 |
| `POST /admin/ingest` | 热灌库（上传文件） |

除 `/health`、`/info`、`/metrics` 外，所有端点需 `X-API-Key` 请求头。

## 安全机制

- **API Key 鉴权** — `API_SHARED_KEY` 保护所有业务端点
- **CORS** — 默认禁用（BFF 架构不需要跨域）
- **Device ID 校验** — 字符白名单 + per-device 滑动窗口限流
- **Nginx 限流** — 流式端点 20 req/min per IP
- **错误脱敏** — 内部异常不暴露给客户端
- **输入校验** — Body 64KiB 上限 + metadata 4KiB 上限
- **Prompt 防注入** — 所有 system prompt 含防注入指令
- **安全响应头** — X-Frame-Options / X-Content-Type-Options / Referrer-Policy

## 可观测性

- **结构化日志** — JSON 格式 access log 输出到 stderr
- **Prometheus 指标** — HTTP 请求、LLM 调用、向量检索、SQL 查询、Embedding 的耗时和成功率
- **Langfuse** — 可选的 LLM 调用追踪（`LANGFUSE_ENABLED=true` 开启）

访问 `http://localhost:8008/metrics` 查看指标。

## 项目结构

```
├── docker-compose.yml              # 全栈 Docker 编排（生产）
├── main.py                         # 后端启动入口（开发）
├── requirements.txt                # Python 依赖
├── .env.example                    # 环境变量模板
│
├── src/
│   ├── api/                        # FastAPI 应用 + 可观测性
│   ├── graph/                      # LangGraph 对话编排
│   │   ├── node/                   # 图节点（意图分类、生成、闲聊等）
│   │   └── agentic_rag/            # RAG 子图（检索、重排、评估）
│   ├── knowledge/                  # 知识层（Milvus、SQLite、Embedding）
│   ├── runtime/                    # 运行时（线程管理、Checkpoint）
│   └── config/                     # 配置文件
│
├── web/                            # Next.js 前端
├── infra/
│   ├── docker/                     # Dockerfile + Milvus 开发编排
│   └── nginx/                      # Nginx 反向代理配置
├── script/                         # 数据导入脚本
├── sql/                            # SQL 建表 + 数据导入工具
├── tests/                          # 测试套件
└── data/                           # 数据目录（gitignored）
```

## 详细部署指南

见 [DEPLOY.md](DEPLOY.md)。
