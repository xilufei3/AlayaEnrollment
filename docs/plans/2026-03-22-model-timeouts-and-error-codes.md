# Model Timeouts And Error Codes Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add explicit per-model timeout and retry budgets, then normalize timeout failures into a single outward-facing API error code.

**Architecture:** Extend `src/graph/llm.py` so each model kind carries explicit timeout and retry settings and returns timeout-aware wrappers for both chat models and rerankers. Update API streaming error payloads in `src/api/chat_app.py` so timeout failures use one business code with subtype metadata, while keeping non-timeout errors unchanged.

**Tech Stack:** FastAPI, LangChain `ChatOpenAI`, LangChain community `JinaRerank`, pytest

---

### Task 1: Lock The Desired Timeout Behavior With Tests

**Files:**
- Modify: `tests/api/test_chat_app_device_id.py`
- Create: `tests/graph/test_llm_timeouts.py`

**Step 1: Write failing tests**

- Add graph-layer tests that assert `build_model_configs()` exposes separate timeout / retry budgets for `generation`, `intent`, `eval`, and `rerank`.
- Add graph-layer tests that assert chat-model timeout wrappers normalize timeout exceptions into one custom timeout exception type.
- Add API tests that assert stream idle / max duration timeout events now use one business code with distinct subtype metadata.

**Step 2: Run tests to verify they fail**

Run: `pytest tests/graph/test_llm_timeouts.py tests/api/test_chat_app_device_id.py::test_runs_stream_emits_idle_timeout_error tests/api/test_chat_app_device_id.py::test_chat_stream_emits_max_duration_error -q`

**Step 3: Implement the minimal production code**

- Add timeout-aware model spec fields and wrappers in `src/graph/llm.py`.
- Update API timeout payload helpers in `src/api/chat_app.py`.

**Step 4: Re-run the same tests**

Run: `pytest tests/graph/test_llm_timeouts.py tests/api/test_chat_app_device_id.py::test_runs_stream_emits_idle_timeout_error tests/api/test_chat_app_device_id.py::test_chat_stream_emits_max_duration_error -q`

### Task 2: Wire Timeout Normalization Through The Runtime

**Files:**
- Modify: `src/graph/llm.py`
- Modify: `src/api/chat_app.py`

**Step 1: Add explicit model budgets**

- `generation`, `intent`, `eval`, and `rerank` each get independent timeout and retry defaults in `src/graph/llm.py`.
- `planner` can reuse a sensible explicit budget even if not directly requested, to keep config shape uniform.

**Step 2: Normalize timeout exceptions**

- Raise one custom timeout exception from chat-model wrappers and reranker wrappers.
- Map that exception to one outward-facing timeout error code in `src/api/chat_app.py`.

**Step 3: Keep subtype detail for diagnostics**

- Stream guard timeouts include a subtype such as `stream_idle_timeout` or `stream_max_duration`.
- Model-client timeouts include a subtype such as `model_generation_timeout` or `model_rerank_timeout`.

### Task 3: Verify End-To-End

**Files:**
- Modify: `src/graph/llm.py`
- Modify: `src/api/chat_app.py`
- Modify: `tests/api/test_chat_app_device_id.py`
- Create: `tests/graph/test_llm_timeouts.py`

**Step 1: Run focused tests**

Run: `pytest tests/graph/test_llm_timeouts.py tests/api/test_chat_app_device_id.py -q`

**Step 2: Run API suite**

Run: `pytest tests/api -q`

**Step 3: Run full test suite and report unrelated failures separately**

Run: `pytest -q`
