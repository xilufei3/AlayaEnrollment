import assert from "node:assert/strict";
import test from "node:test";

test("exports a compact single-line landing hint", async () => {
  const { LANDING_HINT } = await import("./landing-hint.ts");

  assert.ok(LANDING_HINT.trim().length > 0, "landing hint should not be empty");
  assert.equal(
    LANDING_HINT.includes("\n"),
    false,
    "landing hint should stay on a single line",
  );
});
