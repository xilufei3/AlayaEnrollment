# AlayaData -> Milvus 导入使用说明

本文档说明如何使用当前最小同步管道，把本地文件经 AlayaData 解析后写入 Milvus。

## 1. 组件说明

当前导入链路由以下模块组成：

- `app/services/alayadata_client.py`
  - 与 AlayaData 服务交互（upload/create_job/wait/get_result）
- `app/services/ingestion_service.py`
  - 解析 ETL 结果并转为统一 chunk
  - 优先复用 `embedding_vector`
  - 缺失时调用 embedding 接口补齐
  - 写入 Milvus
- `app/services/milvus_store.py`
  - 负责 Milvus 索引确保与批量 upsert
- `app/scripts/ingest_file.py`
  - 命令行入口

## 2. 前置条件

执行导入前，确认：

1. AlayaData 服务可访问（示例：`http://100.64.0.30:6000`）
2. Milvus 已启动并可连接
3. 本地 `.env` 已配置 Milvus 与 embedding 相关变量

推荐先做连通性检查：

```powershell
ping 100.64.0.30
Test-NetConnection 100.64.0.30 -Port 6000
```

## 3. 环境变量

至少需要以下配置（可写在 `.env`）：

### 3.1 Milvus

- `MILVUS_URI` (例如 `http://localhost:19530`)
- `MILVUS_TOKEN` (可空)
- `MILVUS_DB_NAME` (可空)
- `MILVUS_COLLECTION_PREFIX` (默认 `adm_`)
- `MILVUS_VECTOR_FIELD` (默认 `embedding`)
- `MILVUS_ID_FIELD` (默认 `id`)

### 3.2 Embedding（用于缺失向量时补算）

- `EMBEDDING_BASE_URL`（或 `OPENAI_BASE_URL` / `DEEPSEEK_BASE_URL` / `JINA_BASE_URL`）
- `EMBEDDING_MODEL`（或 `OPENAI_EMBEDDING_MODEL` / `JINA_EMBEDDING_MODEL` / `JINA_MODEL_NAME`）
- `EMBEDDING_API_KEY`（或 `OPENAI_API_KEY` / `DEEPSEEK_API_KEY` / `JINA_API_KEY`）

说明：
- 如果 ETL 每个切片都返回了 `embedding_vector`，则不会触发补算。
- 只要有切片缺失 `embedding_vector`，就会使用上述 embedding 配置补齐。

## 4. 执行导入

在仓库根目录执行：

```powershell
D:\miniconda3\python.exe -m app.scripts.ingest_file `
  --file "D:\AlayaEnrollment\data\本科专业.md" `
  --index "sustech_major_training" `
  --server "http://100.64.0.30:6000" `
  --env-file "D:\AlayaEnrollment\.env"
```

常用可选参数：

- `--dataset` / `--doc-id`
- `--chunk-size` / `--chunk-overlap`
- `--parser`（默认 `builtin`）
- `--no-ocr`
- `--batch-size`（Milvus 批量写入大小）
- `--timeout`（ETL HTTP 超时）
- `--max-wait`（任务轮询最大等待秒数）
- `--embedding-base-url` / `--embedding-model` / `--embedding-api-key`

## 5. 成功输出说明

脚本成功时会输出类似：

```text
status=succeeded_with_warnings job_id=job_xxx index=sustech_major_training chunks_total=10 chunks_ingested=9 upserted=9 etl_embeds=7 fallback_embeds=2
warnings=etl status partial_succeeded
```

字段含义：

- `status`
  - `succeeded`：无告警完成
  - `succeeded_with_warnings`：有部分告警，但可用数据已入库
- `etl_embeds`：直接复用 ETL 返回向量的 chunk 数
- `fallback_embeds`：通过 embedding 接口补算的 chunk 数
- `upserted`：实际写入 Milvus 的向量条数

## 6. 常见问题排查

### 6.1 `ConnectionRefusedError` / WinError 10061

表现：无法连接 `100.64.0.30:6000`。
处理：

1. 确认服务是否启动
2. 确认 IP/端口是否正确
3. 确认本机到目标地址网络策略未拦截

### 6.2 `missing embedding base url` 或 `missing embedding model`

表现：脚本启动后直接失败。
处理：在 `.env` 或命令行补充 embedding 配置。

### 6.3 `vector dimension mismatch`

表现：写入前维度校验失败。
处理：确认 ETL 返回向量与补算向量模型一致，避免同批混用不同维度模型。

## 7. 仅解析不入库（可选）

如果只想验证 ETL 解析效果，不做 Milvus 导入，可使用：

```powershell
$env:PYTHONIOENCODING='utf-8'; D:\miniconda3\python.exe D:\AlayaEnrollment\scripts\client_etl.py "D:\AlayaEnrollment\data\本科专业.md" --server http://100.64.0.30:6000 --output-dir "D:\AlayaEnrollment\output"
```
