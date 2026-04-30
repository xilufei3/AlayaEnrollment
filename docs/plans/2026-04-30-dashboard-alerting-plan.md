# 数据看板与线上预警系统方案

日期：2026-04-30

## 背景

当前项目是招生问答系统，包含 FastAPI 后端、Next.js 前端、QQ 机器人、Milvus 向量库、SQL 查询、LLM/RAG 链路和 Langfuse trace。系统已经具备一部分观测基础：

- 后端入口：`src/api/chat_app.py`
- Prometheus 指标与结构化日志：`src/api/observability.py`
- 已有接口：`/health`、`/info`、`/metrics`
- 已有 admin 会话管理接口：`/admin/conversations`
- 已有知识库统计接口：`/admin/collection/stats`
- 已有 Langfuse 集成能力
- 前端已有 admin 会话页：`web/src/app/admin/conversations/page.tsx`
- 前端已有 `recharts`，可快速实现内部看板图表
- 已有 QQ bot，可作为告警通知渠道之一

本方案将“数据看板”和“线上预警系统”拆成两个互补部分：

- 数据看板：回答“系统现在运行得怎么样、哪里慢、用户在问什么、RAG/LLM 链路哪里耗时”。
- 线上预警系统：回答“什么时候算异常、谁收到通知、通知内容能否直接帮助定位 bug”。

## 总体目标

1. 研发和运维可以实时看到系统健康状态、错误率、延迟和核心链路指标。
2. 招生/运营人员可以看到用户、会话、高频问题、无答案问题和知识库状态。
3. 系统出现 bug、上游模型异常、向量库异常、SQL 异常或流式响应异常时，可以自动通知负责人。
4. 告警信息必须包含足够定位上下文，例如接口、错误码、耗时、日志入口、Grafana 链接、Langfuse trace 信息。
5. 不重复建设时间序列能力。系统指标使用 Prometheus/Grafana，业务运营数据使用后端 admin API 和 Next.js 页面。

## 推荐架构

```text
FastAPI backend
  ├─ /health
  ├─ /info
  ├─ /metrics
  ├─ structured JSON logs
  ├─ app/RAG/LLM metrics
  └─ admin dashboard APIs

Prometheus
  └─ scrape backend:/metrics

Grafana
  ├─ 系统总览 Dashboard
  ├─ RAG/LLM Dashboard
  ├─ 接口质量 Dashboard
  └─ 业务运营 Dashboard

Alertmanager
  ├─ Prometheus alert rules
  └─ webhook / 企业微信 / 飞书 / 钉钉 / QQ 通知

Loki + Promtail，可选
  └─ 收集 docker logs / JSON logs

Langfuse
  └─ 单次 LLM/RAG trace 排查

Sentry，可选
  └─ 捕获 Python/Next.js/QQ bot 异常堆栈
```

建议最终形成三个互补入口：

- 内部 admin 页面：给业务和维护人员看会话、用户、高频问题、无答案问题、知识库状态。
- Grafana：给研发和运维看请求量、错误率、P95/P99、RAG/LLM/SQL/检索/Embedding、容器状态和告警状态。
- Alertmanager：负责自动告警、分组、静默、恢复通知和通知路由。

## 数据看板功能范围

### 1. 系统健康总览

首页建议放在 `/admin/dashboard`，展示系统是否可用以及核心风险。

功能项：

- 当前服务状态：`backend`、`web`、`nginx`、`qq-bot`、`milvus`
- `/health` 状态：`runtime_ready`
- `/info` 信息：服务名称、版本、是否需要 API key
- 最近 5 分钟请求量
- 最近 5 分钟 4xx / 5xx 错误率
- HTTP P50 / P95 / P99 响应时间
- 当前是否存在告警
- 最近一次异常发生时间
- Milvus collection 行数
- 今日用户数、会话数、消息数

示例展示：

```text
服务状态：正常
5xx 错误率：0.8%
HTTP P95：3.2s
LLM 错误率：1.4%
检索错误率：0%
SQL 错误率：0%
Embedding 错误率：0%
今日活跃用户：128
今日会话：342
今日消息：1,927
知识库向量数：42,318
```

### 2. 请求与接口质量

用于判断 bug 是否集中在某个接口。

功能项：

