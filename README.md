# AlayaEnrollment

本仓库是本地 Alaya Agent 的单仓项目，主要包含：
- Python 后端运行时与聊天 API
- Next.js 前端聊天界面
- 向量检索包与 Milvus 基础设施配置

## 目录结构

```text
AlayaEnrollment/
  apps/
    agent-chat-app/         # 前端工作区（web + agents）
  infra/
    docker/
      milvus-compose.yml
  packages/
    vector_store/           # Python 向量存储包
  src/
    api/chat_app.py         # FastAPI 入口
    runtime/graph_runtime.py
  .env                      # 项目统一环境变量（本地）
  .env.example              # 环境变量模板
```

## 环境变量

本项目统一使用仓库根目录环境文件：
- `D:\AlayaEnrollment\.env`

模板文件：
- `D:\AlayaEnrollment\.env.example`

首次可先复制模板：

```powershell
cd D:\AlayaEnrollment
Copy-Item .env.example .env
```

## 启动后端

```powershell
cd D:\AlayaEnrollment
python -m uvicorn src.api.chat_app:app --reload --host 0.0.0.0 --port 8008
```

健康检查：

```powershell
curl http://localhost:8008/health
```

## 启动前端

在前端工作区安装并启动：

```powershell
cd D:\AlayaEnrollment\apps\agent-chat-app
pnpm install
pnpm dev
```

仅启动 web（pnpm）：

```powershell
cd D:\AlayaEnrollment\apps\agent-chat-app
pnpm --filter web dev
```

仅启动 web（npm）：

```powershell
cd D:\AlayaEnrollment\apps\agent-chat-app\apps\web
npm install
npm run dev
```

## 说明

- 根目录 `.env` 同时用于后端运行时和前端默认配置。
- `AlayaFlow/` 目录当前不纳入本仓库版本管理（已忽略）。

## Additional Docs

完整文档请查看 **[docs/README.md](docs/README.md)**，包括：

- [部署指南](docs/deployment.md) — 环境、Milvus、后端与前端部署
- [使用指南](docs/usage.md) — 聊天 API、前端使用、环境变量
- [数据导入](docs/data-import.md) — AlayaData → Milvus 导入流程与 CLI
- [AlayaData → Milvus 导入说明](docs/milvus-ingestion-guide.md) — 详细组件与故障排查
- [系统架构与 Milvus 层次](docs/system-architecture-milvus-layers.md) — 插入/检索链路设计
