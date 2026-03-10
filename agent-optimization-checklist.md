# 招生咨询智能体 — 优化清单

基于「智能体 A：招生咨询智能体」的最终需求（场景、用户故事、知识体系），对当前 `src` 内智能体实现的差距与可优化点整理如下。

---

## 一、需求与实现对照摘要

| 需求维度 | 当前实现 | 差距/建议 |
|----------|----------|----------|
| **场景 1** 了解南科大基本情况 | 意图 `school_overview` + collection `school_overview` | 已覆盖；可强化「5 分钟内判断」的回复风格 |
| **场景 2** 招生政策与录取信息 | 意图 `admission_policy` + collection `admission_policy` | 已覆盖；需保证数据按年更新与精准性 |
| **场景 3** 专业与就业前景 | 专业有 `majors_and_training`；就业/深造当前 **无检索** | 见下文「知识库与检索」 |
| **知识体系** 毕业去向、校园生活 | 意图已定义，collection 映射为 `"None"` | 检索被跳过，仅靠生成模型；需补 collection 与数据 |

---

## 二、知识库与检索

### 2.1 补齐意图 → Collection 映射（高优先级）

**现状**（`src/config.py`）：

```python
INTENT_COLLECTION_MAP: dict[str, str] = {
    IntentType.SCHOOL_OVERVIEW.value: "school_overview",
    IntentType.ADMISSION_POLICY.value: "admission_policy",
    IntentType.MAJOR_AND_TRAINING.value: "majors_and_training",
    IntentType.CAREER_AND_DEVELOPMENT.value: "None",   # 无检索
    IntentType.CAMPUS_LIFE.value: "None",             # 无检索
}
```

**问题**：`career_and_development`（毕业去向与发展）、`campus_life`（校园生活）映射为 `"None"`，`vector_retrieve` 会直接跳过检索，返回空 chunks，生成阶段缺乏权威文档支撑。

**建议**：

1. **毕业去向与发展**：新增 collection（如 `career_and_development`），与招办/就业办数据源对接，导入深造率、境内/境外比例、就业行业、薪资参考等。
2. **校园生活**：新增 collection（如 `campus_life`），导入书院介绍、住宿、奖助学金、学费等。
3. 在 `INTENT_COLLECTION_MAP` 中改为真实 collection 名，并与 `data/config.py` 的 `DIR_TO_COLLECTION`（若沿用目录导入）及导入脚本的 `--index` 保持一致。

### 2.2 数据源与“按年更新”

需求中招生政策、招生计划、时间节点、录取分数线等标注为「招办（按年更新）」。当前实现未区分年份或版本。

**建议**：

- 在 chunk 元数据中增加 `year` / `term`（如 2025、2026）或 `source_version`。
- 导入时按年份/版本建 collection 或带年份的 index，或在检索/生成时优先使用“最新版”数据（需与招办约定数据命名与更新流程）。

### 2.3 检索策略增强（可选）

- **招生政策**：对报名时间、分数线、631 计算方式等强事实类问题，可考虑 **混合检索**（向量 + 关键词/结构化字段），减少仅向量检索的遗漏。
- **多意图**：若用户一问涉及多类（如「学校怎么样 + 怎么报名」），可考虑多意图或主意图+副意图，分别检索多 collection 再合并上下文（当前为单意图单 collection）。

---

## 三、意图识别

### 3.1 意图定义与需求表格对齐

当前 `INTENT_DESCRIPTIONS` 已覆盖五大类，可与需求 2.2 的表格进一步对齐，便于模型和运营理解：

- **学校概况**：显式列出「学校定位、办学特色、校园与城市、师资概况、科研实力」。
- **招生政策**：显式列出「招生模式(631)、报名条件、招生计划、时间节点、考核方式、录取规则、各省差异」。
- **专业与培养**：显式列出「专业目录、专业介绍、入学后选专业、转专业政策」。
- **毕业去向与发展**：显式列出「深造率、就业情况、知名校友」。
- **校园生活**：显式列出「书院制度、住宿条件、奖助学金、学费标准」。

可在 `config.py` 的 `INTENT_DESCRIPTIONS` 或意图分类 prompt 中引用上述关键词，提升边界 case 的分类稳定性。

### 3.2 意图置信度与落空意图

当前 `IntentClassificationResult` 含 `confidence`，但未在图中使用：无论置信度高低都会进入 retrieve → rerank → generate。

**建议**：

- 低置信度时（如 <0.6）：可走「澄清」分支，回复“您是想了解招生政策、专业介绍还是其他？”再根据下一轮补充检索。
- 或对「无法归类」增加 `out_of_scope` 意图，返回友好提示并引导到官网/招办电话（避免幻觉）。

---

## 四、生成与提示词

### 4.1 角色与场景化 System Prompt

当前 `generation.py` 中：

```python
system_prompt = (
    "You are an admission assistant for SUSTech. "
    "Answer based on retrieved documents and conversation history.\n"
    "Rules:\n"
    "1) Prioritize retrieved evidence;\n"
    "2) If evidence is insufficient, say so clearly and suggest next steps;\n"
    "3) Keep answer concise and direct.\n"
)
```

