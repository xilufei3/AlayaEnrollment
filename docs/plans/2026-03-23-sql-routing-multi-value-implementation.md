# SQL Routing And Multi-Value Query Planning Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `search_planner` metadata-aware for SQL routing, add a dedicated `sql_plan_builder`, and extend the deterministic `admission_scores` execution path to support multiple provinces and multiple years.

**Architecture:** The planner will read table capabilities from `table_registry.yaml` and output a routing-only SQL candidate. A new `sql_plan_builder` node will transform the chosen table metadata into a lightweight list-based key plan, and the executor will deterministically compile that plan into the existing query helper layer without letting the model generate raw SQL.

**Tech Stack:** Python, LangGraph, LangChain document/message primitives, SQLite, pytest

---

### Task 1: Make `search_planner` SQL-metadata aware and route only data questions

**Files:**
- Modify: `src/graph/agentic_rag/schemas.py`
- Modify: `src/graph/agentic_rag/node/search_planner.py`
- Modify: `src/graph/prompts.py`
- Test: `tests/graph/agentic_rag/test_search_planner_sql_plan.py`

**Step 1: Write the failing tests**

Add tests that describe the new contract:

```python
def test_search_planner_includes_sql_registry_context(monkeypatch):
    captured = {}

    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            captured["messages"] = messages
            return {
                "rewritten_query": "广东 2024 录取分数",
                "reason": "ok",
                "sql_candidate": {
                    "enabled": True,
                    "selected_tables": ["admission_scores"],
                    "reason": "分数数据查询",
                },
            }

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.search_planner.get_model",
        lambda _: DummyModel(),
    )

    node = create_search_planner_node(model_id="planner")
    result = asyncio.run(node({...}))

    user_message = captured["messages"][1][1]
    assert "admission_scores" in user_message
    assert "query_key" in user_message
    assert result["sql_candidate"]["selected_tables"] == ["admission_scores"]


def test_search_planner_disables_sql_for_rule_question_when_no_table_matches(monkeypatch):
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "rewritten_query": "综合评价 631 规则 含义",
                "reason": "ok",
                "sql_candidate": {
                    "enabled": False,
                    "selected_tables": [],
                    "reason": "规则解释问题",
                },
            }
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/graph/agentic_rag/test_search_planner_sql_plan.py -v`

Expected: FAIL because `sql_candidate` and registry-aware prompt content do not exist yet.

**Step 3: Write minimal implementation**

Update the planner to:

- add a new `SQLCandidate` TypedDict in `src/graph/agentic_rag/schemas.py`
- load registry metadata via `SQLManager`
- serialize a compact table summary into the planner prompt
- parse `sql_candidate` from model output
- default to `enabled=False` and `selected_tables=[]` on fallback

Suggested implementation shape:

```python
class SQLCandidate(TypedDict, total=False):
    enabled: bool
    selected_tables: list[str]
    reason: str


def _build_sql_registry_context() -> str:
    tables = SQLManager().get_all_table_meta()
    ...


return {
    "search_plan": plan,
    "sql_candidate": sql_candidate,
    "rag_iteration": iteration + 1,
}
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/graph/agentic_rag/test_search_planner_sql_plan.py -v`

Expected: PASS, including coverage for the new prompt content and rule-question routing behavior.

**Step 5: Commit**

```bash
git add src/graph/agentic_rag/schemas.py src/graph/agentic_rag/node/search_planner.py src/graph/prompts.py tests/graph/agentic_rag/test_search_planner_sql_plan.py
git commit -m "feat: make sql routing metadata-aware"
```

### Task 2: Add `sql_plan_builder` to convert selected table metadata into key lists

**Files:**
- Modify: `src/graph/agentic_rag/schemas.py`
- Create: `src/graph/agentic_rag/node/sql_plan_builder.py`
- Modify: `src/graph/agentic_rag/graph.py`
- Modify: `src/graph/prompts.py`
- Test: `tests/graph/agentic_rag/test_sql_plan_builder.py`

**Step 1: Write the failing test**

Create table-plan tests for single-value, multi-value, and unspecified-year behavior:

```python
def test_sql_plan_builder_extracts_multiple_provinces_and_years(monkeypatch):
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "admission_scores",
                        "key_values": {
                            "province": ["广东", "浙江"],
                            "year": ["2022", "2023", "2024"],
                        },
                        "reason": "compare",
                    }
                ],
                "limit": 6,
                "reason": "ok",
            }


def test_sql_plan_builder_leaves_year_empty_for_recent_years_query(monkeypatch):
    class DummyModel:
        async def ainvoke(self, messages, response_format=None):
            return {
                "enabled": True,
                "table_plans": [
                    {
                        "table": "admission_scores",
                        "key_values": {"province": ["广东"], "year": []},
                        "reason": "recent years",
                    }
                ],
                "limit": 6,
                "reason": "ok",
            }
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/graph/agentic_rag/test_sql_plan_builder.py -v`

Expected: FAIL because the node and state contract do not exist yet.

**Step 3: Write minimal implementation**

Create `src/graph/agentic_rag/node/sql_plan_builder.py` with:

- prompt input containing the user query, simple slots, selected tables, and per-table query keys
- strict JSON parsing
- normalization that only keeps registered query keys
- output format:

```python
{
    "sql_plan": {
        "enabled": True,
        "table_plans": [
            {
                "table": "admission_scores",
                "key_values": {
                    "province": ["广东", "浙江"],
                    "year": ["2022", "2023"],
                },
                "reason": "..."
            }
        ],
        "limit": 6,
        "reason": "..."
    }
}
```

Wire the graph so the flow becomes:

`search_planner -> retrieval/sql_plan_builder`

`sql_plan_builder -> sql_query`

**Step 4: Run test to verify it passes**

Run: `pytest tests/graph/agentic_rag/test_sql_plan_builder.py -v`

Expected: PASS, with stable list-based key extraction.

**Step 5: Commit**

```bash
git add src/graph/agentic_rag/schemas.py src/graph/agentic_rag/node/sql_plan_builder.py src/graph/agentic_rag/graph.py src/graph/prompts.py tests/graph/agentic_rag/test_sql_plan_builder.py
git commit -m "feat: add sql plan builder node"
```

### Task 3: Extend the deterministic SQL executor to accept multi-value province and year keys

**Files:**
- Modify: `src/graph/agentic_rag/node/sql_query.py`
- Modify: `src/knowledge/sql_queries.py`
- Test: `tests/graph/agentic_rag/test_sql_query_node.py`
- Create: `tests/knowledge/test_sql_queries.py`

**Step 1: Write the failing tests**

Update node tests so the executor forwards lists instead of single values:

```python
def test_sql_query_node_passes_multi_value_filters(monkeypatch):
    captured = {}

    def fake_query_admission_scores(*, provinces=None, years=None, limit=20):
        captured["provinces"] = provinces
        captured["years"] = years
        captured["limit"] = limit
        return [{"province": "广东", "year": 2024, "min_score": "640"}]

    monkeypatch.setattr(
        "src.graph.agentic_rag.node.sql_query.query_admission_scores",
        fake_query_admission_scores,
    )

    result = asyncio.run(node({
        "intent": "admission_policy",
        "sql_plan": {
            "enabled": True,
            "table_plans": [
                {
                    "table": "admission_scores",
                    "key_values": {
                        "province": ["广东", "浙江"],
                        "year": ["2023", "2024"],
                    },
                    "reason": "compare",
                }
            ],
            "limit": 6,
        },
    }))

    assert captured == {
        "provinces": ["广东", "浙江"],
        "years": ["2023", "2024"],
        "limit": 6,
    }
```

Add helper tests for empty-list behavior:

```python
def test_query_admission_scores_skips_year_filter_when_years_empty(...):
    rows = query_admission_scores(provinces=["广东"], years=[], limit=6)
    assert rows
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/graph/agentic_rag/test_sql_query_node.py tests/knowledge/test_sql_queries.py -v`

Expected: FAIL because the node still expects scalar `province/year` fields and the helper does not accept lists.

**Step 3: Write minimal implementation**

Update `sql_query.py` to:

- read `table_plans`
- locate the `admission_scores` plan
- normalize missing keys to empty lists
- call the helper with `provinces=[...]` and `years=[...]`

Update `sql_queries.py` to compile list filters with bound parameters:

```python
def query_admission_scores(*, provinces=None, years=None, limit=20):
    provinces = [p for p in provinces or [] if p]
    years = [int(y) for y in years or [] if str(y).strip()]
    ...
```

Keep the implementation deterministic and table-specific.

**Step 4: Run test to verify it passes**

Run: `pytest tests/graph/agentic_rag/test_sql_query_node.py tests/knowledge/test_sql_queries.py -v`

Expected: PASS, including empty-list behavior and list forwarding.

**Step 5: Commit**

```bash
git add src/graph/agentic_rag/node/sql_query.py src/knowledge/sql_queries.py tests/graph/agentic_rag/test_sql_query_node.py tests/knowledge/test_sql_queries.py
git commit -m "feat: support multi-value sql query keys"
```

### Task 4: Run focused end-to-end verification for the updated subgraph

**Files:**
- Reuse existing tests from:
  - `tests/graph/agentic_rag/test_search_planner_sql_plan.py`
  - `tests/graph/agentic_rag/test_sql_plan_builder.py`
  - `tests/graph/agentic_rag/test_sql_query_node.py`
  - `tests/knowledge/test_sql_queries.py`

**Step 1: Run the focused suite**

Run:

```bash
pytest tests/graph/agentic_rag/test_search_planner_sql_plan.py tests/graph/agentic_rag/test_sql_plan_builder.py tests/graph/agentic_rag/test_sql_query_node.py tests/knowledge/test_sql_queries.py -v
```

Expected: PASS

**Step 2: Run a broader regression slice**

Run:

```bash
pytest tests/graph/agentic_rag -v
```

Expected: PASS without regressions in merge, rerank, or sufficiency-eval behavior.

**Step 3: Commit the verification checkpoint**

```bash
git add -A
git commit -m "test: verify sql routing and multi-value query planning"
```

### Task 5: Optional follow-up after merge

**Files:**
- Modify later if needed: `src/config/table_registry.yaml`
- Modify later if needed: additional SQL helper files for new tables

**Step 1: Add new registered tables only after the first path is stable**

Use the same pattern:

- planner reads all registered table summaries
- planner selects candidate tables
- plan builder extracts only registered query keys
- executor dispatches to a whitelisted helper per table

**Step 2: Defer performance optimizations**

If repeated eval retries cause repeated SQL calls, add a later optimization to skip identical SQL plans across iterations. Do not add that in the first implementation unless tests or profiling show a concrete problem.
