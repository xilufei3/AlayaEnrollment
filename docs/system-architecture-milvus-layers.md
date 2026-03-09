# 系统架构与 Milvus 检索/插入层次

本文档描述当前系统的整体设计架构，以及 Milvus 向量库在**插入**与**检索**两条链路上的层次结构。

---

## 1. 系统整体架构概览

系统大致分为以下几块：

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              入口层 / 运行时                                  │
│  • FastAPI (src/api/chat_app.py)                                             │
│  • AdmissionGraphRuntime (src/runtime/graph_runtime.py)                       │
│  • 脚本: app/scripts/ingest_file.py, src/ingest/collection_uploader.py        │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
         ┌──────────────────────────────┼──────────────────────────────┐
         ▼                              ▼                              ▼
┌─────────────────────┐    ┌─────────────────────────┐    ┌─────────────────────────┐
│  对话 / 检索流水线    │    │  文件入库流水线 (ETL)    │    │  本地/批量入库           │
│  LangGraph 四步图    │    │  app/services           │    │  src/ingest             │
│  intent→retrieve→   │    │  IngestionService       │    │  collection_uploader    │
│  rerank→generate    │    │  + AlayaDataClient      │    │  直接使用 vector_store   │
└─────────────────────┘    └─────────────────────────┘    └─────────────────────────┘
         │                              │                              │
         └──────────────────────────────┼──────────────────────────────┘
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                    向量存储抽象 (packages/vector_store)                        │
│  • 接口: VectorStore (create_index, upsert, search, delete, stats, …)        │
│  • 实现: PyMilvusStore（封装 pymilvus.MilvusClient）                          │
│  • 工厂: create_store_from_env() → PyMilvusStore                             │
└─────────────────────────────────────────────────────────────────────────────┘
                                        │
                                        ▼
┌─────────────────────────────────────────────────────────────────────────────┐
│                          Milvus 集群 (pymilvus)                              │
└─────────────────────────────────────────────────────────────────────────────┘
```

- **对话/检索**：用户 query → 图运行时 → intent → 向量检索 → rerank → 生成；检索时用 `VectorStore.search`。
- **文件入库（ETL）**：文件 → AlayaData ETL → 切片/向量 → 通过 `app/services` 的 `MilvusStoreService` 写入；插入时用 `VectorStore.upsert`（及 `create_index`）。
- **本地/批量入库**：`collection_uploader` 或脚本直接使用 `create_store_from_env()` 得到的 store 做 `upsert`，不经过 ETL 服务。

---

## 2. Milvus 插入（Upsert）层次结构

插入链路上，谁创建 store、谁调 create_index/upsert 的层次如下。

### 2.1 层次总览（自下而上）

```
Layer 0:  pymilvus.MilvusClient
              ↑
Layer 1:  PyMilvusStore (packages/vector_store/milvus_store.py)
              │ 实现 VectorStore：create_index, upsert, search, delete, stats, drop_index
              │ 使用 collection_prefix（如 adm_）、vector_field（如 embedding）、id_field（如 id）
              ↑
Layer 2a: MilvusStoreService (app/services/milvus_store.py)     [仅用于 ETL 入库]
              │ ensure_index(index_name, dimension, metric)  → store.create_index / 兼容已存在
              │ upsert(index_name, items, batch_size)         → 分批 store.upsert
              ↑
Layer 3a: IngestionService (app/services/ingestion_service.py)
              │ 编排：上传文件 → 创建 ETL 任务 → 轮询 → 取结果 → 向量补全 → ensure_index → upsert
              │ 依赖：alaya_client, milvus_service (MilvusStoreService), embedder
              ↑
          入口: app/scripts/ingest_file.py 等
```

**另一条插入路径（不经过 app/services）：**

```
Layer 1:  PyMilvusStore (同上)
              ↑
Layer 2b: 直接使用 store（无 MilvusStoreService 包装）
              │ create_index(CreateIndexRequest) 或 依赖已有 collection
              │ upsert(UpsertRequest) 按批调用
              ↑
          入口: src/ingest/collection_uploader.py, packages/vector_store/milvus_demo.py
```

### 2.2 关键类型与调用

| 层次 | 组件 | 插入相关 API | 说明 |
|------|------|----------------|------|
| L1 | `PyMilvusStore` | `create_index(CreateIndexRequest)`、`upsert(UpsertRequest) -> UpsertResult` | 直接调 `MilvusClient.create_collection` / `upsert`，维护 `_meta_cache` |
| L2a | `MilvusStoreService` | `ensure_index(index_name, dimension, metric)`、`upsert(index_name, items, batch_size) -> int` | 封装“索引若存在则跳过”、按批 upsert，供 IngestionService 使用 |
| L2b | 无 | 直接 `store.create_index` / `store.upsert` | collection_uploader、demo 等 |

- **Request/Result**：来自 `packages/vector_store.models`（`CreateIndexRequest`, `UpsertRequest`, `UpsertResult`, `VectorItem`）。
- **创建方式**：所有插入路径最终都通过 `create_store_from_env(env_file)` 得到 `PyMilvusStore`；`MilvusStoreService` 在未传入 `store` 时内部同样调用 `create_store_from_env`。

---

## 3. Milvus 检索（Search）层次结构

检索链路上，从“用户 query 字符串”到“Milvus 返回相似向量”的层次如下。

### 3.1 层次总览（自下而上）

```
Layer 0:  pymilvus.MilvusClient
              ↑
