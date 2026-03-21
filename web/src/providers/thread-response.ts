import type { Thread } from "@langchain/langgraph-sdk";

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null;
}

export function isThreadPayload(value: unknown): value is Thread {
  return isRecord(value) && typeof value.thread_id === "string";
}

export function isThreadNotFoundPayload(value: unknown): boolean {
  return isRecord(value) && value.detail === "Thread not found";
}

export function resolveThreadLookupResponse(value: unknown): Thread | null {
  if (isThreadPayload(value)) {
    return value;
  }

  if (isThreadNotFoundPayload(value)) {
    return null;
  }

  throw new Error("Unexpected thread lookup response shape");
}
