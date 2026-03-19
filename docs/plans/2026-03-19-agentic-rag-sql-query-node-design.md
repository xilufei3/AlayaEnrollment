# Agentic RAG SQL Query Node Design

## Goal

在不改动顶层工作流骨架的前提下，为 `admission_policy` 类问题增加一条结构化 SQL 查询路径，并与现有向量检索路径一起进入生成节点汇总答案。

目标效果：

- 顶层图仍然保持 `intent_classify -> agentic_rag -> generate`
- `agentic_rag` 子图同时跑向量检索和 SQL 查询
- 两路结果在评估前合并
- 生成节点既能利用文本证据，也能利用结构化结果

## Why This Design

当前系统已经具备两类能力：

- 向量检索能力，由 `agentic_rag` 子图驱动
- 手写 SQL 查询能力，由 `src/knowledge/sql_queries.py` 提供

如果把 SQL 查询放到顶层图里，顶层会新增一层额外的路由与合并逻辑，而现有的“补槽位、检索充分性评估、生成”仍然主要发生在 `agentic_rag` 子图中，职责会被拆散。

更合适的做法是把 SQL 查询视为子图内的另一种 retrieval source。这样：

- 顶层编排保持稳定
- 子图统一负责证据收集与汇总
- 后续如果再接更多结构化数据表，也能延续同样模式

## High-Level Architecture

顶层图保持不变：

```text
START
  -> intent_classify
  -> agentic_rag
  -> generate
  -> END
```

`agentic_rag` 子图改为并行双路检索：

```text
START
  -> search_planner
  -> retrieval
  -> sql_query
  -> merge_context
  -> rerank
  -> eval
  -> END / retry
```

更准确地说：

- `search_planner` 同时向 `retrieval` 和 `sql_query` 发出计划
- `retrieval` 和 `sql_query` 都执行
- `merge_context` 在评估前合并两路结果
- `rerank` 和 `eval` 继续基于合并后的 `chunks` 工作

## Core Decisions

### 1. SQL 查询只在 `admission_policy` 意图下生效

`sql_query_node` 只对 `intent == "admission_policy"` 的情况实际执行 SQL。其他意图下节点返回空结果，不影响现有流程。

这样做的原因：

- 当前表 `admission_scores` 明显属于政策/录取数据方向
- 避免为校园生活、专业培养等问题无意义地引入结构化噪声

### 2. SQL 是否执行由 planner 决定

不能把“槽位为空”直接等同于“不查 SQL”。

Planner 新增 `sql_plan`，至少包含：

- `enabled: bool`
- `province: str | None`
- `year: str | None`
- `limit: int`
- `reason: str`

语义是：

- `enabled=True` 表示当前问题需要结构化查询
- `province/year` 是 planner 可选提供的覆盖值
- `limit` 控制 SQL 返回条数

### 3. Planner 未提供的过滤值，回退到 slots

`sql_query_node` 执行前解析参数：

```python
resolved_province = sql_plan.province or slots.province or None
resolved_year = sql_plan.year or slots.year or None
```

也就是说：

- planner 给了值，优先用 planner 的值
- planner 没给，用意图识别节点已有的 `slots`
- 两边都没给，也允许执行无过滤 SQL 查询，但仍受 `limit` 约束

这样 planner 的职责更轻，也更容错。

### 4. SQL 查询函数继续使用手写 SQL

不引入动态 NL2SQL。

`src/knowledge/sql_queries.py` 继续作为唯一 SQL 执行入口，结构化查询节点只负责：

- 解释 planner/slots
- 调用手写查询函数
- 把结果转成下游可消费的状态

### 5. 合并节点只拼接，不去重

你已经明确要求不去重，因此 `merge_context` 的职责非常简单：

- 收集 `structured_chunks`
- 收集 `vector_chunks`
- 直接拼接为最终 `chunks`

推荐顺序：

```python
chunks = structured_chunks + vector_chunks
```

原因：

- 结构化结果通常是更高密度的事实证据
- 后续还有 `rerank`，最终排序会再次调整

### 6. 合并发生在评估前

`merge_context` 放在 `eval` 之前，而不是生成前。

这意味着：

- `eval` 判断信息是否充分时，会同时看到 SQL 和 RAG 的证据
- 如果信息仍不足，可以重试 planner，重新调整向量检索与 SQL 查询策略

## State Changes

### `RAGState`

现有 `RAGState` 已经有：

- `vector_chunks`
- `structured_results`
- `chunks`

