import assert from "node:assert/strict";
import test from "node:test";

import {
  mergeThreadLists,
  rememberThread,
} from "./thread-list.ts";

function makeThread(
  threadId: string,
  updatedAt: string,
  values: Record<string, unknown> = {},
) {
  return {
    thread_id: threadId,
    created_at: updatedAt,
    updated_at: updatedAt,
    metadata: {},
    status: "idle" as const,
    values,
    interrupts: {},
  };
}

test("rememberThread adds a newly created thread to the front of the local list", () => {
  const threads = [makeThread("older-thread", "2026-03-20T08:00:00.000Z")];

  const remembered = rememberThread(threads, "new-thread");

  assert.equal(remembered[0]?.thread_id, "new-thread");
  assert.equal(
    remembered.some((thread) => thread.thread_id === "older-thread"),
    true,
  );
});

test("mergeThreadLists preserves an optimistic thread when search results are stale", () => {
  const optimisticThreads = rememberThread([], "new-thread");
  const staleSearchResults = [
    makeThread("existing-thread", "2026-03-20T08:00:00.000Z"),
  ];

  const merged = mergeThreadLists(optimisticThreads, staleSearchResults);

  assert.deepEqual(
    merged.map((thread) => thread.thread_id),
    ["new-thread", "existing-thread"],
  );
});

test("mergeThreadLists uses fetched thread details once the backend catches up", () => {
  const optimisticThreads = rememberThread([], "new-thread");
  const fetchedThreads = [
    makeThread("new-thread", "2026-03-21T09:00:00.000Z", {
      messages: [{ type: "human", content: "How do I apply?" }],
    }),
  ];

  const merged = mergeThreadLists(optimisticThreads, fetchedThreads);
  const matched = merged.find((thread) => thread.thread_id === "new-thread");

  assert.ok(matched, "merged list should still contain the new thread");
  assert.deepEqual(matched?.values, fetchedThreads[0]?.values);
});
