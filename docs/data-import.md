# 数据导入指南

本文档说明如何将业务数据经 AlayaData ETL 解析后写入 Milvus，供对话检索使用。更细的组件说明、命令参数与故障排查见 [AlayaData → Milvus 导入使用说明](milvus-ingestion-guide.md)。

## 1. 流程概览

```
本地文件 → AlayaData 服务（上传 + ETL 任务）→ 切片/向量结果
    → IngestionService（标准化、embedding 补齐）→ MilvusStoreService
    → Milvus 向量库（按 index 写入）
```

- **AlayaData**：负责文件解析、切片、可选 OCR，并可返回 `embedding_vector`。
- **IngestionService**：优先复用 ETL 返回的向量，缺失时调用配置的 Embedding 接口补齐，再写入 Milvus。
- **Milvus**：按 `index`（对应 collection）存储向量，检索时由运行时按意图选择集合。

## 2. 前置条件

- AlayaData 服务可访问（如 `http://100.64.0.30:6000`）。
- Milvus 已启动并可连接（见 [部署指南 - 启动 Milvus](deployment.md#4-启动-milvus-docker-compose)）。
- 根目录 `.env` 已配置 Milvus 与 Embedding 相关变量（见下文）。

## 3. 环境变量

数据导入至少需要以下配置（可写在仓库根目录 `.env`）。

### 3.1 Milvus

| 变量 | 说明 | 示例 |
|------|------|------|
| `MILVUS_URI` | Milvus 地址 | `http://localhost:19530` |
| `MILVUS_TOKEN` | 认证（可选） | 空 |
| `MILVUS_DB_NAME` | 数据库名（可选） | 空 |

### 3.2 Embedding（用于 ETL 未返回向量时补齐）

| 变量 | 说明 |
|------|------|
| `EMBEDDING_BASE_URL` 或 `OPENAI_BASE_URL` / `DEEPSEEK_BASE_URL` / `JINA_BASE_URL` | Embedding API 地址 |
| `EMBEDDING_MODEL` 或对应 `*_EMBEDDING_MODEL` / `JINA_MODEL_NAME` | 模型名 |
| `EMBEDDING_API_KEY` 或对应 `*_API_KEY` | API Key |

若 ETL 结果中每个切片都带 `embedding_vector`，则不会调用上述 Embedding；只要有切片缺失向量，就会用当前配置补齐。

### 3.3 AlayaData

| 变量 | 说明 | 示例 |
|------|------|------|
| `AlayaData_URL` | AlayaData 服务地址 | `http://100.64.0.30:6000` |

## 4. 执行导入

在仓库根目录执行 CLI（具体模块路径以仓库为准，以下为文档约定）：

```powershell
python -m app.scripts.ingest_file `
  --file "D:\AlayaEnrollment\data\本科专业.md" `
  --index "sustech_major_training" `
  --server "http://100.64.0.30:6000" `
  --env-file "D:\AlayaEnrollment\.env"
```

常用参数：

- `--file`：本地文件路径
- `--index`：Milvus 集合/索引名（需与检索侧使用的集合名一致，参见 `src/config.py` 中 `INTENT_COLLECTION_MAP`）
- `--server`：AlayaData 服务 URL
- `--env-file`：环境变量文件路径
- `--dataset` / `--doc-id`：可选数据集/文档标识
- `--chunk-size` / `--chunk-overlap`：切片参数
- `--parser`：解析器（默认 `builtin`）
- `--no-ocr`：禁用 OCR
- `--batch-size`：Milvus 批量写入大小
- `--timeout` / `--max-wait`：ETL 超时与轮询等待
- `--embedding-base-url` / `--embedding-model` / `--embedding-api-key`：覆盖 Embedding 配置

**注意**：`--index` 应与检索侧使用的集合名一致（参见 `src/config.py` 中 `INTENT_COLLECTION_MAP`），例如专业与培养对应 `majors_and_training`，前缀由配置决定。

## 5. 成功输出说明

成功时终端会输出类似：

```text
status=succeeded_with_warnings job_id=job_xxx index=sustech_major_training chunks_total=10 chunks_ingested=9 upserted=9 etl_embeds=7 fallback_embeds=2
warnings=etl status partial_succeeded
```

- **status**：`succeeded` 或 `succeeded_with_warnings`（部分告警但已入库）。
- **etl_embeds**：直接使用 ETL 返回向量的 chunk 数。
- **fallback_embeds**：通过 Embedding 接口补算的 chunk 数。
- **upserted**：实际写入 Milvus 的向量条数。

## 6. 仅解析不入库（可选）

若只想验证 ETL 解析结果而不写 Milvus，可使用仓库内提供的仅解析脚本（若存在），或参考 [milvus-ingestion-guide - 仅解析不入库](milvus-ingestion-guide.md#7-仅解析不入库可选) 中的命令。

## 7. 常见问题排查

| 现象 | 可能原因 | 处理 |
|------|----------|------|
| `ConnectionRefusedError` / 无法连接 AlayaData | 服务未启动或网络/防火墙 | 确认 AlayaData 地址与端口，检查本机到目标网络 |
| `missing embedding base url` / `missing embedding model` | 未配置 Embedding | 在 `.env` 或命令行补充对应变量 |
| `vector dimension mismatch` | 向量维度不一致 | 保证 ETL 与补算使用同一 embedding 模型，同批不混用不同维度 |
| 检索无结果 | 集合名与配置不符 | 核对 `INTENT_COLLECTION_MAP` 与 `--index` 使用的集合名是否一致 |

更多细节与组件说明见 [AlayaData → Milvus 导入使用说明](milvus-ingestion-guide.md) 与 [系统架构与 Milvus 检索/插入层次](system-architecture-milvus-layers.md)。
