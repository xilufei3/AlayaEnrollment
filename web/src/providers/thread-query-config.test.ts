import assert from "node:assert/strict";
import test from "node:test";

import {
  getThreadSearchMetadata,
  resolveThreadConnection,
} from "./thread-query-config.ts";

test("falls back to env values when query params are absent", () => {
  const resolved = resolveThreadConnection({
    apiUrlFromQuery: null,
    assistantIdFromQuery: null,
    envApiUrl: "http://localhost:8008",
    envAssistantId: "agent",
  });

  assert.equal(resolved.apiUrl, "http://localhost:8008");
  assert.equal(resolved.assistantId, "agent");
});

test("query params override env values", () => {
  const resolved = resolveThreadConnection({
    apiUrlFromQuery: "http://example.com",
    assistantIdFromQuery: "from-query",
    envApiUrl: "http://localhost:8008",
    envAssistantId: "agent",
  });

  assert.equal(resolved.apiUrl, "http://example.com");
  assert.equal(resolved.assistantId, "from-query");
});

test("returns null when neither query nor env contains values", () => {
  const resolved = resolveThreadConnection({
    apiUrlFromQuery: "",
    assistantIdFromQuery: "",
    envApiUrl: "",
    envAssistantId: "",
  });

  assert.equal(resolved.apiUrl, null);
  assert.equal(resolved.assistantId, null);
});

test("uses assistant_id for UUID assistant ids", () => {
  const metadata = getThreadSearchMetadata(
    "123e4567-e89b-12d3-a456-426614174000",
    "device-1",
  );
  assert.deepEqual(metadata, {
    assistant_id: "123e4567-e89b-12d3-a456-426614174000",
    device_id: "device-1",
  });
});

test("uses graph_id for non-UUID assistant ids", () => {
  const metadata = getThreadSearchMetadata("agent", "device-1");
  assert.deepEqual(metadata, { graph_id: "agent", device_id: "device-1" });
});
