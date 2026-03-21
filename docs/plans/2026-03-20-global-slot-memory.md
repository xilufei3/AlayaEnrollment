# Global Slot Memory Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `province` and `year` the only global slots, update them with the latest user-provided values, ask follow-up questions only when the current query truly depends on them, and prevent remembered exact years from overriding range-style queries.

**Architecture:** Keep slot extraction inside `intent_classify`, but add query-aware `required_slots` to state so later graph nodes can decide whether a missing slot actually matters for the current turn. Propagate that state into Agentic RAG and make SQL year usage query-aware so remembered exact years are ignored for range-style queries such as `近几年` and `历年`.

**Tech Stack:** Python, LangGraph, Pydantic, pytest

---

### Task 1: Add failing tests for intent classification helpers

**Files:**
- Create: `tests/graph/node/test_intent_classify_slots.py`
- Modify: `src/graph/node/intent_classify.py`

**Step 1: Write the failing test**

```python
def test_normalize_slots_keeps_only_province_and_year():
    assert normalize_slots({"province": "广东", "year": "2025", "major": "人工智能"}) == {
        "province": "广东",
        "year": "2025",
    }
```

Add tests for:

- filtering unknown slot keys
- ignoring blank values
- computing `missing_slots` from query-aware `required_slots` rather than intent defaults

**Step 2: Run test to verify it fails**

Run: `pytest tests/graph/node/test_intent_classify_slots.py -q`

Expected: FAIL because helper/functions do not exist yet or existing logic uses intent-level defaults.

**Step 3: Write minimal implementation**

Implement minimal helpers in `src/graph/node/intent_classify.py`:

- slot filtering for `province/year`
- query-aware missing-slot calculation

**Step 4: Run test to verify it passes**

Run: `pytest tests/graph/node/test_intent_classify_slots.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/graph/node/test_intent_classify_slots.py src/graph/node/intent_classify.py
git commit -m "test: cover fixed global slot helpers"
```

### Task 2: Add failing tests for query-aware sufficiency evaluation

**Files:**
- Create: `tests/graph/agentic_rag/test_sufficiency_eval_required_slots.py`
- Modify: `src/graph/agentic_rag/node/sufficiency_eval.py`
- Modify: `src/graph/agentic_rag/schemas.py`
- Modify: `src/graph/agentic_rag/graph.py`
- Modify: `src/graph/state.py`

**Step 1: Write the failing test**

```python
def test_sufficiency_eval_only_requests_slots_needed_by_current_query():
    result = node({
        "query": "631是什么意思",
        "intent": "admission_policy",
        "slots": {},
        "required_slots": [],
        "chunks": [Document(page_content="631 是综合评价模式。")],
    })
    assert result["missing_slots"] == []
```

Add a second test for:

- `今年分数线多少` with `required_slots=["province"]` and no province -> returns `["province"]`

**Step 2: Run test to verify it fails**

Run: `pytest tests/graph/agentic_rag/test_sufficiency_eval_required_slots.py -q`

Expected: FAIL because current sufficiency eval uses `REQUIRED_SLOTS_BY_INTENT`.

**Step 3: Write minimal implementation**

Update state/schemas and sufficiency evaluator to read `required_slots`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/graph/agentic_rag/test_sufficiency_eval_required_slots.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/graph/agentic_rag/test_sufficiency_eval_required_slots.py src/graph/agentic_rag/node/sufficiency_eval.py src/graph/agentic_rag/schemas.py src/graph/agentic_rag/graph.py src/graph/state.py
git commit -m "feat: make slot follow-up query aware"
```

### Task 3: Add failing tests for range-style query year behavior

**Files:**
- Modify: `tests/graph/agentic_rag/test_sql_query_node.py`
- Modify: `tests/graph/agentic_rag/test_search_planner_sql_plan.py`
- Modify: `src/graph/agentic_rag/node/search_planner.py`
- Modify: `src/graph/agentic_rag/node/sql_query.py`

**Step 1: Write the failing test**

```python
def test_sql_query_does_not_apply_remembered_exact_year_for_recent_years_query():
    result = node({
        "query": "近几年录取情况",
        "intent": "admission_policy",
        "slots": {"province": "广东", "year": "2025"},
        "sql_plan": {"enabled": True},
    })
    assert captured["year"] is None
```

Add a paired test showing:

- an exact-year query may still apply `year`

**Step 2: Run test to verify it fails**

Run: `pytest tests/graph/agentic_rag/test_sql_query_node.py tests/graph/agentic_rag/test_search_planner_sql_plan.py -q`

Expected: FAIL because current SQL query always falls back to remembered `slots.year`.

**Step 3: Write minimal implementation**

Implement a small query-aware helper and pass through any needed planner metadata.

**Step 4: Run test to verify it passes**

Run: `pytest tests/graph/agentic_rag/test_sql_query_node.py tests/graph/agentic_rag/test_search_planner_sql_plan.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add tests/graph/agentic_rag/test_sql_query_node.py tests/graph/agentic_rag/test_search_planner_sql_plan.py src/graph/agentic_rag/node/search_planner.py src/graph/agentic_rag/node/sql_query.py
git commit -m "fix: keep remembered year from overriding range queries"
```

### Task 4: Wire prompt/model output for fixed slots and query-aware requirements

**Files:**
- Modify: `src/graph/prompts.py`
- Modify: `src/graph/node/intent_classify.py`
- Modify: `tests/graph/test_prompts.py`

**Step 1: Write the failing test**

```python
def test_intent_classifier_prompt_mentions_only_province_and_year_slots():
    assert "province" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
    assert "year" in INTENT_CLASSIFIER_SYSTEM_PROMPT_TEMPLATE
```

Add assertions for:

- prompt instructs model to return query-aware required slots
- tests still match exported prompt constants

**Step 2: Run test to verify it fails**

Run: `pytest tests/graph/test_prompts.py -q`

Expected: FAIL if prompt text or output contract has not been updated.

**Step 3: Write minimal implementation**

Update prompt contract and parsing model in `intent_classify.py`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/graph/test_prompts.py -q`

Expected: PASS

**Step 5: Commit**

```bash
git add src/graph/prompts.py src/graph/node/intent_classify.py tests/graph/test_prompts.py
git commit -m "feat: tighten slot extraction prompt contract"
```

### Task 5: Run focused verification

**Files:**
- Modify: none
- Test: `tests/graph/node/test_intent_classify_slots.py`
- Test: `tests/graph/agentic_rag/test_sufficiency_eval_required_slots.py`
- Test: `tests/graph/agentic_rag/test_sql_query_node.py`
- Test: `tests/graph/agentic_rag/test_search_planner_sql_plan.py`
- Test: `tests/graph/test_prompts.py`

**Step 1: Run the focused suite**

Run:

```bash
pytest tests/graph/node/test_intent_classify_slots.py tests/graph/agentic_rag/test_sufficiency_eval_required_slots.py tests/graph/agentic_rag/test_sql_query_node.py tests/graph/agentic_rag/test_search_planner_sql_plan.py tests/graph/test_prompts.py -q
```

Expected: PASS

**Step 2: Inspect for regressions**

Check that:

- `missing_slots` is empty for query-irrelevant slot cases
- `generation` can still receive `missing_slots` with chunks present
- range queries do not silently inherit remembered exact year

**Step 3: Commit**

```bash
git add src/graph tests/graph
git commit -m "feat: make global slot memory query aware"
```
