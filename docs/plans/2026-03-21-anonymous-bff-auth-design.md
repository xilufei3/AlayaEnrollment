# Anonymous BFF Auth Hardening Design

## Goal

Move the current single-machine deployment from a browser-held shared API key to a
Next.js backend-for-frontend (BFF) model so anonymous visitors can keep using the
chat UI while `API_SHARED_KEY` stays server-only.

## Context

The current deployment mixes three responsibilities in the browser:

- calling FastAPI directly
- attaching `X-Api-Key`
- generating and sending `X-Device-Id`

That is acceptable for an internal demo, but it is not acceptable for a public or
long-running deployment:

- `NEXT_PUBLIC_API_SHARED_KEY` can be exposed to the browser bundle
- the browser can persist the key in `localStorage`
- Nginx currently hardcodes the same shared key in a committed config file
- `X-Device-Id` is useful for anonymous thread grouping, but it is not a trusted
  identity signal

This design keeps the anonymous visitor model for now, but removes the shared key
from every browser-visible surface.

## Final Decisions

### 1. Use Option A1: Next.js BFF as the only public API surface

The browser will talk only to the Next.js app on port `3000` and to same-origin
`/api/*` routes served by that app.

FastAPI remains the upstream application server, but it becomes private to the host
and is no longer part of the public browser contract.

### 2. Keep anonymous visitors, but narrow the meaning of `X-Device-Id`

`X-Device-Id` stays in the system because the current thread list and ownership model
already depend on it. In this change it is explicitly treated as an anonymous device
or browser scope marker only.

It continues to support:

- thread isolation between browsers
- restoring thread history for the same browser
- optimistic local thread UX

It does not become an authentication credential.

### 3. Proxy the actual LangGraph-compatible API surface, not only `/chat/stream`

The current frontend does not only use `/api/chat/stream`. It uses the LangGraph SDK
thread and run endpoints:

- `/info`
- `/threads`
- `/threads/search`
- `/threads/{id}`
- `/threads/{id}/state`
- `/threads/{id}/history`
- `/runs/stream`
- `/threads/{id}/runs/stream`

The BFF must cover the endpoints the frontend already uses so the current UI can
continue to work without a frontend rewrite.

### 4. Use a whitelist-based catch-all API route in Next.js

Instead of scattering many route handlers that each duplicate proxy logic, the
frontend will add:

- `web/src/app/api/[[...path]]/route.ts`
- `web/src/lib/server/backend-proxy.ts`

The route handler will only proxy a controlled list of upstream paths. It will not
be a general open proxy.

### 5. Keep `API_SHARED_KEY` server-only

`API_SHARED_KEY` will be read only in Node.js server code:

- Next.js BFF reads it from `process.env.API_SHARED_KEY`
- FastAPI still validates it

The key will be removed from:

- `NEXT_PUBLIC_*` variables
- frontend config exports
- browser storage flows
- committed Nginx config

### 6. Introduce `BACKEND_INTERNAL_URL` for the BFF upstream target

The Next.js server will forward requests to:

- `BACKEND_INTERNAL_URL=http://127.0.0.1:8008`

This remains a server-only environment variable. It is not injected into the browser
bundle.

### 7. Rewrite `/api/info` for the browser view

FastAPI can continue returning `api_key_required: true` because it still expects the
shared key from its trusted caller.

The BFF will rewrite the payload returned to the browser so that:

- `api_key_required` becomes `false`

This allows the current frontend to stop showing the API key input workflow while
preserving the upstream FastAPI contract.

### 8. FastAPI binds to localhost only

For the single-machine deployment, FastAPI will run on:

- `127.0.0.1:8008`

The public ingress path becomes:

- browser -> Nginx -> Next.js -> FastAPI

This shrinks the exposed surface without requiring a broader infrastructure change.

### 9. Nginx only proxies to Next.js

Nginx will no longer proxy `/api/` directly to FastAPI and will no longer inject
`X-Api-Key`.

Both `/` and `/api/*` will terminate at Next.js. The Next.js BFF owns the upstream
hop to FastAPI.

### 10. Rotate the current shared key immediately

The committed Nginx file already contains a concrete shared key. That key should be
treated as compromised and replaced before or together with this rollout.

## Architecture Changes

### Browser layer

The browser keeps:

