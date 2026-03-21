# Stream Resource Guardrails Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add per-thread single-flight, stream duration and idle timeouts, and basic Nginx IP rate limiting so public streaming requests stop being unbounded.

**Architecture:** Keep the current single-machine architecture intact. Add a process-local thread lease registry and shared SSE timeout wrapper in FastAPI, then add coarse per-IP throttling for the public streaming paths in Nginx.

**Tech Stack:** FastAPI, asyncio, SSE via `StreamingResponse`, pytest, Nginx

---

### Task 1: Add failing backend tests for the new stream guardrails

**Files:**
- Modify: `tests/api/test_chat_app_device_id.py`

**Step 1: Write the failing test**

Add tests that cover:

- rejecting a second `/threads/{thread_id}/runs/stream` request while the first
  one is still active
- returning an SSE `error` event when a stream stays idle past
  `STREAM_IDLE_TIMEOUT_SECONDS`
- returning an SSE `error` event when total stream duration exceeds
  `STREAM_MAX_DURATION_SECONDS`

Use a test runtime stub with controllable async generators so the tests exercise
the real FastAPI endpoint behavior.

**Step 2: Run test to verify it fails**

Run:

```bash
pytest tests/api/test_chat_app_device_id.py -q
```

Expected: FAIL because the current app does not enforce any of these guardrails.

**Step 3: Write minimal implementation**

Do not implement yet. This task ends at the failing test.

**Step 4: Commit**

Skip commit for now. Keep working tree changes local until the full feature is
verified.

### Task 2: Implement minimal FastAPI stream guardrails

**Files:**
- Modify: `src/api/chat_app.py`

**Step 1: Add process-local thread lease tracking**

Implement a lightweight lease helper in `src/api/chat_app.py` that:

- stores active thread ids in app state
- protects access with an `asyncio.Lock`
- exposes acquire/release helpers for the threaded run endpoint

**Step 2: Add shared stream timeout wrapper**

Implement a shared helper that:

- iterates an async event source
- waits for the next event with idle timeout enforcement
- tracks a total deadline for max duration enforcement
- emits exactly one SSE `error` event before stopping on timeout

**Step 3: Apply the helper to all streaming endpoints**

Update:

- `/threads/{thread_id}/runs/stream`
- `/runs/stream`
- `/api/chat/stream`

The thread endpoint should:

- acquire the thread lease before starting
- return `409` with `THREAD_BUSY` if the lease is already taken
- always release the lease when the stream ends

**Step 4: Run focused tests**

Run:

```bash
pytest tests/api/test_chat_app_device_id.py -q
```

Expected: PASS

### Task 3: Add basic Nginx per-IP throttling for streaming paths

**Files:**
- Modify: `infra/nginx/alaya-enrollment.conf`
- Modify: `.env.example`
- Modify: `README.md`

**Step 1: Update Nginx config**

Add:

- `limit_req_zone $binary_remote_addr ...`
- `limit_req_status 429`
- path-specific `limit_req` blocks for:
  - `/api/chat/stream`
  - `/api/runs/stream`
  - `/api/threads/.*/runs/stream`

Preserve the existing SSE proxy settings like `proxy_buffering off` and long
read timeouts.

**Step 2: Document backend timeout settings**

Add the new env variables to `.env.example` and document them in `README.md`.

**Step 3: Run config text verification**

Run:

```bash
rg -n "STREAM_MAX_DURATION_SECONDS|STREAM_IDLE_TIMEOUT_SECONDS|limit_req_zone|limit_req_status|limit_req" .env.example README.md infra/nginx/alaya-enrollment.conf
```

Expected: matches found in all three files.

### Task 4: Run final verification

**Files:**
- Modify: none

**Step 1: Run focused backend tests**

Run:

```bash
pytest tests/api/test_chat_app_device_id.py -q
```

Expected: PASS

**Step 2: Run the full backend suite**

Run:

```bash
pytest -q
```

Expected: PASS

**Step 3: Optional manual smoke verification**

Verify manually after deployment:

- a second tab cannot start a second run on the same thread while the first is
  still streaming
- a hung stream exits with a timeout error event instead of waiting forever
- bursty requests to the public streaming endpoints hit `429` at Nginx
