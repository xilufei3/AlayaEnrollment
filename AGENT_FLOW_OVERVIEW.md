# 当前智能体流程总览

这份文档用于帮助另一个大模型快速理解本项目当前智能体的整体设计、状态流转、节点职责、提示词约束与能力边界。文档基于 `src/graph` 及其依赖实现整理，尽量贴近真实代码，而不是理想化设计。

## 1. 一句话总结

当前智能体是一个面向“南方科技大学本科招生咨询”的 LangGraph 工作流，整体采用两层结构：

- 第一层是主工作流：`意图分类 -> (闲聊 / 超范围 / Agentic RAG) -> (缺槽位追问 / 正式生成)`
- 第二层是 `agentic_rag` 子图：`检索规划 -> 向量检索 + SQL 规划/查询 -> 重排 -> 上下文合并 -> 材料充分性评估 -> 不足则重试`

它不是一个自由代理式 ReAct 智能体，而是一个“强流程约束的多节点图工作流”。模型的自由度主要集中在：

- 意图分类与槽位提取
- 检索改写与 SQL 路由判断
- 材料是否充分的评估
- 最终回答的语言组织

真正的流程控制、回退策略和路由规则，主要都写死在代码中。

## 2. 目标与职责范围

该智能体的目标是回答“南科大本科招生”相关问题，覆盖的大类意图包括：

- `school_overview`：学校概况
- `admission_policy`：招生政策、录取、分数、位次、631 等
- `major_and_training`：专业与培养
- `career_and_development`：升学就业去向
- `campus_life`：校园生活
- `other`：闲聊、打招呼、泛化开场
- `out_of_scope`：与南科大本科招生无关

它还维护两个全局槽位：

- `province`
- `year`

其中当前实现最强调的槽位是 `province`。在配置里，`admission_policy` 默认需要省份信息才能更精准回答；但具体某一轮是否“缺槽位”，最终由意图分类节点结合当前问题动态输出 `required_slots` 决定。

## 3. 总体架构

### 3.1 主图

主图入口在 `src/graph/graph.py`，结构可以概括为：

```text
START
  -> intent_classify
     -> direct_reply              if intent == out_of_scope
     -> direct_reply              if intent == other or confidence < threshold
     -> agentic_rag               otherwise
          -> slot_followup        if missing_slots 非空
          -> generate             otherwise
END
```

关键路由规则：

1. 如果意图为 `out_of_scope`，直接走短回复节点中的“超范围引导”分支。
2. 如果意图为 `other`，或者意图置信度低于阈值 `0.55`，直接走短回复节点中的“闲聊/兜底回复”分支。
3. 其余情况进入 `agentic_rag` 子图。
4. `agentic_rag` 返回后：
   - 若 `missing_slots` 非空，走 `slot_followup`
   - 否则走 `generate`

### 3.2 Agentic RAG 子图

子图入口在 `src/graph/agentic_rag/graph.py`，结构如下：

```text
START
  -> search_planner
      -> retrieval --------> rerank ----\
      -> sql_plan_builder -> sql_query --+-> merge_context -> eval
                                                  |
                                                  +-> if sufficient / missing_slots: END
                                                  +-> if insufficient_docs and 未超轮次: 回到 search_planner
```

这个子图有两个重要特点：

1. 它是“并行双路”：
   - 一路做向量检索
   - 一路做 SQL 能力判断和结构化查询
2. 它是“有上限的迭代式检索”：
   - 默认最多 2 轮
   - 如果评估为材料不足，会再规划一次搜索并扩大检索范围

## 4. 共享状态设计

### 4.1 主图状态 `WorkflowState`

主图状态定义在 `src/graph/state.py`。核心字段如下：

| 字段 | 含义 |
| --- | --- |
| `thread_id` | 会话线程 ID |
| `turn_id` | 当前轮次 ID |
| `messages` | 多轮消息历史，LangGraph 用 `add_messages` 合并 |
| `query` | 当前用户问题文本 |
| `intent` | 当前轮识别出的意图 |
| `confidence` | 意图置信度 |
| `slots` | 全局槽位记忆，目前主要是 `province` / `year` |
| `required_slots` | 当前问题若想准确回答，需要哪些槽位 |
| `missing_slots` | `required_slots` 中当前仍缺失的槽位 |
| `chunks` | 最终用于生成的非结构化文档块 |
| `structured_results` | SQL 查询得到的结构化结果 |
| `citations` | 预留字段，当前主流程基本未使用 |
| `retrieval_skipped` | 是否跳过检索，主要用于闲聊/超范围 |
| `answer` | 最终回答 |