- 各接口请求量
- 各接口 4xx / 5xx 数量
- 各接口 P95/P99 耗时
- 慢请求列表
- 429 限流次数
- SSE 流式接口中断次数
- 超时次数
- 按错误码统计异常：
  - `REQUEST_TIMEOUT`
  - `MODEL_UNAVAILABLE`
  - `VECTOR_STORE_ERROR`
  - `INTERNAL_ERROR`
  - `THREAD_BUSY`

当前已有指标：

- `http_requests_total{method,path_template,status}`
- `http_request_duration_seconds{method,path_template}`

建议新增指标：

```python
APP_ERRORS_TOTAL = Counter(
    "app_errors_total",
    "Application errors by code and path",
    ["code", "path_template"],
    registry=_REGISTRY,
)
```

### 3. RAG / LLM 链路看板

招生问答系统的核心风险集中在 RAG/LLM 链路。看板需要能判断问题出在分类、检索、SQL、rerank、generation、模型服务还是流式响应。

功能项：

- LLM 调用次数、成功率、失败率
- LLM P50 / P95 / P99 耗时
- 按 `model_kind` 分组的错误率和耗时
- 向量检索次数、成功率、P95 耗时
- SQL 查询次数、成功率、P95 耗时
- Embedding 请求次数、成功率、P95 耗时
- RAG 总耗时
- RAG 节点级耗时：
  - `intent_classify`
  - `search_planner`
  - `sql_plan_builder`
  - `sql_query`
  - `retrieval`
  - `rerank`
  - `merge_context`
  - `sufficiency_eval`
  - `generation`
- 无答案、低置信度、需要追问的比例
- Langfuse trace 入口

当前已有指标：

- `llm_requests_total`
- `llm_request_duration_seconds`
- `retrieval_requests_total`
- `retrieval_duration_seconds`
- `sql_query_total`
- `sql_query_duration_seconds`
- `embedding_requests_total`
- `embedding_duration_seconds`

建议新增节点级指标：

```python
GRAPH_NODE_RUNS_TOTAL = Counter(
    "graph_node_runs_total",
    "LangGraph node runs",
    ["node", "status"],
    registry=_REGISTRY,
)

GRAPH_NODE_DURATION = Histogram(
    "graph_node_duration_seconds",
    "LangGraph node duration",
    ["node"],
    buckets=(0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 20, 30, 60),
    registry=_REGISTRY,
)
```

插桩建议：

- 不建议在每个 LangGraph node 函数内部手动调用 `observe()` / `inc()`。
- 如果 RAG 链路使用 LangGraph `StateGraph`，应优先在 graph 执行层做统一插桩，例如统一的 node wrapper、装饰器或 callback。
- 统一包装层负责记录 `node`、`status`、duration，并在异常路径上保证失败指标一定被记录。
- 这样可以避免节点遗漏、异常分支漏记，以及后续新增 node 时维护成本不断上升。
- 文档和实现里需要明确“插桩点位在 LangGraph node 调度边界，而不是散落在业务 node 函数内部”。

### 4. 用户与会话运营看板

面向招生/运营人员，回答“用户是否在用、问了什么、哪里回答不上来”。

功能项：

- 今日活跃用户数
- 今日会话数
- 今日消息数
- 平均每会话消息数
- 用户来源渠道：
  - 网站
  - QQ 群
  - 微信公众号，如果启用
  - embed 页面
- 高频问题
- 无答案问题列表
- 触发工具、SQL、检索的问题列表
- 最近会话列表
- 按用户查看历史对话
- 删除异常会话

当前已有能力：

- `/admin/conversations`
- `/admin/conversations/{thread_id}`
- `/admin/conversations/{thread_id}` DELETE

建议新增接口：

```text
GET /admin/dashboard/summary
GET /admin/dashboard/questions/top?window=7d
GET /admin/dashboard/no-answer?window=7d
```

时间序列趋势不建议由业务 API 自己维护，优先使用 Prometheus/Grafana。

`GET /admin/dashboard/summary` 的实现约束：

- 该接口主要返回快照型聚合数据，例如 `total_users`、`total_threads`、`total_messages`、`updated_at`。
- 如果直接在 SQLite 上对大表执行 `COUNT(DISTINCT ...)`，数据量上来后会成为慢查询风险。
- 建议优先考虑两种方案：
  - 用定时任务或后台刷新任务把聚合结果预计算后写入统计表。
  - 把趋势类指标交给 Prometheus，例如使用 `conversation_messages_total` 这类 Counter，admin API 只返回当前快照。