建议新增：

- `sql_plan: SQLPlan`
- `structured_chunks: list[Document]`

并调整职责：

- `retrieval` 只写 `vector_chunks`
- `sql_query` 只写 `structured_results` 和 `structured_chunks`
- `merge_context` 统一写 `chunks`

### `WorkflowState`

建议在顶层 `WorkflowState` 新增：

- `structured_results: list[dict[str, Any]]`

这样 `generate` 节点既能读合并后的 `chunks`，也能在需要时直接读取 SQL 原始结果。

## Node Responsibilities

### `search_planner`

现有 planner 只生成向量检索计划。需要扩展为同时生成：

- `search_plan`
- `sql_plan`

Planner 不直接执行 SQL，只负责决策：

- 当前问题是否需要 SQL
- 如果需要，是否覆盖 `province/year`
- SQL 结果数量上限是多少

默认建议：

- `sql_plan.limit = 6`

### `retrieval`

现有行为：

- 执行向量检索
- 返回 `vector_chunks`
- 直接把 `chunks` 写成向量结果

新行为：

- 仍然执行向量检索
- 只返回 `vector_chunks`
- 不再直接写 `chunks`

### `sql_query_node`

新节点职责：

1. 检查 `intent`
2. 读取 `sql_plan`
3. 解析最终查询参数：
   - 优先 planner
   - 其次 slots
4. 调用 `query_admission_scores(...)`
5. 返回：
   - `structured_results`
   - `structured_chunks`

其中 `structured_chunks` 是把结构化结果转成 `Document`，供后续 `merge_context / rerank / generate` 使用。

### `merge_context`

新节点职责：

- 读取 `structured_chunks`
- 读取 `vector_chunks`
- 直接拼接为 `chunks`

不做：

- 去重
- 摘要压缩
- 评分

### `rerank`

保持原职责不变，继续只基于 `chunks` 工作。

### `eval`

保持原职责不变，但它评估的输入将变成“SQL + RAG 合并后的上下文”。

### `generate`

第一版可以保持“以 `chunks` 为主输入”的策略。

但建议增加一个轻量增强：

- 当 `structured_results` 非空时，在 prompt 中附加一段简短的结构化结果摘要

这不是必须项，但能让生成节点更稳定地区分：

- 文本检索证据
- 表格型结构化证据

## SQL Query Behavior

结构化查询节点最终调用：

`src/knowledge/sql_queries.py::query_admission_scores(...)`

当前查询函数已经满足：

- `province` 可空
- `year` 可空
- 仍然返回全列
- `province` 支持双向 `LIKE`
- `limit` 受控

这足够支撑第一版节点接入。

## Failure Handling

### SQL 查询失败

`sql_query_node` 应捕获异常并返回空结果，而不是让整个子图失败。

推荐行为：

- 记录 warning/error 日志
- 返回：
  - `structured_results = []`
  - `structured_chunks = []`

这样向量检索仍可继续支撑回答。

### Planner 开启 SQL 但没有有效过滤值

如果 `sql_plan.enabled=True` 且 planner/slots 都没有 `province/year`：

- 允许执行“无过滤 + limit”的 SQL 查询

因为用户有可能需要全局录取信息，而不是某个特定省份/年份。

### SQL 查询结果为空

如果执行成功但结果为空：

- 返回空 `structured_results`
- 不阻塞向量检索结果

生成节点会继续依据已有 `chunks` 作答。

## Files To Change

核心会涉及这些文件：

- `src/graph/agentic_rag/schemas.py`
- `src/graph/state.py`
- `src/graph/agentic_rag/node/search_planner.py`
- `src/graph/agentic_rag/node/retrieval.py`
- `src/graph/agentic_rag/graph.py`
- `src/graph/node/generation.py`
- `src/knowledge/sql_queries.py`

新增文件建议：

- `src/graph/agentic_rag/node/sql_query.py`
- `src/graph/agentic_rag/node/merge_context.py`

## Non-Goals

这一版设计明确不做：

- 通用 NL2SQL
- 多表自动路由
- SQL 结果去重
- SQL 和向量结果的复杂融合打分
- 结构化结果的专门 UI 渲染

## Summary

最终目标是把 SQL 查询能力自然嵌入 `agentic_rag` 子图，使其成为与向量检索并行的一条证据来源。

这条设计路线的优点是：

- 顶层图基本不动
- 子图职责更完整
- 保持现有 RAG 主链稳定
- 可逐步扩展到更多结构化表
