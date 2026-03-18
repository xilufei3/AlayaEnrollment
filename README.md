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

## 推荐顺序

```bash
cp .env.example .env
python main.py
python -m script.ingest_all --dir ./data/raw/unstructured
python -m script.demo_vector_search --query "本科专业" --top-k 3
```