- 如果 MVP 阶段先直接查 SQLite，也要明确后续需要替换为预聚合，避免 dashboard 页面把线上库查询拖慢。

### 5. 知识库与数据质量看板

招生问答依赖知识库、Milvus、Embedding 和 SQL 数据。知识库异常会直接表现为“系统 bug”。

功能项：

- Milvus collection row count
- 最近一次 ingest 时间
- 最近一次 ingest 是否成功
- 每个 category 的文档数量
- 文档 chunk 数量
- Embedding 失败数
- 检索命中率
- Top-K 检索为空比例
- SQL 表数据量
- SQL 查询失败的问题样例
- 知识库版本或数据更新时间

当前已有：

- `/admin/collection/stats`

建议新增 ingest 记录表：

```sql
CREATE TABLE ingest_runs (
  id TEXT PRIMARY KEY,
  filename TEXT NOT NULL,
  category TEXT,
  status TEXT NOT NULL,
  inserted_count INTEGER DEFAULT 0,
  error_message TEXT,
  created_at TEXT NOT NULL,
  finished_at TEXT
);
```

## 线上预警系统功能范围

### 告警分级

#### P0：系统不可用

触发条件：

- `/health` 连续 1 分钟失败
- backend 容器退出或重启频繁
- Milvus healthcheck 失败
- nginx 无法访问 backend
- 5xx 错误率持续高于 20%
- 所有 LLM 请求失败

通知方式：

- 立即通知主要值班群
- 需要 @负责人
- 恢复后发送恢复通知

#### P1：核心功能严重异常

触发条件：

- `/threads/{thread_id}/runs/stream` 或 `/runs/stream` 错误率高于 5%，持续 5 分钟
- `REQUEST_TIMEOUT` 明显升高
- `MODEL_UNAVAILABLE` 持续出现
- `VECTOR_STORE_ERROR` 持续出现
- SQL 查询失败率高于 5%
- Embedding 失败率高于 5%
- LLM P95 耗时超过 30 秒，持续 10 分钟
- 检索 P95 耗时超过 5 秒，持续 10 分钟

通知方式：

- 立即通知技术群
- 告警信息带接口、错误码、最近日志查询方式、Grafana 链接和 Langfuse 入口

#### P2：性能退化或局部异常

触发条件：

- HTTP P95 超过 10 秒
- LLM P95 超过 20 秒
- 429 限流数量异常升高
- SSE idle timeout 数量升高
- 会话创建成功但回答失败数量升高
- QQ bot 调 backend 失败
- 微信接口失败，如果启用

通知方式：

- 发送到监控群
- 聚合通知，避免刷屏

#### P3：数据质量异常

触发条件：

- Milvus collection row count 变成 0 或明显下降
- 最近一次 ingest 失败
- 检索空结果比例异常升高
- SQL 表为空或关键表数据量异常
- 高频“答不上来”问题增长
- 相同错误短时间内重复出现

通知方式：

- 发送到维护群
- 可每日汇总或低频通知

### 告警消息格式

告警通知必须能帮助快速定位，不能只发“系统异常”。

推荐格式：

```text
[P1] AlayaEnrollment 核心问答接口错误率过高

时间：2026-04-30 10:25 UTC
服务：backend
接口：POST /threads/{thread_id}/runs/stream
错误率：8.7% / 5m
5xx 数量：42
主要错误码：REQUEST_TIMEOUT
P95 耗时：34.2s

可能影响：用户无法稳定收到招生问答回复
排查入口：
- Grafana: http://...
- Logs: logger=alaya.api code=REQUEST_TIMEOUT
- Langfuse: trace_name=admission-chat
```

## 实现方案

### 第 1 步：补齐后端指标

在 `src/api/observability.py` 增加以下指标：

```text
app_errors_total{code,path_template}
stream_runs_total{status,timeout_kind}
active_stream_runs
graph_node_runs_total{node,status}
graph_node_duration_seconds{node}
conversation_messages_total{channel,role}
no_answer_total{channel}
ingest_runs_total{status}
```

用途：

