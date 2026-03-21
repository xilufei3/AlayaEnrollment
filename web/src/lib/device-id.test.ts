import assert from "node:assert/strict";
import test from "node:test";

import { getClientHeaders, getDeviceId } from "./device-id.ts";

function createStorage() {
  const store = new Map<string, string>();
  return {
    getItem(key: string) {
      return store.has(key) ? store.get(key)! : null;
    },
    setItem(key: string, value: string) {
      store.set(key, value);
    },
  };
}

test("getClientHeaders only includes x-device-id for browser requests", () => {
  const headers = getClientHeaders();

  assert.equal(typeof headers["X-Device-Id"], "string");
  assert.equal("X-Api-Key" in headers, false);
});

test("getDeviceId reuses the stored device id in a browser-like environment", () => {
  const originalWindow = globalThis.window;
  const localStorage = createStorage();
  const sessionStorage = createStorage();
  const fakeWindow = {
    crypto: {
      randomUUID: () => "device-fixed",
    },
    localStorage,
    sessionStorage,
  } as unknown as Window & typeof globalThis;

  Object.defineProperty(globalThis, "window", {
    configurable: true,
    value: fakeWindow,
  });

  try {
    const first = getDeviceId();
    const second = getDeviceId();

    assert.equal(first, "device-fixed");
    assert.equal(second, "device-fixed");
    assert.equal(localStorage.getItem("device_id"), "device-fixed");
  } finally {
    Object.defineProperty(globalThis, "window", {
      configurable: true,
      value: originalWindow,
    });
  }
});
