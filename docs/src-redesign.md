# src 重设计文档

基于「Agentic RAG + 意图路由」架构，对 `src/` 目录的完整重设计方案。

---

## 一、设计目标回顾

| 目标 | 对应设计点 |
|------|-----------|
| 5 类意图各自路由到独立知识域 | 顶层条件路由，不同意图进入 Agentic RAG |
| "其它"问题跳过 RAG 直接生成 | `other` → `direct_generate` 分支 |
| 检索不足时自动重试（有上限） | RAG 子图内部评估循环，`max_iterations=2` |
| 缺槽位时反问用户（而非自己猜） | 评估节点三分支：sufficient / missing_slots / insufficient |
| 混合检索（向量 + 结构化） | RAG 子图内并行两路检索 |

---

## 二、新目录结构

```
src/
├── __init__.py
├── config.py                       # 意图定义、collection 映射、槽位定义、常量
├── schemas.py                      # 顶层 WorkflowState（扩展）
├── graph.py                        # 顶层图：意图路由 + 子图/节点组装
│
├── api/
│   ├── __init__.py
│   └── chat_app.py                 # FastAPI（适配新 STAGE_ORDER，基本不变）
│
├── node/                           # 顶层图的直接节点（单步，不含循环）
│   ├── __init__.py
│   ├── intent_classify.py          # 原 intend_clasaify.py → 增加 slots 提取
│   ├── slot_ask.py                 # 【新】反问用户缺失的槽位
│   ├── fallback.py                 # 【新】out_of_scope 兜底话术
│   ├── direct_generate.py          # 【新】无 RAG 直接生成（other 意图）
│   ├── generation.py               # 最终生成（接收 RAG chunks，场景化 prompt）
│   └── runtime_resources.py        # 启动资源初始化（保持不变）
│
├── agentic_rag/                    # 【新模块】Agentic RAG 子图
│   ├── __init__.py
│   ├── graph.py                    # 子图定义与编译
│   ├── schemas.py                  # RAGState（子图内部状态）
│   └── node/
│       ├── __init__.py
│       ├── search_planner.py       # LLM：决定本轮检索策略
│       ├── vector_search.py        # 向量检索（从原 vector_retrieve.py 迁移）
│       ├── structured_search.py    # 【新】结构化检索（省份/年份精确查询）
│       ├── rerank.py               # 重排序（从原 rerank.py 迁移）
│       └── sufficiency_eval.py    # 【新】LLM 评估：足够/缺槽位/资料不足
│
└── runtime/
    ├── __init__.py
    ├── graph_runtime.py            # 更新 STAGE_ORDER 适配新节点名
    └── thread_registry.py          # 不变
```

**变更摘要（与现有 src 对比）：**

| 现有文件 | 去向 |
|---------|------|
| `node/intend_clasaify.py` | 重命名 → `node/intent_classify.py`，增加 slots 提取 |
| `node/vector_retrieve.py` | 迁移 → `agentic_rag/node/vector_search.py` |
| `node/rerank.py` | 迁移 → `agentic_rag/node/rerank.py`，参数外置 |
| `node/generation.py` | 保留，增加场景化 system prompt + 无检索 fallback 分支 |
| `graph.py` | 重写：线性边 → 条件边 + 子图调用 |
| `schemas.py` | 扩展：新增 confidence / slots / missing_slots 等字段 |

---

## 三、状态模型（Schemas）

### 3.1 顶层 WorkflowState

```python
# src/schemas.py

class WorkflowState(TypedDict, total=False):
    # ── 会话基础 ──────────────────────────────────────────
    thread_id: str
    turn_id: str
    messages: list[BaseMessage]

    # ── 意图路由（intent_classify 节点输出）─────────────────
    query: str
    intent: str           # IntentType value | "out_of_scope" | "other"
    confidence: float     # 0~1，用于条件路由
    slots: dict[str, str] # 已从问题提取的槽位，如 {"province": "浙江", "year": "2025"}

    # ── 槽位缺失（slot_ask 节点使用）────────────────────────
    missing_slots: list[str]   # 本轮缺失的槽位名，如 ["province"]
    clarify_question: str      # 反问话术，直接返回给用户

    # ── RAG 结果（agentic_rag 子图输出）────────────────────
    chunks: list[Document]
    citations: list[dict]      # [{doc_id, source, excerpt}] 供前端溯源
    retrieval_skipped: bool    # True 时 generation 使用无检索 prompt

    # ── 最终输出 ─────────────────────────────────────────
    answer: str
```