- `app_errors_total`：错误码趋势和告警。
- `stream_runs_total`：SSE 中断、超时、成功率。
- `active_stream_runs`：当前活跃流式请求。
- `graph_node_*`：定位 RAG 哪个节点慢或失败。
- `conversation_messages_total`：使用量趋势。
- `no_answer_total`：知识库质量。
- `ingest_runs_total`：知识库更新质量。

注意：

- 不要把 `thread_id`、`session_id`、`device_id` 放进 Prometheus label。
- 这些高基数字段应该进入日志或 trace。
- `device_id` 写入日志时继续脱敏。
- 对合成探测流量要单独打标，例如 `request_source=synthetic` 写入日志或 trace，必要时在指标侧增加低基数来源维度，确保可以与真实用户流量区分。

### 第 2 步：统一错误记录

当前 `src/api/chat_app.py` 已经有 `_error_code()` 和 `_error_payload()`，可以继续沿用错误分类：

- `REQUEST_TIMEOUT`
- `MODEL_UNAVAILABLE`
- `VECTOR_STORE_ERROR`
- `INTERNAL_ERROR`

需要补充：

- 每次生成错误响应时记录 `app_errors_total`
- 流式接口的 `error` event 也记录指标
- 全局异常 handler 记录 `INTERNAL_ERROR`
- 日志中增加 `error_code`
- 日志中尽可能带上 `thread_id`、`session_id`、`trace_id`

推荐日志字段：

```json
{
  "ts": "2026-04-30T10:25:00",
  "level": "ERROR",
  "logger": "alaya.api",
  "event": "request_error",
  "path": "/threads/{thread_id}/runs/stream",
  "thread_id": "xxx",
  "device_id": "abcd1234***",
  "trace_id": "xxx",
  "error_code": "REQUEST_TIMEOUT",
  "duration_ms": 30120
}
```

### 第 3 步：增加监控基础设施

在 `docker-compose.yml` 中增加：

- `prometheus`
- `grafana`
- `alertmanager`
- 可选：`loki`
- 可选：`promtail`
- 可选：`cadvisor`
- 可选：`node-exporter`

Prometheus 配置示例：

```yaml
scrape_configs:
  - job_name: alaya-backend
    metrics_path: /metrics
    static_configs:
      - targets:
          - backend:8008
```

安全要求：

- 生产环境不要把 `/metrics` 公开暴露到公网。
- 优先只允许 Prometheus 在内网访问。
- 如必须经过 nginx，增加 IP allowlist 或独立 token。

### 第 4 步：Grafana Dashboard

至少建立 4 个 dashboard：

1. 系统总览
2. 接口质量
3. LLM/RAG 链路
4. 知识库与业务运营

常用 PromQL：

请求量：

```promql
sum(rate(http_requests_total[5m]))
```

5xx 错误率：

```promql
sum(rate(http_requests_total{status=~"5.."}[5m]))
/
sum(rate(http_requests_total[5m]))
```

HTTP P95：

```promql
histogram_quantile(
  0.95,
  sum(rate(http_request_duration_seconds_bucket[5m])) by (le, path_template, method)
)
```

LLM 调用与状态：

```promql
sum(rate(llm_requests_total[5m])) by (model_kind, status)
```

LLM P95：

```promql
histogram_quantile(
  0.95,
  sum(rate(llm_request_duration_seconds_bucket[5m])) by (le, model_kind)
)
```

检索请求：

```promql
sum(rate(retrieval_requests_total[5m])) by (mode, status)
```

检索 P95：

```promql
histogram_quantile(
  0.95,
  sum(rate(retrieval_duration_seconds_bucket[5m])) by (le, mode)
)
```

SQL 状态：

```promql
sum(rate(sql_query_total[5m])) by (status)
```

接口错误排行：

```promql
topk(
  10,
  sum(rate(http_requests_total{status=~"5.."}[5m])) by (path_template)
)
```

### 第 5 步：Prometheus 告警规则

基础规则示例：

