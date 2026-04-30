import assert from "node:assert/strict";
import test from "node:test";

import {
  buildUpstreamHeaders,
  buildUpstreamResponseHeaders,
  isAllowedProxyPath,
  rewriteBrowserInfoPayload,
  toUpstreamPath,
} from "./backend-proxy.ts";

test("isAllowedProxyPath accepts supported LangGraph endpoints", () => {
  assert.equal(isAllowedProxyPath(["threads", "abc", "runs", "stream"]), true);
  assert.equal(isAllowedProxyPath(["runs", "stream"]), true);
  assert.equal(isAllowedProxyPath(["info"]), true);
  assert.equal(isAllowedProxyPath(["admin", "conversations"]), true);
  assert.equal(isAllowedProxyPath(["admin", "conversations", "thread-1"]), true);
  assert.equal(isAllowedProxyPath(["secret", "admin"]), false);
});

test("buildUpstreamHeaders drops browser supplied x-api-key", () => {
  const headers = new Headers({
    "content-type": "application/json",
    "x-api-key": "browser-value",
    "x-device-id": "device-1",
  });

  const upstream = buildUpstreamHeaders(headers, "server-secret");

  assert.equal(upstream.get("content-type"), "application/json");
  assert.equal(upstream.get("x-api-key"), "server-secret");
  assert.equal(upstream.get("x-device-id"), "device-1");
});

test("toUpstreamPath maps browser api segments to upstream LangGraph paths", () => {
  assert.equal(toUpstreamPath(["threads", "thread-1", "runs", "stream"]), "/threads/thread-1/runs/stream");
  assert.equal(toUpstreamPath(["threads", "thread-1", "state"]), "/threads/thread-1/state");
  assert.equal(toUpstreamPath(["admin", "conversations", "thread-1"]), "/admin/conversations/thread-1");
  assert.equal(toUpstreamPath(["runs", "stream"]), "/runs/stream");
  assert.equal(toUpstreamPath(["info"]), "/info");
});

test("rewriteBrowserInfoPayload hides api_key_required from the browser", () => {
  assert.deepEqual(
    rewriteBrowserInfoPayload({
      assistant_id: "agent",
      api_key_required: true,
      runtime_ready: true,
    }),
    {
      assistant_id: "agent",
      api_key_required: false,
      runtime_ready: true,
    },
  );
});

test("buildUpstreamResponseHeaders preserves SSE-safe headers", () => {
  const headers = new Headers({
    "content-type": "text/event-stream",
    "cache-control": "no-cache",
    "content-location": "/threads/thread-1/runs/run-1",
    "x-accel-buffering": "no",
    "x-internal-debug": "drop-me",
  });

  const responseHeaders = buildUpstreamResponseHeaders(headers);

  assert.equal(responseHeaders.get("content-type"), "text/event-stream");
  assert.equal(responseHeaders.get("cache-control"), "no-cache");
  assert.equal(
    responseHeaders.get("content-location"),
    "/threads/thread-1/runs/run-1",
  );
  assert.equal(responseHeaders.get("x-accel-buffering"), "no");
  assert.equal(responseHeaders.has("x-internal-debug"), false);
});