### 3.2 RAGState（子图内部状态）

```python
# src/agentic_rag/schemas.py

class SearchPlan(TypedDict):
    strategy: Literal["vector", "structured", "hybrid"]
    vector_query: str           # 向量检索用的查询（可改写）
    structured_filters: dict    # 结构化过滤条件，如 {"province": "浙江", "year": "2025"}
    top_k: int

class RAGState(TypedDict, total=False):
    # 从顶层 WorkflowState 传入
    query: str
    intent: str
    slots: dict[str, str]

    # 子图内部
    search_plan: SearchPlan
    rag_iteration: int           # 当前循环次数，初始 0
    max_iterations: int          # 最大重试次数，默认 2

    # 各路检索结果
    vector_chunks: list[Document]
    structured_results: list[dict]

    # 合并重排后
    chunks: list[Document]

    # 评估结果
    eval_result: Literal["sufficient", "missing_slots", "insufficient_docs"]
    missing_slots: list[str]     # eval 发现缺少的槽位
    eval_reason: str             # 评估理由（调试用）
```

---

## 四、图拓扑

### 4.1 顶层图（src/graph.py）

```
START
  │
  ▼
[intent_classify]
  │  输出: intent, confidence, slots, missing_slots(可选)
  │
  ▼ add_conditional_edges → route_after_intent()
  │
  ├─ "fallback"        → [fallback]          → END
  │                       (out_of_scope 兜底话术)
  │
  ├─ "slot_ask"        → [slot_ask]          → END
  │                       (低置信度 or 意图识别缺槽位时反问)
  │
  ├─ "direct_generate" → [direct_generate]   → END
  │                       (other 意图，不查知识库)
  │
  └─ "agentic_rag"     → [agentic_rag]       (子图，见 4.2)
                            │
                            ▼ add_conditional_edges → route_after_rag()
                            │
                            ├─ "slot_ask"  → [slot_ask]  → END
                            │                (RAG 评估发现缺省份等槽位)
                            │
                            └─ "generate"  → [generate]  → END
                                             (正常生成答案)
```

**路由函数逻辑：**

```python
# route_after_intent
def route_after_intent(state: WorkflowState) -> str:
    intent = state.get("intent", "")
    confidence = state.get("confidence", 1.0)
    missing = state.get("missing_slots") or []

    if intent == "out_of_scope":
        return "fallback"
    if intent == "other":
        return "direct_generate"
    if confidence < CONFIDENCE_THRESHOLD or missing:
        return "slot_ask"
    return "agentic_rag"

# route_after_rag
def route_after_rag(state: WorkflowState) -> str:
    missing = state.get("missing_slots") or []
    if missing:
        return "slot_ask"
    return "generate"
```

### 4.2 Agentic RAG 子图（src/agentic_rag/graph.py）

```
START（接收 query, intent, slots）
  │
  ▼
[search_planner]          LLM 决定本轮策略（vector/structured/hybrid）
  │  输出: search_plan
  │
  ▼
  ┌──────────┬──────────────┐
  │          │              │
[vector_   [structured_   (strategy=hybrid 时两路并行)
 search]    search]
  │          │
  └────┬─────┘
       │ 合并原始结果
       ▼
   [rerank]               Jina 重排序
       │ 输出: chunks（最终文档列表）
       │
       ▼
[sufficiency_eval]        LLM 评估检索质量
       │
       ▼ add_conditional_edges → route_after_eval()
       │
       ├─ "sufficient"      → END（携带 chunks 返回顶层）
       │
       ├─ "missing_slots"   → END（携带 missing_slots 返回顶层，顶层路由到 slot_ask）
       │
       └─ "insufficient"
              │
              ├─ iteration < max_iterations → 更新 search_plan → 回到 [search_planner]
              │
              └─ iteration >= max_iterations → END（返回当前 chunks，交生成兜底处理）
```

---

## 五、各节点职责与接口

### 5.1 顶层节点

#### `node/intent_classify.py`
**职责**：识别意图类型、置信度，同时提取可识别的槽位（省份、年份等）。

| | 说明 |
|-|------|
| **输入** | `state.query` / `state.messages`（取最后一条用户消息） |
| **输出** | `intent`, `confidence`, `slots`, `missing_slots`（需要但未提供的槽位） |
| **模型** | `intent_model_id`（LLM，JSON 模式） |
| **变更点** | 原版只输出 intent/reason/confidence；新版新增 slots 和 missing_slots 提取 |

