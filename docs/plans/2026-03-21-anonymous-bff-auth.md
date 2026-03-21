# Anonymous BFF Auth Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the single-machine deployment to a Next.js BFF model so anonymous visitors keep working while `API_SHARED_KEY` is removed from browser-visible code and configuration.

**Architecture:** Add a whitelist-based Next.js proxy for the current LangGraph-compatible API surface, make the browser use same-origin `/api`, inject `API_SHARED_KEY` only on the server, and bind FastAPI to `127.0.0.1`. Keep `X-Device-Id` only for anonymous thread scoping and preserve the existing FastAPI runtime contract.

**Tech Stack:** Next.js App Router, TypeScript, Node.js route handlers, FastAPI, Nginx, pytest, node:test

---

### Task 1: Add failing tests for the server-side proxy helper

**Files:**
- Create: `web/src/lib/server/backend-proxy.ts`
- Create: `web/src/lib/server/backend-proxy.test.ts`

**Step 1: Write the failing test**

```ts
import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUpstreamHeaders,
  isAllowedProxyPath,
  rewriteBrowserInfoPayload,
  toUpstreamPath,
} from "./backend-proxy.ts";

test("isAllowedProxyPath accepts supported LangGraph endpoints", () => {
  assert.equal(isAllowedProxyPath(["threads", "abc", "runs", "stream"]), true);
  assert.equal(isAllowedProxyPath(["runs", "stream"]), true);
  assert.equal(isAllowedProxyPath(["secret", "admin"]), false);
});

test("buildUpstreamHeaders drops browser supplied x-api-key", () => {
  const headers = new Headers({
    "x-api-key": "browser-value",
    "x-device-id": "device-1",
  });

  const upstream = buildUpstreamHeaders(headers, "server-secret");

  assert.equal(upstream.get("x-api-key"), "server-secret");
  assert.equal(upstream.get("x-device-id"), "device-1");
});

test("rewriteBrowserInfoPayload hides api_key_required from the browser", () => {
  assert.deepEqual(
    rewriteBrowserInfoPayload({
      assistant_id: "agent",
      api_key_required: true,
    }),
    {
      assistant_id: "agent",
      api_key_required: false,
    },
  );
});
```

**Step 2: Run test to verify it fails**

Run:

```bash
cd web
node --test src/lib/server/backend-proxy.test.ts
```

Expected: FAIL because the helper module does not exist yet.

**Step 3: Write minimal implementation**

Implement helper functions in `web/src/lib/server/backend-proxy.ts` for:

- allowed-path matching
- upstream path generation
- server-side header construction
- `/info` response rewriting

Do not add route handlers yet.

**Step 4: Run test to verify it passes**

Run:

```bash
cd web
node --test src/lib/server/backend-proxy.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add web/src/lib/server/backend-proxy.ts web/src/lib/server/backend-proxy.test.ts
git commit -m "test: cover server-side auth proxy helpers"
```

### Task 2: Add a failing test for browser request headers carrying only device scope

**Files:**
- Modify: `web/src/lib/device-id.ts`
- Create: `web/src/lib/device-id.test.ts`
- Modify: `web/src/providers/client.ts`

**Step 1: Write the failing test**

```ts
import assert from "node:assert/strict";
import test from "node:test";

import { getClientHeaders } from "./device-id.ts";

test("getClientHeaders only includes x-device-id for browser requests", () => {
  const headers = getClientHeaders();

  assert.equal(typeof headers["X-Device-Id"], "string");
  assert.equal("X-Api-Key" in headers, false);
});
```

Add a second test that verifies repeated calls still return a stable device identifier in
the same browser-like environment.

**Step 2: Run test to verify it fails**

Run:

```bash
cd web
node --test src/lib/device-id.test.ts
```

Expected: FAIL because `getClientHeaders` still accepts and forwards an API key.

**Step 3: Write minimal implementation**

Update:

- `web/src/lib/device-id.ts` so `getClientHeaders()` no longer accepts `apiKey`
- `web/src/providers/client.ts` so the LangGraph SDK client only sends browser-safe headers

Do not change `Stream.tsx` yet.

**Step 4: Run test to verify it passes**

Run:

```bash
cd web
node --test src/lib/device-id.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add web/src/lib/device-id.ts web/src/lib/device-id.test.ts web/src/providers/client.ts
git commit -m "feat: stop sending shared key from the browser"
```

### Task 3: Add the Next.js BFF route and wire SSE passthrough

**Files:**
- Create: `web/src/app/api/[[...path]]/route.ts`
- Modify: `web/src/lib/server/backend-proxy.ts`
- Modify: `web/src/lib/server/backend-proxy.test.ts`

**Step 1: Write the failing test**

Extend `web/src/lib/server/backend-proxy.test.ts` with a helper-level test such as:

```ts
test("toUpstreamPath maps browser api segments to upstream LangGraph paths", () => {
  assert.equal(toUpstreamPath(["threads", "thread-1", "runs", "stream"]), "/threads/thread-1/runs/stream");
  assert.equal(toUpstreamPath(["info"]), "/info");
});
```

Add a test covering which response headers should be preserved for SSE:

- `content-type`
- `cache-control`
- `x-accel-buffering`

**Step 2: Run test to verify it fails**

Run:

```bash
cd web
node --test src/lib/server/backend-proxy.test.ts
```

Expected: FAIL because the route wiring and header helpers are not complete yet.

**Step 3: Write minimal implementation**

Implement:

- `web/src/app/api/[[...path]]/route.ts`
- explicit `GET` and `POST` handlers
- `export const runtime = "nodejs"`
- `export const dynamic = "force-dynamic"`

The route should:

- allow only whitelisted paths
- read `BACKEND_INTERNAL_URL` and `API_SHARED_KEY`
- inject the server-side key
- forward request bodies for `POST`
- stream `upstream.body` directly for SSE
- rewrite `/info` payload before returning JSON to the browser

**Step 4: Run test to verify it passes**

Run:

```bash
cd web
node --test src/lib/server/backend-proxy.test.ts
```

Expected: PASS

**Step 5: Commit**

```bash
git add web/src/app/api/[[...path]]/route.ts web/src/lib/server/backend-proxy.ts web/src/lib/server/backend-proxy.test.ts
git commit -m "feat: add nextjs bff for langgraph api routes"
```

### Task 4: Remove browser API-key configuration and connection UI paths

**Files:**
- Modify: `web/src/providers/Stream.tsx`
- Modify: `web/next.config.mjs`
- Modify: `.env.example`
- Modify: `web/.env.example`

**Step 1: Write the failing test**

Create or extend a small helper-oriented test in:

- `web/src/lib/server/backend-proxy.test.ts`
- or create `web/src/providers/stream-config.test.ts`

with assertions such as:

```ts
test("browser config no longer depends on NEXT_PUBLIC_API_SHARED_KEY", () => {
  const publicKeys = ["NEXT_PUBLIC_API_URL", "NEXT_PUBLIC_ASSISTANT_ID"];
  assert.equal(publicKeys.includes("NEXT_PUBLIC_API_SHARED_KEY"), false);
});
```

Also add a regression assertion around the browser-side `/info` payload rewrite:

- `api_key_required` should evaluate to `false` for UI decisions

**Step 2: Run test to verify it fails**

Run:

```bash
cd web
node --test src/lib/server/backend-proxy.test.ts
```

Expected: FAIL because the browser still reads API key configuration and can render the key form.

**Step 3: Write minimal implementation**

Update `web/src/providers/Stream.tsx` to:

- stop reading `NEXT_PUBLIC_API_SHARED_KEY`
- stop reading or writing `lg:chat:apiKey`
- remove the API-key-only connection form branch
- keep `apiUrl` and `assistantId`

Update `web/next.config.mjs` and env examples to:

- expose only `NEXT_PUBLIC_API_URL`
- expose `NEXT_PUBLIC_ASSISTANT_ID` if still needed by the browser
- keep `API_SHARED_KEY` and `BACKEND_INTERNAL_URL` server-only

**Step 4: Run test to verify it passes**

Run:

```bash
cd web
node --test src/lib/server/backend-proxy.test.ts
npm.cmd run lint
```

Expected: PASS for the node test and no new lint errors related to removed API-key flows.

**Step 5: Commit**

```bash
git add web/src/providers/Stream.tsx web/next.config.mjs .env.example web/.env.example
git commit -m "refactor: keep shared api key on the server only"
```

### Task 5: Tighten single-machine deployment configuration

**Files:**
- Modify: `infra/nginx/alaya-enrollment.conf`
- Modify: `README.md`
- Modify: `web/README.md`

**Step 1: Write the failing verification checklist**

Document the expected deployment behavior directly in the docs update:

- Nginx `/api/` proxies to `127.0.0.1:3000`
- Nginx no longer injects `X-Api-Key`
- FastAPI runs on `127.0.0.1:8008`
- root `.env` contains `API_SHARED_KEY` and `BACKEND_INTERNAL_URL`
- browser-visible env files do not contain a public API key

**Step 2: Run the current verification commands**

Run:

```bash
rg -n "NEXT_PUBLIC_API_SHARED_KEY|proxy_set_header X-Api-Key" .env.example web/.env.example infra/nginx/alaya-enrollment.conf web/next.config.mjs
```

Expected: MATCHES are still present before the change.

**Step 3: Write minimal implementation**

Update docs and config so that:

- Nginx only proxies to Next.js
- `/api/` keeps `proxy_buffering off` and long timeouts for SSE
- README starts FastAPI on localhost only
- README explains `BACKEND_INTERNAL_URL`
- both env example files remove the public shared-key variable

**Step 4: Run verification to confirm the old patterns are gone**

Run:

```bash
rg -n "NEXT_PUBLIC_API_SHARED_KEY|proxy_set_header X-Api-Key" .env.example web/.env.example infra/nginx/alaya-enrollment.conf web/next.config.mjs
```

Expected: no matches

**Step 5: Commit**

```bash
git add infra/nginx/alaya-enrollment.conf README.md web/README.md
git commit -m "docs: align single-machine deployment with nextjs bff auth"
```

### Task 6: Run full verification before rollout

**Files:**
- Modify: none
- Test: `web/src/lib/server/backend-proxy.test.ts`
- Test: `web/src/lib/device-id.test.ts`
- Test: existing Python suite

**Step 1: Run focused web tests**

Run:

```bash
cd web
node --test src/lib/server/backend-proxy.test.ts src/lib/device-id.test.ts
```

Expected: PASS

**Step 2: Run frontend verification**

Run:

```bash
cd web
npm.cmd run lint
npm.cmd run build
```

Expected: PASS

**Step 3: Run backend verification**

Run:

```bash
cd ..
pytest -q
```

Expected: PASS

**Step 4: Run manual smoke tests**

Verify manually:

- open the web app and confirm no API key prompt appears
- create a new thread
- load an existing thread
- send a streaming message
- `curl http://127.0.0.1:8008/info` without `X-Api-Key` is still protected for direct callers
- `curl http://127.0.0.1:3000/api/info` returns browser-safe JSON with `api_key_required: false`

**Step 5: Commit**

```bash
git add web src README.md infra/nginx/alaya-enrollment.conf
git commit -m "feat: harden anonymous single-machine auth with nextjs bff"
```
