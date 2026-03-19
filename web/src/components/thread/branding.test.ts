import assert from "node:assert/strict";
import test from "node:test";

test("exports admissions branding copy", async () => {
  const { BRAND_COPY } = await import("./branding.ts");

  assert.match(
    BRAND_COPY.title,
    /南方科技大学|南科大|SUSTech/i,
    "title should reference SUSTech admissions branding",
  );
  assert.ok(
    BRAND_COPY.subtitle.trim().length > 20,
    "subtitle should explain the assistant's purpose",
  );
  assert.ok(
    BRAND_COPY.historyTitle.trim().length > 0,
    "history title should be defined",
  );
});

test("exports quick prompts with visible labels and prefilled questions", async () => {
  const { QUICK_PROMPTS } = await import("./branding.ts");

  assert.ok(QUICK_PROMPTS.length >= 4, "at least four quick prompts are expected");
  for (const prompt of QUICK_PROMPTS) {
    assert.ok(prompt.label.trim().length > 0, "prompt label should not be empty");
    assert.ok(
      prompt.question.trim().length > 0,
      "prompt question should not be empty",
    );
  }
});

test("exports metadata and setup copy without template branding", async () => {
  const { APP_METADATA, CONNECTION_COPY } = await import("./branding.ts");

  assert.match(
    APP_METADATA.title,
    /南方科技大学|南科大|SUSTech/i,
    "metadata title should be branded for admissions",
  );
  assert.doesNotMatch(
    APP_METADATA.description,
    /Agent Chat|Agent Inbox|LangGraph/i,
    "metadata description should not leak template branding",
  );
  assert.doesNotMatch(
    CONNECTION_COPY.description,
    /Agent Chat|LangGraph/i,
    "setup description should not leak template branding",
  );
});