意图类型扩展（`config.py`）：
```python
class IntentType(str, Enum):
    SCHOOL_OVERVIEW       = "school_overview"
    ADMISSION_POLICY      = "admission_policy"
    MAJOR_AND_TRAINING    = "major_and_training"
    CAREER_AND_DEVELOPMENT = "career_and_development"
    CAMPUS_LIFE           = "campus_life"
    OUT_OF_SCOPE          = "out_of_scope"   # 【新】完全非招生问题
    OTHER                 = "other"           # 【新】招生相关但无需检索（如打招呼）
```

槽位定义（`config.py`）：
```python
REQUIRED_SLOTS_BY_INTENT: dict[str, list[str]] = {
    "admission_policy": ["province"],   # 省份是招生政策的核心槽位
    "school_overview": [],
    "major_and_training": [],
    "career_and_development": [],
    "campus_life": [],
}
```

---

#### `node/slot_ask.py`（新）
**职责**：根据 `missing_slots` 列表，生成自然语言反问话术，写入 `clarify_question`，同时更新 `messages`（追加 AI 反问消息），然后结束本轮。

| | 说明 |
|-|------|
| **输入** | `state.missing_slots`, `state.query` |
| **输出** | `clarify_question`, `answer`（与 clarify_question 相同，供前端展示），`messages` |
| **实现** | 模板生成，无需 LLM 调用；省份缺失→「请问您是哪个省份的考生？」 |

---

#### `node/fallback.py`（新）
**职责**：`out_of_scope` 时返回固定引导话术，不调用检索或生成模型。

| | 说明 |
|-|------|
| **输入** | `state.intent`, `state.query` |
| **输出** | `answer`（固定话术），`messages` |
| **实现** | 纯模板，无 LLM 调用；返回「您好，我是南科大招生咨询助手，目前只能回答招生相关问题。如需了解招生信息，欢迎继续提问！招办联系方式：……」 |

---

#### `node/direct_generate.py`（新）
**职责**：`other` 意图（如打招呼、感谢）直接生成回复，无 RAG。

| | 说明 |
|-|------|
| **输入** | `state.query`, `state.messages` |
| **输出** | `answer`, `messages`, `retrieval_skipped=True` |
| **实现** | 调用生成模型，使用「招生助手」角色 prompt，简短礼貌回复 |

---

#### `node/generation.py`
**职责**：接收 RAG 结果，按意图使用场景化 prompt 生成最终答案。

| | 说明 |
|-|------|
| **输入** | `query`, `intent`, `chunks`, `messages`, `retrieval_skipped` |
| **输出** | `answer`, `messages`, `citations` |
| **变更点** | 1) 中文 prompt；2) 按 intent 切换场景化规则；3) chunks 为空时走无检索 fallback 规则（禁止猜测数字/日期） |

五类意图的 prompt 分支（详见 `docs/architecture-review.md` 第四章）。

---

### 5.2 Agentic RAG 子图节点

#### `agentic_rag/node/search_planner.py`（新）
**职责**：结合对话历史、当前意图、已有槽位，决定本轮检索策略。

| | 说明 |
|-|------|
| **输入** | `query`, `intent`, `slots`, `rag_iteration`, 上轮 `eval_reason`（重试时提供） |
| **输出** | `search_plan`（strategy, vector_query, structured_filters, top_k） |
| **模型** | 同 `intent_model_id` 或专用小模型，JSON 模式 |
| **关键逻辑** | 第一次：意图为 admission_policy 且有 province→ 优先 structured；无 province → 先 vector；重试时：根据上轮 eval_reason 改写 query 或换策略 |

示例输出：
```json
{
  "strategy": "hybrid",
  "vector_query": "浙江综合评价招生分数线要求",
  "structured_filters": {"province": "浙江", "year": "2025"},
  "top_k": 8
}
```

---

#### `agentic_rag/node/vector_search.py`
**职责**：按 `search_plan.vector_query` 查 Milvus 向量库，按 intent 选择对应 collection。

| | 说明 |
|-|------|
| **输入** | `search_plan`, `intent` |
| **输出** | `vector_chunks` |
| **变更点** | 从原 `vector_retrieve.py` 迁移；collection 通过 `INTENT_COLLECTION_MAP` 查找；支持 `top_k` 动态配置 |

---

#### `agentic_rag/node/structured_search.py`（新）
**职责**：对强事实类查询（省份分数线、时间节点、学费等）做元数据过滤检索。

