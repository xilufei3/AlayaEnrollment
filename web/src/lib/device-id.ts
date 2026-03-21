"use client";

const DEVICE_ID_STORAGE_KEY = "device_id";
let memoryDeviceId: string | null = null;

function createDeviceId(): string {
  if (
    typeof window !== "undefined" &&
    typeof window.crypto?.randomUUID === "function"
  ) {
    return window.crypto.randomUUID();
  }

  return `device-${Math.random().toString(36).slice(2)}-${Date.now().toString(36)}`;
}

function getMemoryDeviceId(): string {
  if (!memoryDeviceId) {
    memoryDeviceId = createDeviceId();
  }
  return memoryDeviceId;
}

export function getDeviceId(): string {
  if (typeof window === "undefined") {
    return createDeviceId();
  }

  try {
    let id = window.localStorage.getItem(DEVICE_ID_STORAGE_KEY);
    if (!id) {
      id = createDeviceId();
      window.localStorage.setItem(DEVICE_ID_STORAGE_KEY, id);
    }
    return id;
  } catch {
    try {
      let id = window.sessionStorage.getItem(DEVICE_ID_STORAGE_KEY);
      if (!id) {
        id = createDeviceId();
        window.sessionStorage.setItem(DEVICE_ID_STORAGE_KEY, id);
      }
      return id;
    } catch {
      return getMemoryDeviceId();
    }
  }
}

export function getClientHeaders(): Record<string, string> {
  return {
    "X-Device-Id": getDeviceId(),
  };
}
