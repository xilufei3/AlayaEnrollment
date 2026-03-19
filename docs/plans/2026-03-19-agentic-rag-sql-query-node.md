# Agentic RAG SQL Query Node Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a SQL query branch inside `agentic_rag` so `admission_policy` questions can use both vector retrieval and structured SQL evidence before generation.

**Architecture:** Keep the top-level graph unchanged and extend the `agentic_rag` subgraph with a parallel `sql_query` branch. `search_planner` will emit both `search_plan` and `sql_plan`; `retrieval` and `sql_query` will run in parallel; `merge_context` will concatenate `structured_chunks` and `vector_chunks` into final `chunks` before rerank and sufficiency evaluation.

**Tech Stack:** Python, LangGraph, LangChain Core `Document`, SQLAlchemy, SQLite, pytest

---

### Task 1: Extend Graph State For SQL Planning And Results

**Files:**
- Modify: `src/graph/agentic_rag/schemas.py`
- Modify: `src/graph/state.py`
- Test: `tests/graph/agentic_rag/test_sql_state_schema.py`

**Step 1: Write the failing test**

```python
from typing import get_type_hints

from src.graph.agentic_rag.schemas import RAGState
from src.graph.state import WorkflowState


def test_rag_and_workflow_state_expose_structured_sql_fields():
    rag_hints = get_type_hints(RAGState, include_extras=True)
    workflow_hints = get_type_hints(WorkflowState, include_extras=True)

    assert "sql_plan" in rag_hints
    assert "structured_chunks" in rag_hints
    assert "structured_results" in rag_hints
    assert "structured_results" in workflow_hints
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/graph/agentic_rag/test_sql_state_schema.py -v
```

Expected:

- FAIL because the state types do not expose the new SQL planning/result fields yet

**Step 3: Write minimal implementation**

Update `src/graph/agentic_rag/schemas.py`:

- add a `SQLPlan` typed dict with:
  - `enabled: bool`
  - `province: str`
  - `year: str`
  - `limit: int`
  - `reason: str`
- add `sql_plan: SQLPlan`
- add `structured_chunks: list[Document]`

Update `src/graph/state.py`:

- add `structured_results: list[dict[str, Any]]`

Keep the rest of the state untouched.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/graph/agentic_rag/test_sql_state_schema.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/graph/agentic_rag/test_sql_state_schema.py src/graph/agentic_rag/schemas.py src/graph/state.py
git commit -m "feat: add SQL planning and result state fields"
```

### Task 2: Teach Search Planner To Emit `sql_plan`

**Files:**
- Modify: `src/graph/agentic_rag/node/search_planner.py`
- Test: `tests/graph/agentic_rag/test_search_planner_sql_plan.py`

**Step 1: Write the failing test**

```python
from src.graph.agentic_rag.node.search_planner import create_search_planner_node


def test_search_planner_returns_sql_plan_fields():
    node = create_search_planner_node()
    result = node(
        {
            "query": "广东 2024 录取分数线是多少",
            "intent": "admission_policy",
            "slots": {"province": "广东", "year": "2024"},
            "rag_iteration": 0,
            "eval_reason": "",
        }
    )

    assert "search_plan" in result
    assert "sql_plan" in result
    assert "enabled" in result["sql_plan"]
    assert "limit" in result["sql_plan"]
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/graph/agentic_rag/test_search_planner_sql_plan.py -v
```

Expected:

- FAIL because the planner currently only emits `search_plan`

**Step 3: Write minimal implementation**

Extend `src/graph/agentic_rag/node/search_planner.py` so planner output includes:

```python
{
    "enabled": intent == "admission_policy",
    "province": slots.get("province", ""),
    "year": slots.get("year", ""),
    "limit": 6,
    "reason": "..."
}
```

Then refine the planner prompt/LLM parsing so:

- `enabled` and `reason` are mandatory
- `province/year` are optional override fields
- when omitted, downstream code will fall back to `slots`

Keep the current vector search planning behavior unchanged.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/graph/agentic_rag/test_search_planner_sql_plan.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/graph/agentic_rag/test_search_planner_sql_plan.py src/graph/agentic_rag/node/search_planner.py
git commit -m "feat: extend search planner with sql plan"
```

### Task 3: Add SQL Query Node

**Files:**
- Create: `src/graph/agentic_rag/node/sql_query.py`
- Test: `tests/graph/agentic_rag/test_sql_query_node.py`

