# Runtime State Persistence Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move runtime files onto a configurable persistent root and make
registry-backed threads survive restart without returning `404`.

**Architecture:** Keep SQLite checkpoints and the SQLite thread registry as the
current persistence model. Add a `RUNTIME_ROOT` override for the runtime base
directory, treat the registry as the durable source of thread identity and
timestamps, and keep `_threads` as a process-local hot cache only.

**Tech Stack:** Python, FastAPI, `pathlib`, SQLite, pytest, README /
environment-variable documentation

---

### Task 1: Add failing tests for runtime root selection

**Files:**
- Create: `tests/graph/node/test_runtime_resources.py`

**Step 1: Write the failing test**

Add focused tests like:

```python
def test_bootstrap_runtime_dirs_uses_runtime_root_env(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    external_root = tmp_path / "persistent-runtime"
    monkeypatch.setenv("RUNTIME_ROOT", str(external_root))

    runtime_root = bootstrap_runtime_dirs(repo_root, runtime_name="chat-api")

    assert runtime_root == external_root / "chat-api"
    assert (runtime_root / "logs").exists()
```

Also add a fallback test that verifies the helper still uses
`repo_root / ".runtime" / runtime_name` when `RUNTIME_ROOT` is unset.

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/graph/node/test_runtime_resources.py -q
```

Expected: FAIL because `bootstrap_runtime_dirs()` currently always uses
`repo_root/.runtime`.

**Step 3: Write minimal implementation**

Do not implement yet. This task ends at the failing test.

### Task 2: Implement configurable runtime root selection

**Files:**
- Modify: `src/graph/node/runtime_resources.py`
- Test: `tests/graph/node/test_runtime_resources.py`

**Step 1: Add runtime root resolution**

Update `bootstrap_runtime_dirs()` so it:

- reads `RUNTIME_ROOT`
- uses it when non-empty
- falls back to `repo_root / ".runtime"` otherwise
- keeps `runtime_name` as the final subdirectory

Keep the exported environment variables (`ROOT_DIR`, `LOGS_DIR`,
`WORKFLOWS_DIR`, `ENVS_DIR`) aligned with the resolved runtime directory.

**Step 2: Run focused tests**

Run:

```bash
pytest tests/graph/node/test_runtime_resources.py -q
```

Expected: PASS

**Step 3: Commit**

```bash
git add src/graph/node/runtime_resources.py tests/graph/node/test_runtime_resources.py
git commit -m "feat: support configurable runtime root"
```

### Task 3: Add failing tests for registry-backed restart recovery

**Files:**
- Modify: `tests/runtime/test_graph_runtime_async_checkpoint.py`
- Create: `tests/api/test_chat_app_runtime_persistence.py`

**Step 1: Write the failing runtime test**

Add a runtime-level test that simulates:

- thread created and persisted into `ThreadRegistry`
- process restart with an empty `_threads` cache
- no checkpoint rows for that thread

The test should assert that `get_thread_state(thread_id=...)` returns:

- registry metadata
- `values == {}`
- a non-`None` `created_at`
- `checkpoint.checkpoint_id is None`

instead of the current fully empty "not found" shape.

**Step 2: Write the failing API test**

Add a focused FastAPI test that:

- creates a thread without producing a checkpoint
- simulates restart against the same registry file
- verifies `/threads/search` still lists the thread
- verifies `GET /threads/{id}` returns `200`
- verifies `GET /threads/{id}/state` returns `200`
- verifies `POST /threads/{id}/history` returns `[]`

Use a lightweight runtime wrapper around `AdmissionGraphRuntime` so the test
exercises the real recovery behavior rather than a fake in-memory runtime.

**Step 3: Run tests to verify they fail**

Run:

```bash
pytest tests/runtime/test_graph_runtime_async_checkpoint.py tests/api/test_chat_app_runtime_persistence.py -q
```

Expected: FAIL because registry-only threads currently collapse into a `404`
path after restart.

**Step 4: Write minimal implementation**

Do not implement yet. This task ends at the failing tests.

### Task 4: Implement registry-backed thread recovery and timestamp sourcing

**Files:**
- Modify: `src/runtime/graph_runtime.py`
- Modify: `src/api/chat_app.py`
- Test: `tests/runtime/test_graph_runtime_async_checkpoint.py`
- Test: `tests/api/test_chat_app_runtime_persistence.py`

**Step 1: Add a registry-backed thread lookup helper**

In `src/runtime/graph_runtime.py`, add a small helper that reads the registry
row for a thread when available. Keep it JSON-safe and reuse it anywhere thread
metadata or timestamps need to come from the durable registry.

**Step 2: Synthesize an empty state for registry-only threads**

Update `get_thread_state()` so it resolves state in this order:

1. latest checkpoint-backed state
2. `_threads` hot-cache state
3. synthesized empty state from the registry row
4. fully empty state when nothing exists

The registry-backed state must carry registry metadata and a best-effort state
timestamp derived from registry `updated_at`.

**Step 3: Fix thread detail timestamps**

Update the `/threads/{id}` response path so that, when a registry row exists:

- `created_at` comes from registry `created_at`
- `updated_at` comes from registry `updated_at`
- `state_updated_at` prefers the latest state timestamp and otherwise falls back
  to registry `updated_at`

Keep ownership checks unchanged apart from letting registry metadata satisfy the
existing device-id validation path.

**Step 4: Run focused tests**

Run:

```bash
pytest tests/graph/node/test_runtime_resources.py tests/runtime/test_graph_runtime_async_checkpoint.py tests/api/test_chat_app_runtime_persistence.py -q
```

Expected: PASS

**Step 5: Commit**

```bash
git add src/runtime/graph_runtime.py src/api/chat_app.py tests/runtime/test_graph_runtime_async_checkpoint.py tests/api/test_chat_app_runtime_persistence.py
git commit -m "fix: recover registry-backed threads after restart"
```

### Task 5: Document persistent runtime path configuration

**Files:**
- Modify: `.env.example`
- Modify: `README.md`

**Step 1: Add the new environment variable**

Document `RUNTIME_ROOT` in `.env.example` near the other runtime settings. Keep
it blank by default so local development still falls back to repo `.runtime`.

**Step 2: Update deployment guidance**

Update `README.md` to explain:

- local development can keep using repo `.runtime`
- production should set `RUNTIME_ROOT` to a repo-external persistent path
- runtime SQLite files live under `<RUNTIME_ROOT>/<runtime_name>/`
- this remains a single-worker deployment assumption

**Step 3: Run text verification**

Run:

```bash
rg -n "RUNTIME_ROOT|single-worker|checkpoints.sqlite|thread_registry.sqlite" .env.example README.md
```

Expected: matches in both files.

**Step 4: Commit**

```bash
git add .env.example README.md
git commit -m "docs: document persistent runtime root"
```

### Task 6: Run final verification

**Files:**
- Modify: none

**Step 1: Run focused persistence tests**

Run:

```bash
pytest tests/graph/node/test_runtime_resources.py tests/runtime/test_graph_runtime_async_checkpoint.py tests/api/test_chat_app_runtime_persistence.py -q
```

Expected: PASS

**Step 2: Run the full test suite**

Run:

```bash
pytest -q
```

Expected: PASS

**Step 3: Perform a manual restart smoke test**

Manual verification:

- set `RUNTIME_ROOT` to a temp directory outside the repo
- create a thread but do not send a checkpoint-producing run
- restart the backend
- verify `/threads/search` still lists the thread
- verify `/threads/{id}` and `/threads/{id}/state` return the empty thread
  instead of `404`
- verify `/threads/{id}/history` remains empty

**Step 4: Optional cleanup**

If the manual smoke test used a temporary runtime root, remove it after the
verification run.