### 4.2 RAG 子图状态 `RAGState`

定义在 `src/graph/agentic_rag/schemas.py`。可分成几类：

输入镜像：

- `query`
- `intent`
- `slots`
- `required_slots`

循环控制：

- `rag_iteration`
- `max_iterations`
- `eval_result`
- `eval_reason`
- `missing_slots`

检索规划：

- `search_plan`
- `sql_candidate`
- `sql_plan`

中间结果：

- `vector_chunks`
- `candidate_vector_chunks`
- `reranked_vector_chunks`
- `structured_results`

最终生成材料：

- `chunks`

这里用了一个统一 reducer `_overwrite`，语义是“最后写入者覆盖前值”。因此并行分支汇合时，状态冲突采用覆盖而非追加；但由于字段拆分得比较清楚，实际冲突较少。

## 5. 主流程逐节点解析

### 5.1 `intent_classify`

位置：`src/graph/node/intent_classify.py`

职责：

- 读取当前用户问题
- 截取最近若干轮对话上下文
- 用 LLM 做意图分类
- 同时抽取 `province` / `year`
- 同时判断当前问题真正需要哪些槽位
- 将本轮抽取结果合并进全局 `slots`

输入来源：

- 当前 `query`
- 最近 `HISTORY_LAST_K_TURNS = 2` 轮对话历史

输出字段：

- `query`
- `intent`
- `confidence`
- `slots`
- `required_slots`
- `missing_slots`

关键实现点：

1. 历史上下文只取“当前用户问题之前”的最近 2 轮对话。
2. 槽位白名单严格限制为 `province` 和 `year`。
3. 新槽位会覆盖旧槽位，形成跨轮记忆。
4. `missing_slots` 的计算方式是：
   - 遍历 `required_slots`
   - 如果在 `slots` 中没有值，就记为缺失
5. 如果分类节点异常失败：
   - 回退到 `admission_policy`
   - `confidence = 0`
   - 槽位为空
   - 由于主图中低置信度会转去 `direct_reply`，因此这个 fallback 实际偏保守

该节点的提示词要求模型输出严格 JSON，字段包括：

- `intent`
- `reason`
- `confidence`
- `slots`
- `required_slots`

### 5.2 主图路由：`route_after_intent`

位置：`src/graph/graph.py`

逻辑非常关键：

- `intent == out_of_scope` -> `direct_reply`
- `intent == other` 或 `confidence < 0.55` -> `direct_reply`
- 否则 -> `agentic_rag`

这意味着：

1. 低置信度问题默认不会冒然进入检索问答，而是先用轻量闲聊兜住。
2. 只有“明确像招生咨询”的问题才进入 RAG。

### 5.3 `direct_reply`

位置：`src/graph/node/direct_reply.py`

职责：

- 统一处理 `out_of_scope`、`other` 和低置信度兜底回复
- 根据意图选择不同的短回复提示词与 fallback 文案

特点：

- 不走检索
- 直接调用短回复生成
- `out_of_scope` 时礼貌说明服务边界并引导回招生问题
- `other` / 低置信度时用一句轻量寒暄或兜底回复承接
- 结果会写入 `answer` 和 `messages`
- 标记 `retrieval_skipped = True`

### 5.4 `agentic_rag`

位置：`src/graph/graph.py` 调用 `src/graph/agentic_rag/graph.py`

职责：

- 对正式招生问题做受控检索增强
- 决定是否需要 SQL
- 决定现有材料是否足够回答
- 若不足，进行最多 2 轮的重试

它返回给主图的只有三个关键结果：

- `chunks`
- `missing_slots`
- `structured_results`

注意：这里没有直接生成回答文本，回答文本仍由主图末端的 `slot_followup` 或 `generate` 负责。

### 5.6 主图路由：`route_after_rag`

位置：`src/graph/graph.py`

逻辑：

- 若 `missing_slots` 非空 -> `slot_followup`
- 否则 -> `generate`