**建议**（与三个核心场景一致）：

- 明确 **目标用户**：高中生及家长，尤其是高二下至高三上、综合评价报名前后。
- **场景 1**：强调「快速建立整体印象、5 分钟内能判断是否值得深入了解」——回复结构清晰（如：定位 + 特色 + 城市/校园），控制篇幅。
- **场景 2**：强调「招生政策与时间节点务必以检索到的文档为准」；若文档不足，明确建议「以官网/招办最新通知为准」并避免编造日期或比例。
- **场景 3**：专业与就业要区分「培养内容」与「毕业去向」，数据不足时说明「具体数据请以学校就业报告为准」。

可将上述要点写进 system prompt，并按 `intent` 做简短分支（可选），使语气和侧重点更贴合场景。

### 4.2 引用与免责

- 对关键事实（尤其是招生政策、分数线、时间节点），可在回复中标注「根据目前掌握的资料」或「请以招生网最新公布为准」。
- 若产品需要，可在 UI 层展示「参考来源」（如 chunk 对应的文档/段落），后端可在 state 中保留 `chunks` 的 metadata 供前端展示。

### 4.3 语言与长度

- 统一使用中文回复（当前 user_prompt 为英文 "User question" 等，可改为中文，与意图描述一致）。
- 可针对「快速了解」类意图限制回复长度或给出「简要版 / 详细版」策略（由 prompt 或后续产品决定）。

---

## 五、流程与体验

### 5.1 无检索时的行为

当 intent 对应 collection 为 `None` 或检索结果为 0 条时，当前仍会进入 rerank → generate，此时 context 为 `(no retrieved documents)`。生成模型易产生幻觉。

**建议**：

- 对「无有效检索结果」在生成前做分支：若 chunks 为空且意图属于「强事实类」（如招生政策、录取规则），回复固定话术：「该方面信息正在整理中，建议您查阅南科大招生网或联系招办获取最新信息」，避免编造。
- 或为「无检索」单独设一条 system 提示，明确禁止猜测数字、日期、比例。

### 5.2 多轮与上下文

当前已传入 `messages` 与 `query`，生成阶段有 `_history_text`，多轮对话能力存在。可再确认：

- 历史轮数上限（当前 `max_turns=6`）是否满足「同一会话内连续问招生 + 专业 + 生活」的场景。
- 若用户追问「那报名时间呢」，是否将上一轮的 intent 作为 hint 传给检索（当前每轮重新做意图分类，一般可行；若需要可做「追问时优先沿用上一轮 intent」的优化）。

### 5.3 会话与追溯

- `stream_stage_events` 已暴露 `intent`、`chunks_count` 等，便于前端展示「正在查询招生政策」等状态。
- 若需审计或质检，可在 state 或日志中保留「意图 + 检索到的 doc id / 摘要」，便于与招办一起做答案溯源与年度更新校验。

---

## 六、配置与运维

### 6.1 配置集中与一致性

- **Collection 命名**：`src/config.py`（意图→collection）、`data/config.py`（目录→collection）、导入脚本的 `--index`、Milvus 实际 collection 名需统一，避免写错或漏配。
- **Rerank**：`create_rerank_node()` 内 `rerank_model_id = "jina-reranker"`、`top_n = 5` 建议抽到配置或 env，便于不同环境切换。

### 6.2 可观测性

- 已有 debug 日志（intent、chunks 数量、answer 长度）；若上线，可增加：
  - 意图分布、无检索比例、平均 chunk 数。
  - 对「无检索」的请求单独打点，便于推动补全 `career_and_development`、`campus_life` 数据。

---

## 七、优先级建议

| 优先级 | 项 | 说明 |
|--------|----|------|
| P0 | 补齐 `career_and_development`、`campus_life` 的 collection 与数据，并更新 `INTENT_COLLECTION_MAP` | 否则这两类问题无权威检索，体验与风险都大 |
| P0 | 无检索时的生成策略（强事实类禁止猜测 + 引导官网/招办） | 避免招生政策类幻觉 |
| P1 | System prompt 场景化（用户身份、5 分钟了解、招生以文档为准） | 提升回复契合度与安全性 |
| P1 | 意图描述与需求 2.2 表格对齐，便于分类与运营 | 提升意图识别稳定性 |
| P2 | 招生数据按年/版本管理与检索策略 | 支撑「按年更新」 |
| P2 | 低置信度意图的澄清或 out_of_scope 处理 | 体验与安全 |
| P3 | 混合检索、多意图检索、引用来源与免责 | 按产品与资源再排期 |

---

## 八、小结

- **已较好对齐需求**：意图与知识体系五大类一致，学校概况、招生政策、专业与培养已有对应 collection 与流程。
- **主要缺口**：毕业去向、校园生活两类无检索（collection 为 `"None"`）；无检索时的生成未做约束，存在幻觉风险。
- **建议优先**：补全上述两个 collection 与数据、更新映射；在生成前对「无检索」做分支并约束强事实类回答；再细化 system prompt 与意图描述，并与招办一起落实数据按年更新与溯源机制。

如需，我可以按上述某一项写出具体改动方案（含代码位置和示例补丁）。