| | 说明 |
|-|------|
| **输入** | `search_plan.structured_filters`, `intent` |
| **输出** | `structured_results`（dict 列表，含 content, metadata） |
| **实现** | 调用 Milvus 的 `expr` 元数据过滤；如 `province == "浙江" AND year == "2025"` |
| **依赖** | chunk 导入时需要携带 `province`, `year`, `source_type` 等元数据字段 |

---

#### `agentic_rag/node/rerank.py`
**职责**：合并向量检索和结构化检索结果，调用 Jina 重排序，输出最终 `chunks`。

| | 说明 |
|-|------|
| **输入** | `vector_chunks`, `structured_results`, `search_plan.top_k` |
| **输出** | `chunks`（合并重排后，截取 top_n） |
| **变更点** | 参数从硬编码改为从 config/env 读取；支持空输入短路（直接返回） |

配置项（移至 `config.py`）：
```python
RERANK_MODEL_ID: str = os.getenv("RERANK_MODEL_ID", "jina-reranker")
RERANK_TOP_N: int = int(os.getenv("RERANK_TOP_N", "5"))
```

---

#### `agentic_rag/node/sufficiency_eval.py`（新）
**职责**：评估本轮检索结果能否回答用户问题，给出三选一判断。

| | 说明 |
|-|------|
| **输入** | `query`, `intent`, `slots`, `chunks`, `rag_iteration` |
| **输出** | `eval_result`（sufficient/missing_slots/insufficient_docs），`missing_slots`，`eval_reason` |
| **模型** | 同 intent_model_id，JSON 模式 |
| **判断逻辑** | sufficient：检索到≥1条高相关文档，且无明显缺失信息；missing_slots：检索到的文档涉及多省份或需要省份才能精确回答，但 slots 中无 province；insufficient_docs：检索结果与问题相关性低或内容为空 |

示例输出：
```json
{
  "eval_result": "missing_slots",
  "missing_slots": ["province"],
  "eval_reason": "问题涉及录取分数线，但未指定省份，无法给出精确答案"
}
```

---

## 六、顶层图 config.py 变更

```python
# src/config.py 新增内容

# 置信度阈值
CONFIDENCE_THRESHOLD: float = float(os.getenv("INTENT_CONFIDENCE_THRESHOLD", "0.55"))

# Agentic RAG 最大重试次数
RAG_MAX_ITERATIONS: int = int(os.getenv("RAG_MAX_ITERATIONS", "2"))

# 各意图的必要槽位
REQUIRED_SLOTS_BY_INTENT: dict[str, list[str]] = {
    IntentType.ADMISSION_POLICY.value: ["province"],
    IntentType.SCHOOL_OVERVIEW.value: [],
    IntentType.MAJOR_AND_TRAINING.value: [],
    IntentType.CAREER_AND_DEVELOPMENT.value: [],
    IntentType.CAMPUS_LIFE.value: [],
}

# 各意图对应的 Milvus collection（补齐后）
INTENT_COLLECTION_MAP: dict[str, str] = {
    IntentType.SCHOOL_OVERVIEW.value: "school_overview",
    IntentType.ADMISSION_POLICY.value: "admission_policy",
    IntentType.MAJOR_AND_TRAINING.value: "majors_and_training",
    IntentType.CAREER_AND_DEVELOPMENT.value: "career_and_development",  # 待补数据
    IntentType.CAMPUS_LIFE.value: "campus_life",                        # 待补数据
}

# 重排序配置（从硬编码移至此处）
RERANK_MODEL_ID: str = os.getenv("RERANK_MODEL_ID", "jina-reranker")
RERANK_TOP_N: int = int(os.getenv("RERANK_TOP_N", "5"))
```

---

## 七、runtime 层适配

### 7.1 STAGE_ORDER 更新

`graph_runtime.py` 中 `STAGE_ORDER` 需要适配新节点名：

```python
# 旧
STAGE_ORDER = ("intent", "retrieve", "rerank", "generate")

# 新
STAGE_ORDER = (
    "intent_classify",      # 意图识别
    "agentic_rag",          # RAG 子图（前端显示为「正在检索」）
    "generate",             # 生成
    # 以下为终止分支，不在主流程 STAGE_ORDER 中，但需要 stream_stage_events 识别
    "slot_ask",
    "fallback",
    "direct_generate",
)
```

### 7.2 stream_stage_events 事件适配