**Step 1: Write the failing test**

```python
from src.graph.agentic_rag.node.sql_query import create_sql_query_node


def test_sql_query_node_uses_sql_plan_then_falls_back_to_slots(monkeypatch):
    captured = {}

    def fake_query_admission_scores(*, province=None, year=None, limit=20):
        captured["province"] = province
        captured["year"] = year
        captured["limit"] = limit
        return [{"province": province, "year": year, "max_score": "660"}]

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_query.query_admission_scores",
        fake_query_admission_scores,
    )

    node = create_sql_query_node()
    result = node(
        {
            "intent": "admission_policy",
            "slots": {"province": "广东", "year": "2024"},
            "sql_plan": {"enabled": True, "province": "", "year": "", "limit": 6, "reason": "need sql"},
        }
    )

    assert captured == {"province": "广东", "year": "2024", "limit": 6}
    assert result["structured_results"][0]["province"] == "广东"
    assert len(result["structured_chunks"]) == 1
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/graph/agentic_rag/test_sql_query_node.py -v
```

Expected:

- FAIL because `sql_query.py` does not exist yet

**Step 3: Write minimal implementation**

Create `src/graph/agentic_rag/node/sql_query.py` with:

- a `create_sql_query_node()` factory
- `intent != "admission_policy"` returns empty SQL outputs
- `sql_plan.enabled` controls whether SQL runs
- final parameters resolve as:

```python
resolved_province = sql_plan.get("province") or slots.get("province") or None
resolved_year = sql_plan.get("year") or slots.get("year") or None
resolved_limit = int(sql_plan.get("limit") or 6)
```

- call:

```python
query_admission_scores(
    province=resolved_province,
    year=resolved_year,
    limit=resolved_limit,
)
```

- convert rows into `Document` entries in `structured_chunks`
- on SQL failure, log and return empty results instead of raising

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/graph/agentic_rag/test_sql_query_node.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/graph/agentic_rag/test_sql_query_node.py src/graph/agentic_rag/node/sql_query.py
git commit -m "feat: add agentic rag sql query node"
```

### Task 4: Add Merge Context Node

**Files:**
- Create: `src/graph/agentic_rag/node/merge_context.py`
- Modify: `src/graph/agentic_rag/node/retrieval.py`
- Test: `tests/graph/agentic_rag/test_merge_context.py`

**Step 1: Write the failing test**

```python
from langchain_core.documents import Document

from src.graph.agentic_rag.node.merge_context import create_merge_context_node


def test_merge_context_concatenates_structured_then_vector_chunks():
    node = create_merge_context_node()
    result = node(
        {
            "structured_chunks": [Document(page_content="sql-1")],
            "vector_chunks": [Document(page_content="vec-1"), Document(page_content="vec-2")],
        }
    )

    assert [doc.page_content for doc in result["chunks"]] == ["sql-1", "vec-1", "vec-2"]
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/graph/agentic_rag/test_merge_context.py -v
```

Expected:

- FAIL because the merge node does not exist yet

**Step 3: Write minimal implementation**

Create `src/graph/agentic_rag/node/merge_context.py` with:

```python
def create_merge_context_node():
    def merge_context_node(state):
        structured_chunks = list(state.get("structured_chunks") or [])
        vector_chunks = list(state.get("vector_chunks") or [])
        return {"chunks": structured_chunks + vector_chunks}
    return merge_context_node
```

Update `src/graph/agentic_rag/node/retrieval.py` so it no longer writes `chunks`, only `vector_chunks`.

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/graph/agentic_rag/test_merge_context.py -v
```

Then run:

```bash
pytest tests/graph/agentic_rag/test_sql_query_node.py tests/graph/agentic_rag/test_merge_context.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/graph/agentic_rag/test_merge_context.py src/graph/agentic_rag/node/merge_context.py src/graph/agentic_rag/node/retrieval.py
git commit -m "feat: merge structured and vector retrieval context"
```

### Task 5: Rewire Agentic RAG Subgraph

**Files:**
- Modify: `src/graph/agentic_rag/graph.py`
- Test: `tests/graph/agentic_rag/test_rag_graph_sql_branch.py`

**Step 1: Write the failing test**