```yaml
groups:
  - name: alaya-backend
    rules:
      - alert: BackendDown
        expr: up{job="alaya-backend"} == 0
        for: 1m
        labels:
          severity: P0
        annotations:
          summary: "Alaya backend is down"
          description: "Prometheus cannot scrape backend /metrics for 1 minute."

      - alert: HighHttp5xxRate
        expr: |
          sum(rate(http_requests_total{status=~"5.."}[5m]))
          /
          sum(rate(http_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: P1
        annotations:
          summary: "HTTP 5xx error rate is high"
          description: "5xx rate is above 5% for 5 minutes."

      - alert: HighHttpLatencyP95
        expr: |
          histogram_quantile(
            0.95,
            sum(rate(http_request_duration_seconds_bucket[5m])) by (le)
          ) > 10
        for: 10m
        labels:
          severity: P2
        annotations:
          summary: "HTTP P95 latency is high"
          description: "HTTP P95 latency is above 10s for 10 minutes."

      - alert: LLMErrorRateHigh
        expr: |
          sum(rate(llm_requests_total{status="error"}[5m]))
          /
          sum(rate(llm_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: P1
        annotations:
          summary: "LLM error rate is high"
          description: "LLM error rate is above 5% for 5 minutes."

      - alert: LLMLatencyHigh
        expr: |
          histogram_quantile(
            0.95,
            sum(rate(llm_request_duration_seconds_bucket[5m])) by (le)
          ) > 30
        for: 10m
        labels:
          severity: P1
        annotations:
          summary: "LLM P95 latency is high"
          description: "LLM P95 latency is above 30s for 10 minutes."

      - alert: RetrievalErrorRateHigh
        expr: |
          sum(rate(retrieval_requests_total{status="error"}[5m]))
          /
          sum(rate(retrieval_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: P1
        annotations:
          summary: "Vector retrieval error rate is high"
          description: "Retrieval error rate is above 5% for 5 minutes."

      - alert: SQLQueryErrorRateHigh
        expr: |
          sum(rate(sql_query_total{status="error"}[5m]))
          /
          sum(rate(sql_query_total[5m])) > 0.05
        for: 5m
        labels:
          severity: P1
        annotations:
          summary: "SQL query error rate is high"
          description: "SQL query error rate is above 5% for 5 minutes."

      - alert: EmbeddingErrorRateHigh
        expr: |
          sum(rate(embedding_requests_total{status="error"}[5m]))
          /
          sum(rate(embedding_requests_total[5m])) > 0.05
        for: 5m
        labels:
          severity: P2
        annotations:
          summary: "Embedding error rate is high"
          description: "Embedding error rate is above 5% for 5 minutes."
```

补充 `app_errors_total` 后可增加：

```yaml
- alert: InternalErrorSpike
  expr: sum(rate(app_errors_total{code="INTERNAL_ERROR"}[5m])) > 0.2
  for: 3m
  labels:
    severity: P1
  annotations:
    summary: "Internal errors are increasing"
    description: "INTERNAL_ERROR is occurring frequently."
```

### 第 6 步：告警通知接入

可选三种方式。

#### 方案 A：Alertmanager 直接发企业微信/飞书/钉钉

适合生产环境。

流程：

```text
Prometheus rule 触发
  -> Alertmanager
  -> webhook / 企业微信 / 飞书 / 钉钉
```

优点：

- 标准
- 稳定
- 支持告警分组
- 支持静默
- 支持恢复通知
- 不依赖 backend 自身可用性，适合承接 P0 告警

#### 方案 B：Alertmanager 发到本项目 webhook，再由项目发 QQ 机器人

适合继续使用 QQ 群作为主要通知渠道。

流程：

```text
Prometheus
  -> Alertmanager
  -> POST /admin/alerts/webhook
  -> qq_bot
  -> QQ 群
```

新增接口：

```text
POST /admin/alerts/webhook
```

功能：

- 校验 secret
- 接收 Alertmanager payload
- 格式化告警文本
- 调用 QQ bot 或内部消息发送模块
- 记录告警事件到 SQLite
- 支持恢复通知

注意：

- webhook 必须有独立 token
- 不要复用普通用户 API key
- 需要去重和限流，防止告警风暴
- 该方案额外引入了 backend `/admin/alerts/webhook` 这个故障点；如果 backend 自身不可达，P0 级别的 `backend down` 告警也可能无法送达
- 因此不建议把方案 B 作为唯一通知链路，尤其不能单独承接 P0 告警

推荐落地方式：

- P0 告警至少保留一条不依赖 backend 自身的通知路径，例如 Alertmanager 直连企业微信、飞书或钉钉。
- QQ bot 适合作为补充渠道，承接 P1/P2/P3 或作为辅助抄送。
- 如果同时保留方案 A 和方案 B，需要在 Alertmanager 路由中明确不同 severity 的发送策略。

