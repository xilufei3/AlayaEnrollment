"use client";

const DEVICE_ID_STORAGE_KEY = "device_id";

function createDeviceId(): string {
  if (
    typeof window !== "undefined" &&
    typeof window.crypto?.randomUUID === "function"
  ) {
    return window.crypto.randomUUID();
  }

  return `device-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

export function getDeviceId(): string {
  if (typeof window === "undefined") {
    return "anonymous";
  }

  try {
    let id = window.localStorage.getItem(DEVICE_ID_STORAGE_KEY);
    if (!id) {
      id = createDeviceId();
      window.localStorage.setItem(DEVICE_ID_STORAGE_KEY, id);
    }
    return id;
  } catch {
    return "anonymous";
  }
}

export function getClientHeaders(
  apiKey?: string | null,
): Record<string, string> {
  const headers: Record<string, string> = {
    "X-Device-Id": getDeviceId(),
  };

  if (apiKey) {
    headers["X-Api-Key"] = apiKey;
  }

  return headers;
}