```python
from src.graph.agentic_rag.graph import create_agentic_rag_node


def test_agentic_rag_returns_chunks_and_structured_results():
    class FakeRetriever:
        def search(self, **kwargs):
            return []

    node = create_agentic_rag_node(retriever=FakeRetriever())
    result = node(
        {
            "query": "广东录取分数线",
            "intent": "admission_policy",
            "slots": {"province": "广东"},
        }
    )

    assert "chunks" in result
    assert "missing_slots" in result
    assert "structured_results" in result
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/graph/agentic_rag/test_rag_graph_sql_branch.py -v
```

Expected:

- FAIL because the subgraph does not yet expose `structured_results`

**Step 3: Write minimal implementation**

Update `src/graph/agentic_rag/graph.py` to:

- register new nodes:
  - `sql_query`
  - `merge_context`
- wire edges:

```python
START -> search_planner
search_planner -> retrieval
search_planner -> sql_query
retrieval -> merge_context
sql_query -> merge_context
merge_context -> rerank
rerank -> eval
```

- seed subgraph input with:
  - `vector_chunks=[]`
  - `structured_results=[]`
  - `structured_chunks=[]`
- return top-level outputs:
  - `chunks`
  - `missing_slots`
  - `structured_results`

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/graph/agentic_rag/test_rag_graph_sql_branch.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/graph/agentic_rag/test_rag_graph_sql_branch.py src/graph/agentic_rag/graph.py
git commit -m "feat: add sql branch to agentic rag graph"
```

### Task 6: Surface Structured Results To Generation

**Files:**
- Modify: `src/graph/node/generation.py`
- Test: `tests/graph/node/test_generation_structured_results.py`

**Step 1: Write the failing test**

```python
from src.graph.node.generation import GenerationComponent


def test_generation_can_render_structured_result_summary():
    rows = [{"province": "广东", "year": 2024, "max_score": "660", "min_score": "640"}]
    text = GenerationComponent._structured_results_text(rows)

    assert "广东" in text
    assert "2024" in text
    assert "660" in text
```

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/graph/node/test_generation_structured_results.py -v
```

Expected:

- FAIL because generation has no structured result rendering helper yet

**Step 3: Write minimal implementation**

Update `src/graph/node/generation.py`:

- add a helper that formats a small structured-results block
- when `state["structured_results"]` is present, append the formatted block to the prompt context
- keep the existing `chunks`-driven generation path intact

Suggested helper:

```python
@staticmethod
def _structured_results_text(rows):
    lines = []
    for i, row in enumerate(rows[:6], start=1):
        lines.append(f"[SQL {i}] {row}")
    return "\n".join(lines)
```

**Step 4: Run test to verify it passes**

Run:

```bash
pytest tests/graph/node/test_generation_structured_results.py -v
```

Expected:

- PASS

**Step 5: Commit**

```bash
git add tests/graph/node/test_generation_structured_results.py src/graph/node/generation.py
git commit -m "feat: include structured sql results in generation context"
```

### Task 7: Full Verification

**Files:**
- Test: `tests/graph/agentic_rag/test_sql_state_schema.py`
- Test: `tests/graph/agentic_rag/test_search_planner_sql_plan.py`
- Test: `tests/graph/agentic_rag/test_sql_query_node.py`
- Test: `tests/graph/agentic_rag/test_merge_context.py`
- Test: `tests/graph/agentic_rag/test_rag_graph_sql_branch.py`
- Test: `tests/graph/node/test_generation_structured_results.py`

**Step 1: Run targeted graph tests**

Run:

```bash
pytest tests/graph/agentic_rag/test_sql_state_schema.py tests/graph/agentic_rag/test_search_planner_sql_plan.py tests/graph/agentic_rag/test_sql_query_node.py tests/graph/agentic_rag/test_merge_context.py tests/graph/agentic_rag/test_rag_graph_sql_branch.py tests/graph/node/test_generation_structured_results.py -v
```

Expected:

- PASS

**Step 2: Run any broader graph suite that exists**

Run:

```bash
pytest tests/graph -v
```

Expected:

- PASS, or document pre-existing failures if they are unrelated

**Step 3: Manual smoke test**

Use a representative state for:

- `admission_policy` with `province/year`
- `admission_policy` with only `province`
- `admission_policy` with neither slot but `sql_plan.enabled=True`

Confirm:

- SQL branch runs
- vector branch runs
- `merge_context` concatenates both
- `generate` sees combined evidence

**Step 4: Commit**

```bash
git add tests/graph
git commit -m "test: verify sql and rag merged retrieval flow"
```