子图内部节点（`search_planner`, `vector_search`, `rerank`, `sufficiency_eval`）对外暴露为 `agentic_rag` 这一个阶段，前端只看到「正在检索知识库」，不感知子图内部轮数。

如需向前端暴露 RAG 循环进度，可在 `agentic_rag/graph.py` 中定义 `on_node_start` 回调，通过 `ui` 字段传递。

### 7.3 RuntimeConfig 新增字段

```python
@dataclass(slots=True)
class RuntimeConfig:
    repo_root: Path
    env_file: Path
    runtime_name: str = "chat-api"
    vector_top_k: int = 5
    checkpoint_path: Path | None = None
    # 新增
    rag_max_iterations: int = 2
    intent_confidence_threshold: float = 0.55
```

---

## 八、数据层要求（与 agentic_rag 联动）

结构化检索依赖 chunk 元数据规范，导入时需携带以下字段：

| 元数据字段 | 类型 | 示例 | 适用意图 |
|-----------|------|------|---------|
| `year` | str | `"2025"` | admission_policy |
| `province` | str | `"浙江"` | admission_policy |
| `source_type` | str | `"招生简章"` / `"问答"` | 全部 |
| `doc_title` | str | `"南科大2025浙江综评简章"` | 全部（引用溯源用） |
| `data_domain` | str | `"admission_policy"` | 全部 |

示例导入命令：
```bash
python -m app.scripts.ingest_file \
  --file "data/admission_policy/南科大2025浙江综评简章.docx" \
  --index "admission_policy" \
  --metadata '{"year":"2025","province":"浙江","source_type":"招生简章","data_domain":"admission_policy"}'
```

---

## 九、迁移路线图

```
阶段 0（准备，不动现有代码）
├── 补充 career_and_development、campus_life 数据并导入
├── 为现有 admission_policy collection 的 chunk 补充 year/province 元数据
└── 确认 config.py 的 INTENT_COLLECTION_MAP 更新

阶段 1（最小可用，~1周）
├── schemas.py：新增 confidence / slots / missing_slots / citations
├── node/intent_classify.py：输出 confidence + slots（保持现有 intent 输出不变）
├── node/fallback.py：新建（模板，无 LLM）
├── node/slot_ask.py：新建（模板，无 LLM）
├── node/generation.py：改为场景化中文 prompt + 无检索时约束
└── graph.py：在现有线性流程基础上增加条件路由
    └── intent → [fallback | slot_ask | 原有 retrieve→rerank→generate]

阶段 2（Agentic RAG，~2周）
├── agentic_rag/ 模块全新建立
│   ├── schemas.py（RAGState）
│   ├── node/search_planner.py
│   ├── node/vector_search.py（从 vector_retrieve.py 迁移）
│   ├── node/structured_search.py（新建）
│   ├── node/rerank.py（从 node/rerank.py 迁移）
│   ├── node/sufficiency_eval.py（新建）
│   └── graph.py（子图编译）
├── graph.py：将 retrieve→rerank 替换为 agentic_rag 子图
└── runtime/graph_runtime.py：更新 STAGE_ORDER

阶段 3（完善，按资源排期）
├── direct_generate.py（other 意图，当前可由 fallback 暂代）
├── citations 字段传递到前端
└── 结构化检索 Milvus expr 过滤完整支持
```

---

## 十、文件变更速查

| 文件 | 操作 | 说明 |
|------|------|------|
| `src/schemas.py` | 修改 | 新增 6 个字段 |
| `src/config.py` | 修改 | 新增常量、补齐 collection 映射、移入 rerank 配置 |
| `src/graph.py` | 重写 | 线性边→条件边，接入 agentic_rag 子图 |
| `src/node/intent_classify.py` | 重命名+修改 | 原 intend_clasaify.py，新增 slots 输出 |
| `src/node/generation.py` | 修改 | 场景化 prompt，无检索约束 |
| `src/node/fallback.py` | 新建 | 兜底话术，无 LLM |
| `src/node/slot_ask.py` | 新建 | 反问用户，无 LLM |
| `src/node/direct_generate.py` | 新建 | other 意图直接生成 |
| `src/agentic_rag/` | 新建目录 | 全部子图文件 |
| `src/runtime/graph_runtime.py` | 修改 | STAGE_ORDER，RuntimeConfig |
| `src/node/vector_retrieve.py` | 删除 | 功能迁移至 agentic_rag/node/vector_search.py |
| `src/node/rerank.py` | 删除 | 功能迁移至 agentic_rag/node/rerank.py |
