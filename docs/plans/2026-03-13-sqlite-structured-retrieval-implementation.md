# SQLite Structured Retrieval Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add SQLite-backed structured retrieval as optional supplemental evidence while keeping semantic retrieval mandatory in the existing agentic RAG pipeline.

**Architecture:** Introduce a small structured retrieval module with import services, domain registry, SQL compiler, and SQLite repository. Extend the planner and RAG graph so semantic retrieval always runs first, then optionally run structured retrieval and fuse pseudo-documents into the existing downstream pipeline.

**Tech Stack:** Python, SQLite, LangGraph, TypedDict/Pydantic-style request models, existing Milvus-based retriever

---

### Task 1: Add structured module skeleton

**Files:**
- Create: `src/structured/__init__.py`
- Create: `src/structured/schemas.py`
- Create: `src/structured/domain_registry.py`
- Create: `src/structured/sqlite_repository.py`
- Create: `src/structured/sql_compiler.py`
- Create: `src/structured/import_service.py`
- Create: `src/structured/search_service.py`

**Step 1: Write the failing tests**

Create test file skeletons for registry lookup, SQL compilation, and row normalization.

**Step 2: Run test to verify it fails**

Run: `pytest tests/structured -v`
Expected: FAIL because the module and tests do not exist yet.

**Step 3: Write minimal implementation**

Create the module files with placeholder types and function signatures only.

**Step 4: Run test to verify import paths resolve**

Run: `pytest tests/structured -v`
Expected: FAIL on missing behavior, not missing imports.

**Step 5: Commit**

```bash
git add src/structured tests/structured
git commit -m "feat: scaffold structured retrieval module"
```

### Task 2: Define import and query schemas

**Files:**
- Modify: `src/structured/schemas.py`
- Test: `tests/structured/test_schemas.py`

**Step 1: Write the failing test**

Add tests that assert normalized request payloads support:

- `StructuredImportRequest`
- `StructuredImportRow`
- `StructuredSearchRequest`
- `StructuredRow`

**Step 2: Run test to verify it fails**

Run: `pytest tests/structured/test_schemas.py -v`
Expected: FAIL because the schema models are incomplete.

**Step 3: Write minimal implementation**

Define the request and result shapes in `src/structured/schemas.py`.

**Step 4: Run test to verify it passes**

Run: `pytest tests/structured/test_schemas.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/structured/schemas.py tests/structured/test_schemas.py
git commit -m "feat: define structured import and search schemas"
```

### Task 3: Implement domain registry

**Files:**
- Modify: `src/structured/domain_registry.py`
- Test: `tests/structured/test_domain_registry.py`

**Step 1: Write the failing test**

Test that:

- `admission_policy` is registered
- allowed filter/select/sort fields resolve correctly
- unknown domains raise a clear error

**Step 2: Run test to verify it fails**

Run: `pytest tests/structured/test_domain_registry.py -v`
Expected: FAIL because registry logic is missing.

**Step 3: Write minimal implementation**

Add a registry entry for `admission_policy` with:

- `table`
- `filterable_fields`
- `selectable_fields`
- `sortable_fields`
- `default_select`

**Step 4: Run test to verify it passes**

Run: `pytest tests/structured/test_domain_registry.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/structured/domain_registry.py tests/structured/test_domain_registry.py
git commit -m "feat: add structured domain registry"
```

### Task 4: Implement SQL compiler

**Files:**
- Modify: `src/structured/sql_compiler.py`
- Test: `tests/structured/test_sql_compiler.py`

**Step 1: Write the failing test**

Add tests for:

- valid equality filters
- valid sort and limit
- invalid field rejection
- unknown domain rejection

Include an assertion like:

```python
sql, params = compile_query(req)
assert "WHERE province = ?" in sql
assert params == ["浙江", 2025, 10]
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/structured/test_sql_compiler.py -v`
Expected: FAIL because compile logic is not implemented.

**Step 3: Write minimal implementation**

Implement:

- domain lookup
- allowlist validation
- parameterized SQL generation
- limit clamping

**Step 4: Run test to verify it passes**

Run: `pytest tests/structured/test_sql_compiler.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/structured/sql_compiler.py tests/structured/test_sql_compiler.py
git commit -m "feat: compile structured query requests to sqlite sql"
```

### Task 5: Add SQLite repository and schema bootstrap

**Files:**
- Modify: `src/structured/sqlite_repository.py`
- Create: `tests/structured/test_sqlite_repository.py`

**Step 1: Write the failing test**

Use a temporary SQLite database and test:

- schema bootstrap creates required tables
- insert or upsert writes rows
- search returns expected rows

**Step 2: Run test to verify it fails**

Run: `pytest tests/structured/test_sqlite_repository.py -v`
Expected: FAIL because repository behavior is missing.

**Step 3: Write minimal implementation**

Implement:

- SQLite connection management
- bootstrap DDL for import tables and `admission_policy_records`
- execution helpers for import and select queries