#### 方案 C：接入 Sentry

适合捕获代码异常堆栈。

推荐组合：

```text
Prometheus/Alertmanager：发现系统异常
Sentry：定位具体异常堆栈
Langfuse：定位 LLM/RAG 单次链路
Grafana/Loki：看趋势和日志上下文
```

## Admin 看板页面实现建议

新增页面：

```text
web/src/app/admin/dashboard/page.tsx
```

页面结构：

```text
顶部：
  服务状态卡片、错误率、P95、今日会话、今日用户、知识库条数

中部：
  请求量趋势图
  错误率趋势图
  LLM 耗时趋势图
  RAG 节点耗时图

下部：
  最近错误列表
  慢请求列表
  无答案问题列表
  最近 ingest 记录
```

前端组件：

- 使用 `recharts` 的 `LineChart` 展示请求量、错误率、延迟趋势
- 使用 `BarChart` 展示接口错误排行、RAG 节点耗时排行
- 使用 `AreaChart` 展示用户活跃趋势
- 使用列表或表格展示最近错误、慢请求、无答案问题、ingest 记录

MVP 后端接口：

```text
GET /admin/dashboard/summary
```

查询建议：

- 页面首屏依赖这个接口时，应保证它是轻量快照查询，而不是实时扫消息表的大聚合。
- 趋势图优先直接读 Prometheus/Grafana，不要把趋势查询堆到 SQLite admin API 上。
- 如果返回 `total_users`、`total_threads`、`total_messages`，建议来自预聚合统计表或缓存快照。

返回示例：

```json
{
  "health": {
    "ok": true,
    "runtime_ready": true
  },
  "usage": {
    "total_users": 120,
    "total_threads": 350,
    "total_messages": 2100
  },
  "knowledge": {
    "collection_name": "alaya_enrollment",
    "row_count": 12345
  },
  "recent_errors": [],
  "updated_at": "2026-04-30T10:30:00Z"
}
```

## 合成探测

`/health` 正常不代表 RAG 问答链路正常。建议增加合成探测任务，定时调用真实问答链路。

隔离要求：

- 合成探测会实际触发 LLM 调用、向量检索和可能的 SQL 查询，必须明确它会消耗真实 token 和计算资源。
- 合成探测请求需要带明确标识，例如专用 header、固定 `device_id`、或 `request_source=synthetic` 之类的低基数字段。
- 指标、日志、trace 和统计接口都要能区分这类流量，避免把探测请求混入正常用户请求的错误率、耗时和使用量统计。
- 告警规则应明确哪些指标包含合成探测，哪些默认排除合成探测，避免既影响真实业务面板，又影响探测本身的告警判断。
- 如果后续做成本分析，还应单独统计 synthetic 流量的调用量和 token 消耗。

测试问题示例：

```text
南科大本科招生有哪些专业？
```

检查项：

- HTTP 是否成功
- SSE 是否正常返回并结束
- 是否返回非空答案
- 总耗时是否小于阈值
- 是否触发模型、检索、SQL 异常

触发规则：

- 连续失败 2 次：P1
- 单次耗时超过 60 秒：P2
- 返回空答案或明显错误：P2/P3

## 优先级与里程碑

### 第一阶段：MVP，1-2 天

目标：能看到系统状态，能收到核心 bug 通知。

任务：

1. 确认 `/metrics` 可被 Prometheus 抓取。
2. 在 `docker-compose.yml` 加入 Prometheus、Grafana、Alertmanager。
3. 增加基础告警：
   - backend down
   - 5xx 错误率高
   - HTTP P95 高
   - LLM 错误率高
   - LLM P95 高
   - retrieval/sql/embedding 错误率高
4. Grafana 建系统总览 dashboard。
5. Alertmanager 先接入一条不依赖 backend 的通知渠道，优先覆盖 P0。
6. 确保 `/metrics` 不暴露给公网。

### 第二阶段：定位效率提升，3-5 天

目标：收到告警后能快速知道哪条链路坏了。

任务：

1. 增加 `app_errors_total{code,path_template}`。
2. 为 LangGraph `StateGraph` 增加统一 node wrapper / callback，补齐 graph node 级别指标。
3. 增加 SSE timeout 指标。
4. 统一日志字段：
   - `trace_id`
   - `thread_id`
   - `session_id`
   - `error_code`
   - `path_template`
