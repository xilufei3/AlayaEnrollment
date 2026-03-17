# Project Model Provider Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Replace project usage of AlayaFlow model registration with a local per-kind singleton model provider.

**Architecture:** Add a local configuration-driven provider that builds concrete model clients directly and caches them per model kind. Migrate project nodes and runtime bootstrap to use the provider instead of AlayaFlow registration while preserving existing node behavior.

**Tech Stack:** Python, LangChain `ChatOpenAI`, LangChain community `JinaRerank`, pytest

---

### Task 1: Add provider tests

**Files:**
- Create: `tests/src/node/test_model_provider.py`

**Step 1: Write the failing test**

Add tests for:
- same kind returns same instance
- different kinds return different instances
- generation kind includes disable-thinking `extra_body`
- rerank kind can be requested with overridden `top_n`

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/src/node/test_model_provider.py -v`
Expected: FAIL because provider module does not exist yet.

**Step 3: Write minimal implementation**

Create provider/config modules with the smallest API needed by the tests.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/src/node/test_model_provider.py -v`
Expected: PASS

### Task 2: Migrate project nodes to provider

**Files:**
- Create: `src/node/model_provider.py`
- Modify: `src/node/model_config.py`
- Modify: `src/node/intent_classify.py`
- Modify: `src/node/generation.py`
- Modify: `src/agentic_rag/node/search_planner.py`
- Modify: `src/agentic_rag/node/sufficiency_eval.py`
- Modify: `src/agentic_rag/node/rerank.py`

**Step 1: Write the failing test**

Add or extend tests to exercise provider lookup from representative node-facing code paths where practical.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/src/node/test_model_provider.py tests/src/node/test_intent_classify_slots.py -v`
Expected: FAIL until imports and call sites are updated.

**Step 3: Write minimal implementation**

Replace `ModelManager` lookups with local provider calls while preserving prompts and return values.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/src/node/test_model_provider.py tests/src/node/test_intent_classify_slots.py -v`
Expected: PASS

### Task 3: Remove runtime dependency on model registration

**Files:**
- Modify: `src/runtime/graph_runtime.py`
- Modify: `src/graph.py`
- Modify: `src/node/runtime_resources.py`

**Step 1: Write the failing test**

Add a focused regression test for graph/runtime setup only if needed; otherwise rely on import-level verification and existing focused tests.

**Step 2: Run test to verify it fails**

Run the focused runtime-related test command if added, or proceed after confirming outdated imports remain.

**Step 3: Write minimal implementation**

Remove project dependency on returned model IDs and keep only runtime directory/bootstrap responsibilities that are still needed.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/src/node/test_model_provider.py tests/src/node/test_intent_classify_slots.py -v`
Expected: PASS

### Task 4: Verify rerank integration

**Files:**
- Modify: `tests/src/node/test_model_provider.py`
- Optionally modify: `src/agentic_rag/node/rerank.py`

**Step 1: Write the failing test**

Add a focused rerank-provider assertion covering `top_n` override behavior.

**Step 2: Run test to verify it fails**

Run: `python -m pytest tests/src/node/test_model_provider.py -v`
Expected: FAIL until rerank provider supports override behavior.

**Step 3: Write minimal implementation**

Support override-aware rerank retrieval without breaking singleton-by-kind defaults.

**Step 4: Run test to verify it passes**

Run: `python -m pytest tests/src/node/test_model_provider.py -v`
Expected: PASS