这说明缺槽位不是在 RAG 子图里直接追问，而是由主图在 RAG 完成后统一收口处理。

### 5.7 `slot_followup`

位置：`src/graph/node/slot_followup.py`

职责：

- 当回答当前问题仍缺少关键信息时，向用户补问

它分两种情况：

1. 如果已经有一些 `chunks`
   - 先基于已有材料给一个简短参考
   - 再自然地追问缺失信息
2. 如果没有 `chunks`
   - 直接生成一句简短追问

这说明当前架构允许一种“半回答 + 追问”的体验：即使缺槽位，也可能先给用户一个通用参考，再补问 `province` 或 `year`。

### 5.8 `generate`

位置：`src/graph/node/generation.py`

职责：

- 使用最终的 `chunks` + `structured_results` + 最近历史，生成面向用户的正式回答

输入：

- `query`
- `intent`
- `chunks`
- `structured_results`
- 最近 2 轮历史

输出：

- `answer`
- `messages`

关键实现点：

1. 如果有材料，生成提示词会要求模型充分使用材料。
2. 如果没有材料，会切换到“自然告知暂未查到，建议查看招生网/联系招办”的模式。
3. 会注入当前时间提示，默认时区是 `Asia/Shanghai`，可通过 `ASSISTANT_TIMEZONE` 覆盖。
4. 优先使用流式 `astream` 生成，失败时再退回 `ainvoke`。
5. 结构化 SQL 结果会被拼成文本一起喂给生成模型。

## 6. Agentic RAG 子图逐节点解析

### 6.1 `search_planner`

位置：`src/graph/agentic_rag/node/search_planner.py`

职责：

- 把用户问题改写成更适合检索的查询
- 为本轮检索确定 `top_k`
- 判断该问题是否适合走 SQL 路径

输出：

- `search_plan`
- `sql_candidate`
- `sql_plan` 的默认空值
- `rag_iteration + 1`

`search_plan` 当前主要包含：

- `strategy`：默认是 `vector_keyword_hybrid`
- `vector_query`：改写后的检索词
- `top_k`

`sql_candidate` 主要包含：

- `enabled`
- `selected_tables`
- `reason`

关键规则：

1. `top_k` 按意图类型设不同默认值。
2. 如果进入第二轮检索，`top_k` 会增大，最多加到 16。
3. 如果用户问题明显是“近几年/近年来/历年/近N年”这种年份范围型表达，会暂时屏蔽 `year` 槽位，避免把检索误收窄成单一年份。
4. 会把 SQL 表注册信息摘要传给 LLM，允许它决定是否启用 SQL。
5. 如果 LLM 规划失败，就回退到规则版 planner，不启用 SQL。

### 6.2 `retrieval`

位置：`src/graph/agentic_rag/node/retrieval.py`

职责：

- 使用外部注入的 `retriever.search(...)` 执行向量/混合检索

前提：

- `create_graph(...)` 必须传入 `retriever`
- 这个对象必须提供 `search(query, top_k, filter_expr, mode)` 方法

特点：

- 当前默认 strategy 会映射到 `SEARCH_HYBRID`
- 查询为空时直接跳过
- 会把命中结果转成 `Document`
- 会对结果做去重

输出：

- `vector_chunks`

### 6.3 `rerank`

位置：`src/graph/agentic_rag/node/rerank.py`

职责：

- 对候选文档做 Jina rerank 重排

关键机制：

1. 会把“历史候选文档”和“本轮新召回文档”合并成 `candidate_vector_chunks`。
2. 合并后最多保留 25 条候选，避免迭代中上下文无限膨胀。
3. 使用改写后的 `vector_query` 做 rerank；如果没有改写词，就用原始 `query`。
4. 出错时会回退为“不重排，直接使用合并后的候选文档”。

输出：

- `candidate_vector_chunks`
- `reranked_vector_chunks`

这意味着 RAG 的多轮不是简单覆盖，而是会在一定程度上累积召回候选，再重新排序。

### 6.4 `sql_plan_builder`

位置：`src/graph/agentic_rag/node/sql_plan_builder.py`

职责：

- 在 `search_planner` 已决定启用 SQL 时，生成一个轻量结构化查询计划

输入：

- `query`
- `intent`
- `slots`
- `sql_candidate`

输出：

- `sql_plan`

`sql_plan` 大致包含：

