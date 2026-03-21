import type { Thread } from "@langchain/langgraph-sdk";

function compareByUpdatedAtDesc(left: Thread, right: Thread): number {
  return String(right.updated_at ?? "").localeCompare(
    String(left.updated_at ?? ""),
  );
}

export function createOptimisticThread(threadId: string): Thread {
  const now = new Date().toISOString();
  return {
    thread_id: threadId,
    created_at: now,
    updated_at: now,
    metadata: {},
    status: "idle",
    values: {},
    interrupts: {},
  };
}

export function rememberThread(threads: Thread[], threadId: string): Thread[] {
  const optimisticThread = createOptimisticThread(threadId);
  const existingThread = threads.find((thread) => thread.thread_id === threadId);
  const nextThread = existingThread
    ? {
        ...existingThread,
        updated_at: optimisticThread.updated_at,
      }
    : optimisticThread;

  return [
    nextThread,
    ...threads.filter((thread) => thread.thread_id !== threadId),
  ];
}

export function mergeThreadLists(
  currentThreads: Thread[],
  incomingThreads: Thread[],
): Thread[] {
  const merged = new Map<string, Thread>();

  for (const thread of currentThreads) {
    merged.set(thread.thread_id, thread);
  }

  for (const thread of incomingThreads) {
    const existing = merged.get(thread.thread_id);
    if (!existing) {
      merged.set(thread.thread_id, thread);
      continue;
    }

    merged.set(thread.thread_id, {
      ...existing,
      ...thread,
      created_at: existing.created_at || thread.created_at,
      updated_at:
        String(existing.updated_at ?? "").localeCompare(
          String(thread.updated_at ?? ""),
        ) >= 0
          ? existing.updated_at
          : thread.updated_at,
    });
  }

  return Array.from(merged.values()).sort(compareByUpdatedAtDesc);
}
