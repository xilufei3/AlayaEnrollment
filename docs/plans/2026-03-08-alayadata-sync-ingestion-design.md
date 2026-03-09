# AlayaData 最小同步入库设计

## 1. 目标
- 构建一个最小同步管道：`文件/路径 -> AlayaData ETL -> chunks/fulltext/embedding_vector -> Milvus`。
- 优先复用 ETL 返回的 `embedding_vector`，缺失时再调用 embedding 接口补齐。
- 当前阶段不引入异步任务系统、队列、数据库任务表。

## 2. 非目标
- 不实现任务调度/重试队列/分布式 worker。
- 不暴露完整业务 API 编排层（仅保留薄调用入口）。
- 不实现多租户鉴权和复杂审计链路。

## 3. 目录与模块边界
- `app/services/alayadata_client.py`
  - 只负责与 AlayaData 服务交互：`upload/create_job/wait_for_job/get_result`。
  - 只做 HTTP、超时、重试、响应映射，不做业务规则。
- `app/services/ingestion_service.py`
  - 负责 ETL 结果标准化、embedding 复用/补齐、向量写入编排。
  - 输出统一入库结果 DTO。
- `app/services/milvus_store.py`
  - 负责 Milvus 索引确保、分批 upsert。
- `app/services/types.py`
  - 放置所有 DTO（dataclass），禁止对外返回裸 dict。
- `app/scripts/ingest_file.py`
  - CLI 薄入口：参数解析 + 调用 service + 打印结果。

## 4. 数据契约（DTO）
- 统一原则：
  - 所有对外方法返回 DTO，不返回裸 dict。
  - raw json 仅允许存在于 client 内部，出 client 立即映射。
- 关键 DTO：
  - `UploadResultDTO`、`CreateJobResultDTO`、`JobStatusDTO`、`ETLResultDTO`。
  - `SliceDTO`：统一 `content_md` 为非空兜底文本（来源顺序：`content_md -> content -> text -> chunk_text -> page_content`）。
  - `IngestSummaryDTO`：`status`、`chunks_total/chunks_ingested/chunks_skipped`、`used_etl_embeddings/fallback_embedded`、`upserted`、`warnings`。

## 5. 执行流程
1. 输入文件路径与入库参数。
2. `AlayaDataClient.upload_file` 上传文件，获得 `upload_ref`。
3. `AlayaDataClient.create_job` 创建 ETL 任务。
4. `AlayaDataClient.wait_for_job` 轮询到终态。
5. `AlayaDataClient.get_job_result` 获取结果并转 `ETLResultDTO`。
6. `IngestionService` 提取标准化 chunk：
   - 先取 `SliceDTO.content_md`；
   - 若切片无文本且 `fulltext` 可用，则回退切分。
7. 向量准备：
   - 优先用 `slice.embedding_vector`；
   - 缺失时调用 embedding client 补齐。
8. `MilvusStoreService.ensure_index` + `upsert` 写入向量。
9. 返回 `IngestSummaryDTO`。

## 6. 成功/失败语义
- 成功：
  - `succeeded`：全部有效 chunk 完成入库且无告警。
  - `succeeded_with_warnings`：`partial_succeeded` 或存在跳过项，但有有效 chunk 成功入库。
- 失败：
  - ETL 终态为 `failed/canceled`；
  - 无有效文本可入库；
  - embedding 补齐失败且无法继续；
  - Milvus upsert 失败。

## 7. 错误处理策略
- 分阶段错误标识：`etl_upload` / `etl_create_job` / `etl_wait` / `etl_result` / `embed` / `upsert`。
- 维度校验：同一批次向量维度必须一致，不一致立即失败。
- `partial_succeeded` 默认继续处理可用切片，并写入 warnings。

## 8. 测试策略
- 单元测试优先（TDD）：
  - DTO 映射与字段兜底规则。
  - `embedding_vector` 复用优先级。
  - embedding 缺失补齐逻辑。
  - Milvus 批量 upsert 与统计计数。
  - `partial_succeeded` 下成功并附 warning 的返回语义。
- 使用 fake client/fake store，不依赖线上服务。

## 9. 交付标准
- 可用 CLI 一条命令完成同步入库。
- 返回结构稳定、可序列化、可直接被上层系统消费。
- 无裸 dict 外泄，接口契约可静态检查与 IDE 补全。