- `enabled`
- `table_plans`
- `limit`
- `reason`

每个 `table_plan` 包含：

- `table`
- `key_values`
- `reason`

关键规则：

1. 只能使用 `search_planner` 选中的表。
2. 只能使用表注册信息里声明过的 `query_key`。
3. 如果用户问的是年份范围问题，也会屏蔽单一年份槽位。
4. 如果 LLM 生成 SQL 计划失败，会回退为“按已选表 + 当前槽位”构造的保守计划。

### 6.5 `sql_query`

位置：`src/graph/agentic_rag/node/sql_query.py`

职责：

- 执行当前 SQL 计划并拿回结构化结果

当前实现实际上只支持一张表：

- `admission_scores`

只要 `sql_plan` 中有这张表，就会调用：

- `query_admission_scores(provinces, years, limit)`

而不会生成任意 SQL 文本。

这说明当前所谓“SQL 能力”本质上是：

- LLM 决定是否启用结构化查询
- LLM 决定查询键值
- 真正执行仍是白名单函数 `query_admission_scores`

所以这是一个“安全的半结构化 SQL 路由”，不是开放式 SQL Agent。

### 6.6 `merge_context`

位置：`src/graph/agentic_rag/node/merge_context.py`

职责非常简单：

- 把 `reranked_vector_chunks` 赋值给 `chunks`

注意：

- 它不会把 SQL 结果拼进 `chunks`
- SQL 结果依然单独保存在 `structured_results`
- 最终生成节点会同时读取这两类输入

### 6.7 `eval`

位置：`src/graph/agentic_rag/node/sufficiency_eval.py`

职责：

- 判断现有材料是否足以直接回答用户

可能输出三类结果：

- `sufficient`
- `missing_slots`
- `insufficient_docs`

判定顺序非常重要：

1. 如果 `chunks` 和 `structured_results` 都为空
   - 直接 `insufficient_docs`
2. 如果 `missing_slots` 非空
   - 直接 `missing_slots`
3. 否则让 LLM 判断当前材料是否足够回答

也就是说：

- “缺槽位”优先级高于“材料是否充分”
- 但由于子图入口没有提前短路，所以即使缺槽位，也可能已经做过一次检索，这样后续 `slot_followup` 可以带着少量参考信息追问用户

LLM 评估失败时，回退为：

- `insufficient_docs`
- 理由为“评估失败，回退后重试”

### 6.8 `eval` 之后的循环控制

位置：`src/graph/agentic_rag/graph.py`

规则如下：

- 如果结果是 `missing_slots` 或 `sufficient`，结束子图
- 如果结果是 `insufficient_docs` 且还没到最大轮次，回到 `search_planner`
- 如果已到最大轮次，也结束子图

默认最大轮次 `max_iterations = 2`。

从代码语义上看，当前实现意味着：

- 通常最多执行 2 轮检索规划/检索/评估
- 到上限后不会继续尝试，而是把当前已有材料交给主图末端处理

## 7. 提示词层面的关键约束

### 7.1 意图分类提示词

核心要求：

- 不是做关键词匹配，而是理解真实咨询目标
- 可利用最近几轮对话
- 只允许输出 `province` / `year`
- 助手自己说过的话不能当新的事实来源
- 要同时判断当前问题是否真的依赖这些槽位
- 必须输出严格 JSON

这保证了意图分类节点兼具：

- 路由功能
- 槽位抽取功能
- 缺信息判定功能

### 7.2 检索规划提示词

核心要求：

- 把用户问题改写成更适合召回官方招生信息的查询
- 保留学校、省份、年份、专业、批次、选科要求、规则名等关键信息
- 宽问题适度展开，窄问题保持聚焦
- 只有明显命中某个结构化表使用场景时才启用 SQL
- 像“631 是什么”“规则是什么”这类解释性问题不能误走 SQL

### 7.3 SQL 计划提示词

核心要求：

- 只能基于已选中的表
- 只能提取表注册元数据中存在的查询键
- 只生成结构化查询计划，不生成 SQL 语句

### 7.4 充分性评估提示词

核心要求：

- 只判断“是否足够回答”
- 不评价文档质量
- 输出只能是 `sufficient` / `insufficient_docs`

注意：`missing_slots` 不是 LLM 评估得出的，而是代码层根据意图分类透传。