**Step 4: Run test to verify it passes**

Run: `pytest tests/structured/test_sqlite_repository.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/structured/sqlite_repository.py tests/structured/test_sqlite_repository.py
git commit -m "feat: add sqlite repository for structured retrieval"
```

### Task 6: Implement import service

**Files:**
- Modify: `src/structured/import_service.py`
- Create: `tests/structured/test_import_service.py`

**Step 1: Write the failing test**

Test:

- `preview` validates rows and reports counts
- `execute` writes import job metadata
- `execute` inserts or upserts fact rows
- invalid rows are tracked in job items

**Step 2: Run test to verify it fails**

Run: `pytest tests/structured/test_import_service.py -v`
Expected: FAIL because import service behavior is not implemented.

**Step 3: Write minimal implementation**

Implement:

- request validation
- import job creation
- preview stats
- execute with transaction handling

**Step 4: Run test to verify it passes**

Run: `pytest tests/structured/test_import_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/structured/import_service.py tests/structured/test_import_service.py
git commit -m "feat: implement structured import service"
```

### Task 7: Implement search service and pseudo-document formatting

**Files:**
- Modify: `src/structured/search_service.py`
- Create: `tests/structured/test_search_service.py`

**Step 1: Write the failing test**

Test that search results:

- are validated through compiler and repository
- return normalized rows
- can be transformed into pseudo-documents with expected metadata

**Step 2: Run test to verify it fails**

Run: `pytest tests/structured/test_search_service.py -v`
Expected: FAIL because search service behavior is missing.

**Step 3: Write minimal implementation**

Implement:

- search service composition
- row normalization
- pseudo-document conversion for downstream use

**Step 4: Run test to verify it passes**

Run: `pytest tests/structured/test_search_service.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/structured/search_service.py tests/structured/test_search_service.py
git commit -m "feat: implement structured search service"
```

### Task 8: Extend RAG schemas for optional structured query

**Files:**
- Modify: `src/agentic_rag/schemas.py`
- Create: `tests/agentic_rag/test_structured_search_plan.py`

**Step 1: Write the failing test**

Test that `SearchPlan` can carry:

- optional `structured_query`
- optional `needs_structured_search`

**Step 2: Run test to verify it fails**

Run: `pytest tests/agentic_rag/test_structured_search_plan.py -v`
Expected: FAIL because schema fields do not exist.

**Step 3: Write minimal implementation**

Add the optional fields to `SearchPlan` and `RAGState` as needed.

**Step 4: Run test to verify it passes**

Run: `pytest tests/agentic_rag/test_structured_search_plan.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/agentic_rag/schemas.py tests/agentic_rag/test_structured_search_plan.py
git commit -m "feat: extend rag schemas for structured search"
```

### Task 9: Update search planner to emit optional structured intent

**Files:**
- Modify: `src/agentic_rag/node/search_planner.py`
- Create: `tests/agentic_rag/node/test_search_planner_structured.py`

**Step 1: Write the failing test**

Test that fact-like questions with complete slots produce:

- a normal vector query
- an optional structured query payload

And open-ended questions do not force structured search.

**Step 2: Run test to verify it fails**

Run: `pytest tests/agentic_rag/node/test_search_planner_structured.py -v`
Expected: FAIL because planner output does not include structured intent.

**Step 3: Write minimal implementation**

Start with simple rules based on:

- `intent`
- slot completeness
- obvious fact-question patterns

Avoid introducing LLM-generated raw SQL.

**Step 4: Run test to verify it passes**

Run: `pytest tests/agentic_rag/node/test_search_planner_structured.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/agentic_rag/node/search_planner.py tests/agentic_rag/node/test_search_planner_structured.py
git commit -m "feat: add structured retrieval planning hints"
```

### Task 10: Add structured search node to Agentic RAG

**Files:**
- Create: `src/agentic_rag/node/structured_search.py`
- Modify: `src/agentic_rag/graph.py`
- Create: `tests/agentic_rag/node/test_structured_search.py`
- Create: `tests/agentic_rag/test_graph_structured_search.py`

**Step 1: Write the failing test**

Test that:

- semantic retrieval still runs
- structured search only runs when requested
- missing structured results do not break the pipeline

**Step 2: Run test to verify it fails**

Run: `pytest tests/agentic_rag/node/test_structured_search.py tests/agentic_rag/test_graph_structured_search.py -v`
Expected: FAIL because the node and graph wiring do not exist.

**Step 3: Write minimal implementation**

Implement:

- a `structured_search` node
- graph wiring after `retrieval`
- state updates for structured pseudo-documents

**Step 4: Run test to verify it passes**

Run: `pytest tests/agentic_rag/node/test_structured_search.py tests/agentic_rag/test_graph_structured_search.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/agentic_rag/node/structured_search.py src/agentic_rag/graph.py tests/agentic_rag
git commit -m "feat: add optional structured search node to rag graph"
```

