# 部署指南

本文档说明如何从零部署 AlayaEnrollment 系统：Milvus、后端 API 与前端应用。

## 1. 环境要求

- **Python**：3.11+（推荐 3.13）
- **Node.js / pnpm**：用于前端（Next.js）
- **Docker / Docker Compose**：用于运行 Milvus 及 Attu
- **AlayaData 服务**（可选）：用于文件 ETL 与向量导入，需可访问的 URL（如 `http://100.64.0.30:6000`）

## 2. 仓库与依赖

```powershell
cd D:\AlayaEnrollment
# 后端依赖（若使用 requirements.txt）
pip install -r requirements.txt
# 或按需安装：uvicorn, fastapi, pymilvus 等
```

## 3. 环境变量

项目使用仓库根目录的 `.env`，后端与前端共用。

**首次部署**：复制模板并按需修改。

```powershell
cd D:\AlayaEnrollment
Copy-Item .env.example .env
# 编辑 .env，至少配置 MILVUS_URI、前端 API 地址、模型 Key 等
```

主要配置项见 [使用指南 - 环境变量](usage.md#环境变量)，数据导入相关见 [数据导入 - 环境变量](data-import.md#环境变量)。

## 4. 启动 Milvus（Docker Compose）

在 `infra/docker` 下使用 Compose 启动 Milvus 单机及 Attu 控制台：

```powershell
cd D:\AlayaEnrollment\infra\docker
docker compose -f milvus-compose.yml up -d
```

- **Milvus**：`localhost:19530`
- **Attu**：`http://localhost:8000`（可选，用于查看集合与数据）

确认 Milvus 可连：

```powershell
# 若已配置 MILVUS_URI=http://localhost:19530，后端 /health 可间接验证
curl http://localhost:19530
```

## 5. 启动后端 API

在仓库根目录启动 FastAPI 服务：

```powershell
cd D:\AlayaEnrollment
python -m uvicorn src.api.chat_app:app --reload --host 0.0.0.0 --port 8008
```

- 默认端口：**8008**
- 健康检查：`GET http://localhost:8008/health`
- 若启动失败，检查 `.env` 中的 `MILVUS_URI` 及 Milvus 是否已启动。

## 6. 启动前端

在前端工作区安装依赖并启动开发服务：

```powershell
cd D:\AlayaEnrollment\apps\agent-chat-app
pnpm install
pnpm dev
```

仅启动 web 应用（pnpm）：

```powershell
cd D:\AlayaEnrollment\apps\agent-chat-app
pnpm --filter web dev
```

或进入 web 子应用用 npm：

```powershell
cd D:\AlayaEnrollment\apps\agent-chat-app\apps\web
npm install
npm run dev
```

前端会使用 `.env` 中的 `NEXT_PUBLIC_API_URL`（默认 `http://localhost:8008`）请求后端。

## 7. 部署检查清单

- [ ] `.env` 已从 `.env.example` 复制并填写必要项
- [ ] Milvus 已通过 `docker compose` 启动且端口 19530 可访问
- [ ] 后端 `GET /health` 返回 `ok: true`，无 `startup_error`
- [ ] 前端可打开并成功请求后端（如发起一次对话）

## 8. 生产部署注意

- 将 `--reload` 去掉，使用多 worker 时注意与 LangGraph 运行时的兼容性。
- 使用反向代理（如 Nginx）时，为 SSE 流式接口关闭缓冲（如 `X-Accel-Buffering: no`）。
- `MILVUS_URI`、API Key 等敏感信息不要提交到仓库，使用环境或密钥管理注入。
