# Stream Resource Guardrails Design

## Goal

Add the minimum production guardrails that the current single-machine deployment
is missing for streaming requests:

- per-thread single-flight protection
- total stream duration and idle timeouts
- basic Nginx IP rate limiting for public streaming entrypoints

The intent is to make the current anonymous, single-worker-first deployment safe
enough to stay up on the public internet without redesigning the whole runtime.

## Context

The current system already moved the browser behind a Next.js BFF, but the
backend streaming endpoints are still effectively ungoverned:

- `/threads/{thread_id}/runs/stream` can be entered concurrently for the same
  thread
- `/runs/stream` and `/api/chat/stream` can hold open indefinitely
- Nginx forwards streaming traffic without any request throttling

That creates three concrete risks:

1. Concurrent writes can corrupt or reorder thread state
2. Hung or idle streams can pin Python worker capacity indefinitely
3. Internet scanners, browser retries, or reconnect storms can flood expensive
   streaming paths before the app has a chance to protect itself

## Approaches Considered

### 1. Minimal in-process guardrails at the FastAPI layer plus Nginx rate limiting

This approach adds:

- a process-local single-flight registry keyed by `thread_id`
- a shared SSE wrapper that enforces max duration and idle timeout
- Nginx `limit_req` on the public streaming paths

Pros:

- small change set
- directly addresses the requested hard blockers
- fits the current single-worker deployment model
- easy to test with the existing backend test suite

Cons:

- the single-flight guarantee is only process-local
- it is not the final answer for future multi-worker deployment

### 2. Add app-layer guardrails plus global active-stream caps

This extends approach 1 with an in-process semaphore or per-device/IP caps.

Pros:

- better protection against overload
- easier to reason about worker capacity

Cons:

- adds policy choices the current rollout does not need yet
- higher risk of rejecting valid usage before baseline telemetry exists

### 3. Build the final distributed model now

This would move single-flight leases and rate limits into Redis or an API
gateway, sized for future multi-worker deployment.

Pros:

- correct long-term architecture
- works across workers and hosts

Cons:

- materially larger scope
- adds new infrastructure dependencies
- slows down the current minimal production hardening work

## Final Decision

Use approach 1 now.

The system is still single-machine and single-worker-first. The shortest path to
safe public operation is to add the missing guardrails at the app layer and at
the public reverse proxy without changing the runtime architecture.

## Design

### 1. Per-thread single-flight

Only `/threads/{thread_id}/runs/stream` gets single-flight enforcement in this
change.

Behavior:

- when a thread stream starts, FastAPI acquires a process-local lease for that
  `thread_id`
- if another request for the same thread arrives before the first stream exits,
  FastAPI rejects it immediately with `409`
- the error payload uses a stable code such as `THREAD_BUSY`
- the lease is released in a `finally` block when the stream completes or fails

This is the highest-value concurrency protection because it prevents thread
state races, which are the most dangerous class of corruption in the current
architecture.

### 2. Shared streaming timeout wrapper

All three streaming endpoints are wrapped with one shared helper:

- `/threads/{thread_id}/runs/stream`
- `/runs/stream`
- `/api/chat/stream`

The wrapper enforces:

- `STREAM_MAX_DURATION_SECONDS`
- `STREAM_IDLE_TIMEOUT_SECONDS`

Implementation shape:

- await the next event from the upstream async iterator with `asyncio.wait_for`
- use the idle timeout for each next-event wait
- separately track a total deadline from stream start
- when the idle timeout fires, emit one SSE `error` event with code
  `STREAM_IDLE_TIMEOUT` and terminate the stream
- when the total duration is exceeded, emit one SSE `error` event with code
  `STREAM_MAX_DURATION_EXCEEDED` and terminate the stream

This keeps the streaming protocol compatible for the current frontend while
ensuring requests cannot hang forever.

### 3. Nginx IP rate limiting

Nginx adds a simple per-IP request limiter for the public streaming paths only:

- `/api/chat/stream`
- `/api/runs/stream`
- `/api/threads/*/runs/stream`

Design choices:

- use `limit_req_zone $binary_remote_addr`
- apply `limit_req` at the public edge before traffic reaches Next.js/FastAPI
- return `429` when the rate limit is exceeded

This is intentionally coarse-grained. It is there to absorb scanners, crawlers,
and reconnect storms before they burn app resources.

## Configuration

Add the following backend env variables:

- `STREAM_MAX_DURATION_SECONDS`
- `STREAM_IDLE_TIMEOUT_SECONDS`

Default values should be conservative and production-safe for the current
system. A sensible starting point is:

- max duration: 120 seconds
- idle timeout: 30 seconds

The existing `API_RATE_LIMIT_PER_MINUTE` variable should not be expanded in this
change. Nginx becomes the first-line rate limiter, and the app change focuses on
correctness and hung-request cleanup.

## Error Handling

### Thread busy

- HTTP status: `409`
- JSON payload:
  - `code: "THREAD_BUSY"`
  - `message: "A run is already active for this thread"`

### Stream idle timeout

- SSE event: `error`
- payload code: `STREAM_IDLE_TIMEOUT`
- stream ends after the error event

### Stream max duration exceeded

- SSE event: `error`
- payload code: `STREAM_MAX_DURATION_EXCEEDED`
- stream ends after the error event

### Upstream runtime errors

Existing upstream error mapping remains unchanged. Timeout guardrails are added
around the current behavior rather than replacing it.

## Testing Strategy

### Backend tests

Add focused API tests for:

- concurrent `/threads/{thread_id}/runs/stream` returns `409 THREAD_BUSY`
- idle timeout produces an SSE `error` event with `STREAM_IDLE_TIMEOUT`
- max duration produces an SSE `error` event with
  `STREAM_MAX_DURATION_EXCEEDED`
- `/runs/stream` still works and is only affected by timeout guardrails, not
  thread single-flight

### Config verification

Verify the Nginx config now contains:

- `limit_req_zone`
- `limit_req_status 429`
- `limit_req` blocks for the three public streaming paths

### Regression verification

Run:

- focused backend pytest for the new API tests
- full `pytest -q`

## Non-Goals

This change does not:

- add distributed locking
- add Redis-backed quotas or rate limiting
- add per-device or per-user quotas
- add global active-stream caps
- redesign the runtime state model

## Future Follow-Up

When the deployment moves to multiple workers, the process-local single-flight
registry must be replaced with a shared lease mechanism, likely in Redis or at a
gateway layer. At that point, rate limits and connection quotas should also move
to distributed enforcement with consistent counters across workers.