### 7.5 生成提示词

最终生成提示词约束很强，核心倾向是：

- 先直接回答，再补充相关实用信息
- 语气像招生老师，不像知识库管理员
- 不能暴露“根据文档/检索结果显示”这类内部过程
- 对具体分数、比例、日期、录取规则等，必须有材料支持
- 若材料中存在明显对比维度，优先用简洁表格
- 允许基于材料做直接推理，但不能继续叠加猜测
- 材料不足时，要自然地建议用户查看招生网或联系招办

这意味着生成节点不是“自由聊天”，而是一个被强风格约束的问答生成器。

## 8. 多轮对话与槽位记忆

当前智能体支持有限的多轮继承：

1. `messages` 中保留完整消息历史。
2. 意图分类和生成只截取最近 `2` 轮对话作为显式上下文。
3. `slots` 是跨轮持久化记忆：
   - 新轮提到的 `province` / `year` 会覆盖旧值
   - 后续问题如果省略这些信息，可以从 `slots` 中补回

因此它更像“轻量会话型助手”，而不是长期记忆代理。

## 9. 模型分工

模型配置在 `src/graph/llm.py` 中统一构建，按角色分为：

- `intent`
- `generation`
- `planner`
- `eval`
- `rerank`

当前设计要点：

1. `intent` / `generation` / `planner` / `eval`
   - 都通过 `ChatOpenAI` 兼容接口接入
   - 实际可指向 DeepSeek/Qwen 等兼容 OpenAI API 的服务
2. `rerank`
   - 使用 Jina reranker
3. 每种模型都有独立超时和重试预算
4. 所有模型实例会被缓存复用
5. 一些节点会根据运行时上下文动态切换 `model_id`

## 10. 当前 SQL 能力边界

当前 SQL 路径非常明确，且能力边界较窄。

已注册表：

- `admission_scores`

表描述：

- 各省各年份录取数据宽表
- 查询键是 `province + year`

适用场景：

- 某省某年录取数据
- 最高分、平均分、最低分、位次
- 某省近几年录取情况

真正执行的查询函数是：

- `query_admission_scores(provinces, years, limit)`

特点：

- 只做白名单参数查询
- 不允许模型直接拼任意 SQL
- 返回结构化行数据，供生成节点组织成表格或说明

## 11. 错误处理与回退策略

整个系统整体上偏“保守兜底”，主要回退策略包括：

1. 意图分类失败
   - 回退到 `admission_policy`
   - 但置信度为 0，主图通常会把它送去 `direct_reply`

2. 检索规划失败
   - 使用规则版 planner
   - 默认不启用 SQL

3. SQL 计划失败
   - 用已知槽位构造保守表计划

4. 向量检索失败
   - 返回空文档

5. rerank 失败
   - 直接使用未重排候选文档

6. 充分性评估失败
   - 视为 `insufficient_docs`，促使系统再试一轮

7. 生成失败
   - 返回空字符串或短回复 fallback

8. 无材料时的最终生成
   - 自然建议用户查看招生网或联系招办

这套设计说明系统优先保证：

- 不乱答
- 能退则退
- 尽量避免把内部异常直接暴露给用户

## 12. 当前能力边界与局限

如果要让另一个模型快速判断“这套系统能做什么、不能做什么”，最重要的是以下几点：

1. 这不是通用助手，只服务于“南科大本科招生咨询”。
2. 它不是开放式工具代理，工具调用路径基本写死。
3. SQL 目前只覆盖 `admission_scores` 一张表。
4. `missing_slots` 的核心来源是意图分类节点，而不是后续 RAG 自主发现。
5. `citations` 字段还没有真正串进主流程产出。
6. 最终生成虽然会读 SQL 结果，但不会自动生成引用标注。
7. RAG 子图最多只重试 2 轮，不会无限搜索。
8. 对话历史只显式看最近 2 轮，因此长上下文继承有限。
9. 低置信度问题会被导向闲聊兜底，这有助于安全，但也可能让少数真实问题被“保守处理”。

## 13. 如果把它抽象成伪代码