Layer 1:  PyMilvusStore (packages/vector_store/milvus_store.py)
              │ search(SearchRequest) -> SearchResult
              │ SearchRequest: index, query_vector, top_k, filter_expr
              │ SearchResult: hits: list[SearchHit] (id, score, payload)
              ↑
Layer 2:  VectorStoreClientAdapter (src/node/vector_store_adapter.py)
              │ 适配“图节点”期望的接口：search(query=str, index=..., top_k=..., ...)
              │ 内部：query_vector = embed_query(query) → store.search(SearchRequest(...))
              │ 返回：{ "hits": [ { "id", "score", "payload" }, ... ] }
              ↑
Layer 3:  VectorRetrieveComponent (src/node/vector_retrieve.py)
              │ 依赖注入 client（即 VectorStoreClientAdapter）
              │ client.search(query=..., index=..., top_k=..., collection_id=...)
              │ 将 hits 转为 LangChain Document，写入 state["chunks"]
              ↑
Layer 4:  LangGraph 图 (src/graph.py)
              │ 节点 "retrieve" = create_vector_retrieve_node(client=vector_client, index=..., top_k=...)
              │ vector_client 由 create_graph(init_args) 构建：若提供 vector_store + embed_query，则
              │ vector_client = VectorStoreClientAdapter(vector_store, embed_query)
              ↑
Layer 5:  AdmissionGraphRuntime (src/runtime/graph_runtime.py)
              │ startup: _vector_store = create_store_from_env(cfg.env_file)
              │          _graph = create_graph({ "vector_store": _vector_store, "embed_query": ..., ... })
              │ 用户消息 → run/invoke → 图执行 → retrieve 节点调用 adapter.search
              ↑
          入口: API / 对话请求
```

### 3.2 关键类型与调用

| 层次 | 组件 | 检索相关 API | 说明 |
|------|------|----------------|------|
| L1 | `PyMilvusStore` | `search(SearchRequest) -> SearchResult` | 使用 `_resolve_meta(index)` 得到 collection，调 `MilvusClient.search`，归一化为 `SearchHit` |
| L2 | `VectorStoreClientAdapter` | `search(query, index, top_k, ...) -> { "hits": [...] }` | 文本 query → `embed_query(query)` → 构造 `SearchRequest` → `store.search` |
| L3 | `VectorRetrieveComponent` | 使用 `client.search(...)`，结果转 Document | 检索节点实现，不直接依赖 VectorStore 接口 |
| L4 | `create_graph` | 注入 `vector_client`（Adapter）到 retrieve 节点 | 图只依赖“能 search(query, index, top_k)”的 client |
| L5 | `AdmissionGraphRuntime` | 创建 `vector_store`（PyMilvusStore）与 `embed_query`，传入 create_graph | 运行时唯一创建 store 的地方，检索链路共用该 store |

- **Request/Result**：`SearchRequest`、`SearchResult`、`SearchHit` 定义在 `packages/vector_store.models`。
- **检索路径上只有一条 store 来源**：运行时 `create_store_from_env()` → 同一实例既用于构建 `VectorStoreClientAdapter`，也即底层 `PyMilvusStore`，因此**插入**（若通过同一进程/同一配置的 store）与**检索**使用的是同一套 Milvus 连接与 collection 命名（含 prefix）。

---

## 4. 两条链路对比小结

| 维度 | 插入（Upsert） | 检索（Search） |
|------|----------------|----------------|
| **底层实现** | `PyMilvusStore.upsert` | `PyMilvusStore.search` |
| **请求模型** | `UpsertRequest(index, items: [VectorItem])` | `SearchRequest(index, query_vector, top_k, filter_expr)` |
| **业务入口** | IngestionService（ETL） / collection_uploader / 脚本 | 对话图 retrieve 节点 |
| **中间层** | 可选：MilvusStoreService（批处理 + ensure_index） | VectorStoreClientAdapter（query→向量 + 接口适配） |
| **Store 创建** | create_store_from_env（在服务/脚本侧） | create_store_from_env（在 AdmissionGraphRuntime） |
| **是否同进程** | 入库与对话可为不同进程，通过同一 MILVUS_* 配置共享同一库 | 同一运行时内检索与插入可共用同一 store 实例 |

---

## 5. 设计要点

1. **统一抽象**：所有 Milvus 访问都经过 `packages/vector_store` 的 `VectorStore` 接口（当前实现为 `PyMilvusStore`），插入和检索使用同一套 `CreateIndexRequest`、`UpsertRequest`、`SearchRequest` 等模型。
2. **插入分层**：ETL 场景用 `MilvusStoreService` 做“确保索引 + 分批 upsert”；其它场景可直接用 store，避免重复封装。
3. **检索分层**：图节点不依赖 VectorStore 的具体类型，只依赖“按 query 字符串 + index + top_k 返回 hits”的 client；`VectorStoreClientAdapter` 负责把 `VectorStore.search(SearchRequest)` 适配成该接口，并接入 `embed_query`。
4. **配置与实例**：连接与集合命名由 `MilvusConfig.from_env` / `create_store_from_env` 统一从环境（或 env 文件）读取，插入与检索通过相同配置即可访问同一批 collection。

如需扩展为多租户、多库或读写分离，只需在“谁创建 store、传什么参数”的层次上扩展（例如不同 env、不同 prefix 或不同 store 实例），而不必改动 `PyMilvusStore` 的 upsert/search 实现本身。
