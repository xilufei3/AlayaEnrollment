# Runtime State Persistence Design

## Goal

Harden the current single-machine, single-worker deployment by fixing two
practical runtime-state problems:

- runtime data should not live only under the repository checkout
- a thread that exists in the persistent registry should not become `404` after
  process restart just because it has no checkpoint yet

The intent is to improve persistence and restart consistency without redesigning
the runtime for multi-worker or multi-machine deployment.

## Context

The current backend already splits state across three places:

- LangGraph checkpoints persist message history and state snapshots in SQLite
- `ThreadRegistry` persists thread identity, metadata, and ordering for the
  sidebar thread list
- `_threads` stores process-local hot state such as current values and status

That shape is acceptable for the current single-worker deployment, but two
problems remain:

1. the runtime root is anchored under `repo_root/.runtime`, which makes runtime
   data vulnerable to repo cleanup, worktree replacement, and deployment
   scripts that recreate the checkout
2. `get_thread_state()` only checks checkpoints first and `_threads` second, so
   a registry-only thread can appear in `/threads/search` but fail ownership
   lookup and return `404` from `/threads/{id}`

This change does not attempt to solve cross-worker consistency. It only makes
the current single-worker model durable and restart-safe.

## Approaches Considered

### 1. Add a configurable runtime root and registry-backed restart recovery

This approach:

- introduces an environment variable for the runtime base directory
- keeps checkpoints and thread registry in SQLite
- treats the registry as the durable source of thread existence and metadata
- keeps `_threads` only as a process-local hot cache

Pros:

- smallest useful change set
- directly addresses the two current operational problems
- preserves the existing LangGraph checkpointer integration
- keeps the future path to Redis/Postgres open

Cons:

- still single-worker oriented
- run leases and active run state remain process-local

### 2. Keep the current runtime root and only patch the `404` behavior

This approach only fixes thread recovery.

Pros:

- smallest code diff
- fixes the most visible restart bug

Cons:

- runtime data still lives inside the repo checkout
- deployment and cleanup workflows can still destroy persistent state

### 3. Move directly to Redis/Postgres-backed shared state

This approach would externalize checkpoint coordination, thread metadata, and
run coordination into shared infrastructure now.

Pros:

- correct long-term architecture
- aligns with eventual multi-worker and multi-machine deployment

Cons:

- much larger scope
- adds new operational dependencies immediately
- slows down the current single-worker hardening work

## Final Decision

Use approach 1 now.

The current target is still single-machine and single-worker. The best next step
is to externalize the runtime root and make thread recovery consistent across
restart while preserving the current SQLite-backed runtime model.

## Design

### 1. Runtime root configuration

Add a new environment variable:

- `RUNTIME_ROOT`

`bootstrap_runtime_dirs(repo_root, runtime_name)` will resolve the runtime base
directory in this order:

1. `RUNTIME_ROOT` when it is set to a non-empty path
2. `repo_root / ".runtime"` as the local-development fallback

The effective runtime directory remains scoped by runtime name:

- `<runtime_base>/<runtime_name>/checkpoints.sqlite`
- `<runtime_base>/<runtime_name>/thread_registry.sqlite`
- `<runtime_base>/<runtime_name>/logs/`
- `<runtime_base>/<runtime_name>/workflows/`
- `<runtime_base>/<runtime_name>/envs/`

This preserves current local behavior while allowing production deployments to
place runtime files on a repo-external persistent path such as
`/var/lib/alaya-enrollment/runtime`.

`RuntimeConfig.checkpoint_path` continues to override the default checkpoint
location when explicitly provided. This change only affects the default runtime
root selection.

### 2. State source boundaries

After this change, the runtime should treat the three state layers as follows:

- checkpoint: durable source of conversation values and history snapshots
- thread registry: durable source of thread existence, metadata, created time,
  and updated time
- `_threads`: best-effort hot cache for the active Python process only

That means `_threads` must no longer be relied on to prove whether a thread
exists. A thread exists when either:

- a checkpoint exists for it, or
- a registry row exists for it

### 3. Registry-backed empty-state recovery

`get_thread_state(thread_id=...)` will keep its current priority order for
actual values:

1. latest checkpoint-backed state
2. process-local `_threads` hot state
3. synthesized empty state from the registry row
4. fully empty "not found" shape

The new registry-backed branch is the key fix. When a thread has no checkpoint
and is not present in `_threads`, but `ThreadRegistry.get_thread(thread_id)`
returns a row, `get_thread_state()` should synthesize a valid state object:

- `values: {}`
- `metadata`: registry metadata
- `checkpoint.thread_id`: requested thread id
- `checkpoint.checkpoint_id`: `None`
- `created_at`: registry `updated_at` as the best available state timestamp
- `parent_checkpoint`: `None`
- `tasks: []`

This keeps the state contract stable for the frontend while preventing
registry-only threads from disappearing after restart.

### 4. Thread detail payload consistency

The thread detail endpoint currently derives top-level timestamps from
`state.get("created_at")`, which is not sufficient once registry-backed empty
states are possible.

To keep `/threads/{id}` aligned with `/threads/search`, thread detail payloads
should use registry timestamps when a registry row exists:

- `created_at`: registry `created_at`
- `updated_at`: registry `updated_at`
- `state_updated_at`: latest checkpoint timestamp when available, otherwise
  registry `updated_at`

If a registry row is not available, the endpoint may fall back to the state
timestamp as it does today.

This makes the thread list, thread detail, and thread state endpoints describe
the same thread record after restart.

### 5. API behavior after restart

With the new recovery rules:

- `/threads/search` still returns registry-backed rows in updated order
- `/threads/{id}` no longer returns `404` for registry-only threads owned by the
  same device
- `/threads/{id}/state` returns an empty but valid state object when the thread
  exists without checkpoints
- `/threads/{id}/history` still returns an empty list when there are no
  checkpoints

Ownership checks remain unchanged. They continue to rely on `metadata.device_id`
from the recovered thread state, which will now be available from the registry
when no checkpoint exists yet.

## Testing Strategy

### Runtime root tests

Add focused tests for `bootstrap_runtime_dirs()` that verify:

- `RUNTIME_ROOT` moves the runtime directory outside the repo checkout
- the helper still falls back to `repo_root/.runtime` when `RUNTIME_ROOT` is
  not set

### Restart recovery tests

Add focused runtime tests that verify:

- a registry-only thread returns a synthesized empty state instead of a fully
  empty "not found" state
- checkpoint-backed threads still prefer checkpoint values and metadata
- thread detail payloads use registry timestamps when present

### API regression tests

Add focused API tests that verify:

- create thread without running a checkpoint-producing request
- simulate restart with the same persistent registry
- `/threads/search` still lists the thread
- `/threads/{id}` and `/threads/{id}/state` return `200` instead of `404`
- `/threads/{id}/history` remains an empty list

### Documentation verification

Update `.env.example` and `README.md` so production deployment instructions
describe:

- the new `RUNTIME_ROOT` variable
- the recommendation to place runtime files on a repo-external persistent path
- the fact that this is still a single-worker deployment model

## Non-Goals

This change does not:

- add Redis or Postgres
- make run leases shared across workers
- make multiple FastAPI workers safe
- redesign the LangGraph checkpoint format
- introduce a new thread storage backend

## Future Follow-Up

When the deployment moves beyond a single FastAPI worker, the next shared-state
work should focus on:

- distributed per-thread run leases
- shared run status / active run coordination
- consistent rate limiting across workers

At that point, Redis becomes the natural next step for hot coordination state,
with Postgres as the likely long-term home for durable thread metadata and audit
records.