```python
def workflow(user_query, messages, slots):
    intent_result = classify_intent_and_extract_slots(user_query, recent_history=last_2_turns(messages))
    merged_slots = merge(slots, intent_result.slots)
    missing_slots = required_minus_existing(intent_result.required_slots, merged_slots)

    if intent_result.intent == "out_of_scope":
        return direct_reply(user_query, intent="out_of_scope")

    if intent_result.intent == "other" or intent_result.confidence < 0.55:
        return direct_reply(user_query, intent=intent_result.intent)

    rag_state = run_agentic_rag(
        query=user_query,
        intent=intent_result.intent,
        slots=merged_slots,
        required_slots=intent_result.required_slots,
        missing_slots=missing_slots,
    )

    if rag_state.missing_slots:
        return slot_followup(
            query=user_query,
            chunks=rag_state.chunks,
            structured_results=rag_state.structured_results,
            missing_slots=rag_state.missing_slots,
        )

    return generate_answer(
        query=user_query,
        intent=intent_result.intent,
        chunks=rag_state.chunks,
        structured_results=rag_state.structured_results,
        history=last_2_turns(messages),
    )
```

`run_agentic_rag(...)` 可进一步抽象为：

```python
for iteration in range(max_iterations):
    search_plan, sql_candidate = plan_search(query, intent, slots, previous_eval_reason)
    vector_docs = retrieve(search_plan)
    reranked_docs = rerank(accumulate(vector_docs))
    sql_plan = build_sql_plan(sql_candidate, slots)
    structured_rows = run_sql(sql_plan)
    chunks = reranked_docs
    eval_result = evaluate_sufficiency(chunks, structured_rows, missing_slots)

    if eval_result in ["sufficient", "missing_slots"]:
        break
```

## 14. 给其他大模型的接手建议

如果你是另一个大模型，想继续在这个项目上工作，建议优先按以下理解方式接手：

1. 把主图看成“外层业务编排器”。
2. 把 `agentic_rag` 看成“受控检索子系统”，不是自由代理。
3. 把 `intent_classify` 看成整个系统最关键的前置节点，因为它同时决定：
   - 用户问题属于什么场景
   - 是否进入 RAG
   - 需要哪些槽位
   - 是否走追问
4. 把 `search_planner` 看成“检索改写 + SQL 路由器”。
5. 把 `generate` 看成“最后的用户态表达器”，它不负责做流程判断，只负责把现有材料说清楚。

如果后续要扩展能力，最自然的扩展点通常是：

- 新增更多结构化表与白名单查询函数
- 在 `merge_context` 中显式融合文档块与 SQL 结果
- 为最终回答加入可见引用
- 让 `required_slots` 与不同意图绑定得更系统
- 改进低置信度直接走闲聊的保守策略

## 15. 关键文件索引

- `src/graph/graph.py`：主图定义与路由
- `src/graph/state.py`：主图状态
- `src/graph/node/intent_classify.py`：意图分类与槽位提取
- `src/graph/node/generation.py`：最终正式生成
- `src/graph/node/slot_followup.py`：缺槽位追问
- `src/graph/node/direct_reply.py`：统一短回复节点（闲聊 / 超范围 / 低置信度）
- `src/graph/agentic_rag/graph.py`：RAG 子图定义
- `src/graph/agentic_rag/node/search_planner.py`：检索规划与 SQL 候选判定
- `src/graph/agentic_rag/node/retrieval.py`：向量/混合检索
- `src/graph/agentic_rag/node/rerank.py`：Jina 重排
- `src/graph/agentic_rag/node/sql_plan_builder.py`：结构化查询计划
- `src/graph/agentic_rag/node/sql_query.py`：白名单 SQL 查询
- `src/graph/agentic_rag/node/sufficiency_eval.py`：材料充分性评估
- `src/graph/prompts/`：按模块拆分后的提示词目录
- `src/config/settings.py`：意图、阈值、历史窗口、模型配置
- `src/config/table_registry.yaml`：SQL 表注册信息
- `src/knowledge/sql_manager.py`：SQL 元数据与执行入口
- `src/knowledge/sql_queries.py`：`admission_scores` 查询函数

## 16. 最简短结论

当前智能体的核心不是“让一个大模型自己想办法回答”，而是：

- 先用意图分类决定是否值得进入正式问答
- 再用受控的 Agentic RAG 获取尽可能可靠的材料
- 最后把材料组织成一个像招生老师说出来的答案

因此，这个系统的本质是“流程优先、模型辅助”的招生问答工作流。