### Task 11: Update fusion and rerank behavior

**Files:**
- Modify: `src/agentic_rag/node/rerank.py`
- Create: `tests/agentic_rag/node/test_rerank_structured_fusion.py`

**Step 1: Write the failing test**

Test that SQLite pseudo-documents and vector documents:

- can be merged deterministically
- preserve metadata source
- do not duplicate identical records

**Step 2: Run test to verify it fails**

Run: `pytest tests/agentic_rag/node/test_rerank_structured_fusion.py -v`
Expected: FAIL because fusion behavior is missing.

**Step 3: Write minimal implementation**

Implement a simple fusion rule:

- concatenate structured pseudo-documents and vector documents
- deduplicate by stable identifier
- preserve source metadata

Add weighting only if needed after initial tests.

**Step 4: Run test to verify it passes**

Run: `pytest tests/agentic_rag/node/test_rerank_structured_fusion.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/agentic_rag/node/rerank.py tests/agentic_rag/node/test_rerank_structured_fusion.py
git commit -m "feat: fuse structured and vector evidence"
```

### Task 12: Wire runtime dependencies

**Files:**
- Modify: `src/runtime/graph_runtime.py`
- Modify: `src/graph.py`
- Modify: `src/node/runtime_resources.py`
- Create: `tests/runtime/test_graph_runtime_structured.py`

**Step 1: Write the failing test**

Test that runtime startup:

- initializes the SQLite structured layer
- injects dependencies into graph creation
- still starts without structured data content preloaded

**Step 2: Run test to verify it fails**

Run: `pytest tests/runtime/test_graph_runtime_structured.py -v`
Expected: FAIL because runtime injection is not wired.

**Step 3: Write minimal implementation**

Add:

- SQLite database path configuration
- repository or service creation during startup
- graph dependency injection

**Step 4: Run test to verify it passes**

Run: `pytest tests/runtime/test_graph_runtime_structured.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/runtime/graph_runtime.py src/graph.py src/node/runtime_resources.py tests/runtime/test_graph_runtime_structured.py
git commit -m "feat: wire structured retrieval services into runtime"
```

### Task 13: Add admin-facing import API skeleton

**Files:**
- Modify: `src/api/chat_app.py`
- Create: `tests/api/test_structured_import_api.py`

**Step 1: Write the failing test**

Add tests for:

- `POST /admin/structured-imports/preview`
- `POST /admin/structured-imports`
- `GET /admin/structured-imports/{import_id}`

Use mocked services first.

**Step 2: Run test to verify it fails**

Run: `pytest tests/api/test_structured_import_api.py -v`
Expected: FAIL because routes do not exist.

**Step 3: Write minimal implementation**

Add route skeletons that call the import service and return normalized JSON responses.

**Step 4: Run test to verify it passes**

Run: `pytest tests/api/test_structured_import_api.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add src/api/chat_app.py tests/api/test_structured_import_api.py
git commit -m "feat: add admin structured import api skeleton"
```

### Task 14: Add sample ingestion adapter for one data source

**Files:**
- Create: `data/structured_import/__init__.py`
- Create: `data/structured_import/admission_policy_adapter.py`
- Create: `tests/data/test_admission_policy_adapter.py`

**Step 1: Write the failing test**

Test that one existing admission-policy source file can be normalized into `StructuredImportRow` objects.

**Step 2: Run test to verify it fails**

Run: `pytest tests/data/test_admission_policy_adapter.py -v`
Expected: FAIL because adapter code does not exist.

**Step 3: Write minimal implementation**

Implement one adapter only for the selected phase-1 source.

**Step 4: Run test to verify it passes**

Run: `pytest tests/data/test_admission_policy_adapter.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add data/structured_import tests/data/test_admission_policy_adapter.py
git commit -m "feat: add structured import adapter for admission policy data"
```

### Task 15: Verify end-to-end behavior

**Files:**
- Modify: `README.md`
- Modify: `docs/README.md`
- Create: `tests/integration/test_structured_retrieval_flow.py`

**Step 1: Write the failing integration test**

Test an end-to-end scenario:

- import structured rows
- start runtime
- run a fact-like question
- verify semantic retrieval remains active
- verify structured evidence is available in fused output

**Step 2: Run test to verify it fails**

Run: `pytest tests/integration/test_structured_retrieval_flow.py -v`
Expected: FAIL because end-to-end wiring is incomplete.

**Step 3: Write minimal implementation or glue code**

Add any remaining integration glue and document configuration in README/docs only after the test demonstrates the missing behavior.

**Step 4: Run full verification**

Run: `pytest tests/structured tests/agentic_rag tests/runtime tests/api tests/integration -v`
Expected: PASS

**Step 5: Commit**

```bash
git add README.md docs/README.md tests/integration/test_structured_retrieval_flow.py
git commit -m "docs: document structured retrieval setup and verification"
```