5. 接入 Loki/Promtail。
6. Grafana 中支持从告警跳转日志。
7. Langfuse trace 链接写入日志或 metadata。

### 第三阶段：业务看板完善，1-2 周

目标：招生/运营人员也能使用。

任务：

1. 新增 `/admin/dashboard` 页面。
2. 为 dashboard summary 引入预聚合统计表或缓存快照，避免直接在 SQLite 上做重聚合。
3. 增加用户、会话、消息趋势。
4. 趋势数据优先接入 Prometheus/Grafana，而不是继续扩张业务 API 查询。
5. 增加高频问题。
6. 增加无答案问题。
7. 增加知识库 ingest 记录。
8. 增加按渠道统计。
9. 增加最近异常会话列表。
10. 增加会话详情和 Langfuse trace 关联。

### 第四阶段：生产级稳定性

目标：减少告警噪音，支持值班流程。

任务：

1. 告警分级 P0/P1/P2/P3。
2. Alertmanager 分组、静默、恢复通知。
3. P0 告警配置双路径或主备路径，至少一条链路不依赖 backend 自身。
4. 告警 webhook 记录事件。
5. 重复告警合并。
6. 增加值班人配置。
7. 增加 Sentry。
8. 增加 release/version 维度。
9. 增加合成探测，并保证 synthetic 流量单独打标和可过滤。

## 最优先落地的告警

按当前系统形态，建议优先做这 10 个：

1. backend `/health` 失败
2. 5xx 错误率升高
3. `REQUEST_TIMEOUT` 升高
4. `MODEL_UNAVAILABLE` 升高
5. `VECTOR_STORE_ERROR` 升高
6. LLM P95 超过 30 秒
7. SSE idle timeout / max duration timeout 升高
8. Milvus collection row count 为 0
9. QQ bot 调 backend 失败
10. 合成问答失败

## 不建议的做法

- 不要只做 admin 页面但没有自动告警。
- 不要只看 `/health`，LLM/RAG 经常是服务活着但回答链路坏了。
- 不要用日志替代指标。错误率、P95、请求量应该用 Prometheus。
- 不要公开暴露 `/metrics`。
- 不要把用户问题全文、API key、`device_id` 放入 Prometheus label。
- 不要把 `thread_id`、`session_id` 放入 Prometheus label。
- 不要让群告警直接发送完整异常堆栈。群里发摘要和链接，详细堆栈去 Sentry/Loki/Grafana 看。

## 建议开发清单

如果进入实现，建议先拆成这些任务：

1. 增加 `infra/prometheus/prometheus.yml`
2. 增加 `infra/prometheus/alert-rules.yml`
3. 增加 `infra/alertmanager/alertmanager.yml`
4. 修改 `docker-compose.yml`，加入 Prometheus、Grafana、Alertmanager
5. 修改 `src/api/observability.py`，增加应用错误、SSE、Graph node 指标
6. 修改 `src/api/chat_app.py`，异常处理和 SSE timeout 分支记录错误指标
7. 在 LangGraph 执行层增加统一 node wrapper / callback，记录 node duration 和 node status
8. 为合成探测请求增加流量标识，并在指标/日志中支持过滤
9. 新增 `/admin/dashboard/summary`，优先读取预聚合统计表或缓存快照
10. 新增 `web/src/app/admin/dashboard/page.tsx`
11. 配置 6-8 条核心告警并打通通知闭环，P0 通知链路不依赖 backend webhook

## 验收标准

MVP 验收：

- Prometheus 可以成功 scrape backend `/metrics`
- Grafana 可以看到 HTTP 请求量、错误率、P95、LLM 请求、检索、SQL、Embedding 指标
- backend down 可以触发告警
- 5xx 错误率高可以触发告警
- LLM 错误率高可以触发告警
- 告警可以发到指定通知渠道
- `/metrics` 未暴露给公网

生产验收：

- P0/P1/P2/P3 告警分级明确
- 告警消息包含服务、接口、错误码、耗时、影响范围和排查链接
- 能从 Grafana 跳转到日志或 trace
- 能定位到具体 RAG 节点异常
- 能看到知识库 ingest 成功/失败记录
- 合成问答探测可以发现 RAG 主链路不可用
- 告警支持恢复通知和静默