- `NEXT_PUBLIC_API_URL=/api`
- `NEXT_PUBLIC_ASSISTANT_ID`
- locally generated `X-Device-Id`

The browser stops carrying:

- `X-Api-Key`
- any public/shared key environment variable
- any stored API key in `localStorage`

### Next.js BFF layer

The BFF becomes responsible for:

- validating the requested API path against an allowlist
- building the upstream URL from `BACKEND_INTERNAL_URL`
- forwarding request method, body, and safe headers
- preserving `X-Device-Id`
- dropping any incoming browser `X-Api-Key`
- injecting server-side `API_SHARED_KEY`
- transparently streaming SSE responses
- rewriting `/info` so the browser sees `api_key_required: false`

### FastAPI layer

FastAPI changes minimally in this design:

- it still validates `X-Api-Key`
- it still uses `X-Device-Id` for anonymous thread scoping
- it is no longer publicly bound

This keeps the current runtime and graph behavior stable while the exposure model
changes around it.

## Data Flow

### Standard JSON request

1. Browser calls `POST /api/threads/search`
2. Next.js BFF validates `/threads/search`
3. Next.js forwards the request to `http://127.0.0.1:8008/threads/search`
4. Next.js injects `X-Api-Key: <server-side secret>`
5. Next.js forwards `X-Device-Id`
6. FastAPI processes the request and returns JSON
7. Next.js returns the JSON response to the browser

### Streaming request

1. Browser calls `POST /api/runs/stream`
2. Next.js BFF validates `/runs/stream`
3. Next.js forwards the request upstream with server-only `X-Api-Key`
4. FastAPI returns `text/event-stream`
5. Next.js returns `upstream.body` directly without buffering or rewriting event data

### `/info` request

1. Browser calls `GET /api/info`
2. Next.js forwards the request upstream
3. FastAPI returns JSON including `api_key_required: true`
4. Next.js rewrites that field to `false`
5. Browser no longer prompts for a shared key

## Error Handling

### Server environment errors

If `API_SHARED_KEY` or `BACKEND_INTERNAL_URL` is missing in the Next.js server
environment, the BFF returns a `500` response with a clear server-side configuration
error message.

### Disallowed proxy paths

If the browser requests a path outside the approved allowlist, the BFF returns `404`
or `403` rather than forwarding the request.

### Upstream JSON errors

If FastAPI returns a JSON error, the BFF forwards the upstream status code and body
without masking it.

### Upstream streaming errors

If FastAPI returns SSE, the BFF forwards the stream body and relevant response
headers. It should not buffer or transform the SSE payload.

## Testing Strategy

### Unit-level web tests

Add tests for the server-side proxy helper to verify:

- allowlist path matching
- upstream URL mapping
- dropping incoming `X-Api-Key`
- preserving `X-Device-Id`
- rewriting `/info` payloads

### Integration-level web verification

Run:

- `npm.cmd run lint`
- `npm.cmd run build`

### Backend regression verification

Run:

- `pytest -q`

The FastAPI graph/runtime behavior should stay unchanged in this design.

### Manual smoke tests

Verify:

- the browser no longer shows an API key input UI
- thread creation and history still work
- streaming still works through `/api/*`
- `127.0.0.1:8008` is reachable locally but not publicly exposed
- the committed Nginx file no longer contains a hardcoded shared key

## Non-Goals

This design does not do the following:

- add user login or SSO
- replace `X-Device-Id` with a real identity model
- redesign the FastAPI thread ownership model
- remove FastAPI shared-key middleware entirely
- introduce multi-machine or multi-instance deployment support

## Files Likely To Change

- `web/next.config.mjs`
- `web/src/app/api/[[...path]]/route.ts`
- `web/src/lib/server/backend-proxy.ts`
- `web/src/providers/Stream.tsx`
- `web/src/providers/client.ts`
- `web/src/lib/device-id.ts`
- `.env.example`
- `web/.env.example`
- `infra/nginx/alaya-enrollment.conf`
- `README.md`
- `web/README.md`

## Summary

This design deliberately keeps the current anonymous-visitor behavior intact while
moving the shared API key entirely to the server side.

The main architectural shift is not a graph change or a UI redesign. It is a trust
boundary change:

- the browser stops knowing the shared key
- Next.js becomes the only public API surface
- FastAPI becomes a localhost-only upstream

That gives the project a much safer single-machine deployment baseline without
forcing a full login system into the same change.
