import assert from "node:assert/strict";
import test from "node:test";

import { shouldShowConnectionForm } from "./stream-connection.ts";

test("shouldShowConnectionForm ignores api_key_required in anonymous bff mode", () => {
  assert.equal(
    shouldShowConnectionForm({
      finalApiUrl: "/api",
      finalAssistantId: "agent",
      connectionInfo: { ok: true, apiKeyRequired: true },
    }),
    false,
  );
});

test("shouldShowConnectionForm still requires api url and assistant id", () => {
  assert.equal(
    shouldShowConnectionForm({
      finalApiUrl: "",
      finalAssistantId: "agent",
      connectionInfo: null,
    }),
    true,
  );
  assert.equal(
    shouldShowConnectionForm({
      finalApiUrl: "/api",
      finalAssistantId: "",
      connectionInfo: { ok: true, apiKeyRequired: false },
    }),
    true,
  );
});
