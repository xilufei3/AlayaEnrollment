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

## 服务器部署

适用于单机部署场景，默认后端 `8008`、前端 `3000`。

### 环境变量拆分

- `.env`（服务器上）包含私密变量：`API_SHARED_KEY`、`API_RATE_LIMIT_PER_MINUTE`、各大模型 Key、Milvus/Langfuse 配置等；该文件只给后端读取。
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

### 2. 启动后端

前台启动：

```bash
python main.py --host 0.0.0.0 --port 8008
```

后台启动：

```bash
mkdir -p .runtime
nohup python main.py --host 0.0.0.0 --port 8008 > .runtime/backend.log 2>&1 &
```

- 如果需要关闭自动拉起 Milvus，可提前在服务器上运行 `docker compose -f infra/docker/milvus-compose.yml up -d`，再在后端命令追加 `--skip-infra`。
- `API_SHARED_KEY` 会被 FastAPI 中间件校验，请在反向代理（如 Nginx）中注入相同的 `X-Api-Key` 头，示例：

```
location /api/ {
  proxy_pass http://127.0.0.1:8008;
  proxy_set_header X-Api-Key your-shared-key;
  proxy_buffering off;
  proxy_read_timeout 600s;
}
```

### 3. 启动前端

```bash
cd web
npm install
npm run build
mkdir -p ../.runtime
nohup npm run start -- --hostname 0.0.0.0 --port 3000 > ../.runtime/frontend.log 2>&1 &
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

- 设置 `API_SHARED_KEY` 后，所有除 `/health`、`/info` 以外的接口都需要 `X-Api-Key` 请求头，适合单服务器场景配合 Nginx 注入。
- `API_RATE_LIMIT_PER_MINUTE`（默认 `120`）启用滑动窗口限流，对流式接口 `/api/chat/stream`、`/runs/stream`、`/threads/{id}/runs/stream` 生效。若需关闭，将其置空或设为 `0`。
- 当前限流为进程内内存实现，多实例部署需改用 Redis/网关方案。

## 推荐顺序

```bash
cp .env.example .env
python main.py
python -m script.ingest_all --dir ./data/raw/unstructured
python -m script.demo_vector_search --query "本科专业" --top-k 3
```
