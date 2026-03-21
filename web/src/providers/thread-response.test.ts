import assert from "node:assert/strict";
import test from "node:test";

import {
  isThreadNotFoundPayload,
  isThreadPayload,
  resolveThreadLookupResponse,
} from "./thread-response.ts";

test("recognizes a valid thread payload", () => {
  const payload = {
    thread_id: "thread-1",
    created_at: "2026-03-21T09:00:00.000Z",
    updated_at: "2026-03-21T09:00:00.000Z",
    metadata: {},
    status: "idle",
    values: {},
    interrupts: {},
  };

  assert.equal(isThreadPayload(payload), true);
  assert.deepEqual(resolveThreadLookupResponse(payload), payload);
});

test("recognizes the backend thread-not-found payload", () => {
  const payload = { detail: "Thread not found" };

  assert.equal(isThreadNotFoundPayload(payload), true);
  assert.equal(resolveThreadLookupResponse(payload), null);
});

test("throws on unexpected thread lookup payloads", () => {
  assert.throws(
    () => resolveThreadLookupResponse({ detail: "Unauthorized" }),
    /Unexpected thread lookup response shape/,
  );
});
