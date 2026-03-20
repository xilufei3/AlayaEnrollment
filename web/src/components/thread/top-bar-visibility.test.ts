import assert from "node:assert/strict";
import test from "node:test";

test("hides the top bar before the consultation starts", async () => {
  const { shouldShowTopBar } = await import("./top-bar-visibility.ts");

  assert.equal(
    shouldShowTopBar(false),
    false,
    "landing state should not render the top header",
  );
});

test("shows the top bar after the consultation starts", async () => {
  const { shouldShowTopBar } = await import("./top-bar-visibility.ts");

  assert.equal(
    shouldShowTopBar(true),
    true,
    "active consultation state should still render the top header",
  );
});

test("shows a standalone history toggle before the consultation starts", async () => {
  const { shouldShowStandaloneHistoryToggle } = await import(
    "./top-bar-visibility.ts"
  );

  assert.equal(
    shouldShowStandaloneHistoryToggle(false),
    true,
    "landing state should keep a visible entry point for the history sidebar",
  );
});

test("keeps a standalone history toggle after the consultation starts", async () => {
  const { shouldShowStandaloneHistoryToggle } = await import(
    "./top-bar-visibility.ts"
  );

  assert.equal(
    shouldShowStandaloneHistoryToggle(true),
    true,
    "active consultation state should preserve a separate history entry point when the compact header is simplified",
  );
});
