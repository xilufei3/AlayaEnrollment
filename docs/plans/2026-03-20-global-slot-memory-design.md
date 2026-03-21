# Global Slot Memory Design

## Goal

在保持当前 graph 主流程不拆分的前提下，把 `slots` 设计成全局固定的用户画像记忆，只保留 `province` 和 `year` 两个槽位，并让后续回答与追问更多由当前用户 query 的语义驱动，而不是被历史槽位机械绑定。

## Final Decisions

### 1. Global slots are fixed

`WorkflowState["slots"]` 全局固定只允许两个 key:

- `province`
- `year`

不再把任意领域信息写入 `slots`。即使 LLM 返回了其他 key，也要在代码里过滤掉。

### 2. Slot extraction stays inside intent classification

`intent_classify` 继续使用一次 LLM 调用同时产出:

- `intent`
- `reason`
- `confidence`
- `slots`
- 当前 query 对答案是否强依赖某些槽位的判断

这样可以保持现有 graph 结构稳定，不需要再单独加一个 slot-extract node。

### 3. Slot values should be the latest user-provided values

LLM 提取时仍然可以参考最近历史消息，但需要遵循以下规则:

- 当前 query 里出现的新值优先级最高
- 如果历史里有多个候选值，取用户最近一次明确提到的值
- assistant 自己复述过的信息不能被当作新的事实来源

代码层面继续保持:

- 本轮抽到非空值才更新
- 空值不覆盖旧值

### 4. Missing-slot follow-up becomes query-aware

后续 graph 不再简单使用 `REQUIRED_SLOTS_BY_INTENT` 决定是否追问。

改为由当前 query 的语义决定:

- 当前问题是否和 `province` 密切相关
- 当前问题是否和 `year` 密切相关
- 哪些槽位缺失会明显影响“更精准回答”

只有当“当前 query 强相关”且“当前槽位为空”时，才把对应槽位放进 `missing_slots`。

这意味着:

- `631 是什么意思` 不应该追问 `province/year`
- `今年分数线多少` 缺 `province` 时可以追问 `province`
- `近几年录取情况` 不应该因为全局 `year` 已有值就被锁死成单一年份问题

### 5. Follow-up style stays user-friendly

当存在 `missing_slots` 且已经有检索材料时，保持当前 generation 的交互风格:

- 先给用户一些相关案例、代表性省份或已有信息
- 最后再加一句补充询问

也就是说，“缺槽位”不等于“立刻只问不答”。

### 6. Remembered year must not override range-style queries

全局 `slots.year` 只是记忆，不是每轮 query 的强过滤条件。

对于下面这类 query:

- `近几年录取情况`
- `历年录取分数`
- `最近几年录取情况`
- `近三年录取位次`

当前 query 的时间语义优先级高于历史记忆中的精确 `year`。在这类情况下:

- 可以继续使用全局 `province`
- 不能默认把全局精确 `year` 当作当前 SQL/检索过滤条件

## Architecture Changes

### `intent_classify`

新增一类输出: 当前 query 的槽位需求。

推荐在结果模型中增加 `required_slots`，表示“当前问题想更精准回答时真正依赖的槽位集合”。该字段由 LLM 基于 query 语义判断。

同时保留并收紧 `slots`:

- 只接收 `province/year`
- 清洗空值
- 用新值覆盖旧值

### `WorkflowState`

在顶层 state 中新增:

- `required_slots: list[str]`

它表示当前 query 语义下真正相关的槽位，而不是全局静态配置。

### `RAGState`

把 `required_slots` 从顶层传入 Agentic RAG 子图，供 sufficiency eval 使用。

### `sufficiency_eval`

不再使用 `REQUIRED_SLOTS_BY_INTENT` 作为唯一缺槽依据。

改为:

- 读取 `required_slots`
- 只对 `required_slots` 里的槽位做缺失判断

这样生成阶段收到的 `missing_slots` 就是“当前 query 真正缺、且值得追问”的槽位。

### `search_planner` and `sql_query`

需要增加一个 query-aware 的 year 使用策略。

第一版可以采用轻量实现:

- 当 query 表达的是范围型时间语义时，禁止把记忆中的精确 `slots.year` 作为 SQL 默认过滤条件
- 当 query 是精确年份或本轮明确提到了年份时，允许继续使用当前轮/全局 year

这可以通过 planner 传递标记，或通过 SQL 节点中的小型 helper 决定。

## Non-Goals

这次不做:

- 新增独立 slot extraction graph node
- 引入通用多槽位 schema
- 把所有 query 语义都结构化成复杂时间 DSL
- 重写 generation 的整体 prompt 架构

## Files Likely To Change

- `src/graph/node/intent_classify.py`
- `src/graph/state.py`
- `src/graph/agentic_rag/schemas.py`
- `src/graph/agentic_rag/graph.py`
- `src/graph/agentic_rag/node/sufficiency_eval.py`
- `src/graph/agentic_rag/node/search_planner.py`
- `src/graph/agentic_rag/node/sql_query.py`
- `src/graph/prompts.py`
- `tests/graph/...`

## Summary

这次改动的核心不是“多加两个槽位”，而是把系统改成两层语义:

- 全局层: 记住用户最近一次确认过的 `province/year`
- 当前问题层: 只在 query 真的需要时才依赖或追问这些槽位

这样既能保留多轮对话记忆，又不会让历史 `year` 把“近几年”这类问题错误地窄化成单一年份查询。
