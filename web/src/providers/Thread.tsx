import { getApiKey } from "@/lib/api-key";
import { getDeviceId } from "@/lib/device-id";
import { Thread } from "@langchain/langgraph-sdk";
import { useQueryState } from "nuqs";
import {
  createContext,
  useContext,
  ReactNode,
  useCallback,
  useMemo,
  useState,
  useEffect,
  Dispatch,
  SetStateAction,
} from "react";
import { createClient } from "./client";
import {
  buildThreadScopeKey,
  getThreadSearchMetadata,
  resolveThreadConnection,
} from "./thread-query-config";
import { resolveThreadLookupResponse } from "./thread-response";

interface ThreadContextType {
  getThreads: () => Promise<Thread[]>;
  getThread: (threadId: string) => Promise<Thread | null>;
  threads: Thread[];
  setThreads: Dispatch<SetStateAction<Thread[]>>;
  threadsLoading: boolean;
  setThreadsLoading: Dispatch<SetStateAction<boolean>>;
  threadScopeKey: string | null;
}

const ThreadContext = createContext<ThreadContextType | undefined>(undefined);

export function ThreadProvider({ children }: { children: ReactNode }) {
  const [apiUrl] = useQueryState("apiUrl");
  const [assistantId] = useQueryState("assistantId");
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);
  const deviceId = useMemo(() => getDeviceId(), []);
  const { apiUrl: resolvedApiUrl, assistantId: resolvedAssistantId } = useMemo(
    () =>
      resolveThreadConnection({
        apiUrlFromQuery: apiUrl,
        assistantIdFromQuery: assistantId,
        envApiUrl: process.env.NEXT_PUBLIC_API_URL,
        envAssistantId: process.env.NEXT_PUBLIC_ASSISTANT_ID,
      }),
    [apiUrl, assistantId],
  );
  const threadScopeKey = useMemo(
    () =>
      buildThreadScopeKey({
        apiUrl: resolvedApiUrl,
        assistantId: resolvedAssistantId,
        deviceId,
      }),
    [deviceId, resolvedApiUrl, resolvedAssistantId],
  );

  useEffect(() => {
    setThreads([]);
    setThreadsLoading(false);
  }, [threadScopeKey]);

  const getThreads = useCallback(async (): Promise<Thread[]> => {
    if (!resolvedApiUrl || !resolvedAssistantId) return [];

    const client = createClient(resolvedApiUrl, getApiKey() ?? undefined);

    const threads = await client.threads.search({
      metadata: getThreadSearchMetadata(
        resolvedAssistantId,
        deviceId,
      ),
      limit: 100,
    });

    return threads;
  }, [deviceId, resolvedApiUrl, resolvedAssistantId]);

  const getThread = useCallback(
    async (threadId: string): Promise<Thread | null> => {
      if (!resolvedApiUrl || !threadId.trim()) {
        return null;
      }

      const client = createClient(resolvedApiUrl, getApiKey() ?? undefined);
      const payload = await client.threads.get(threadId);
      const thread = resolveThreadLookupResponse(payload);
      if (!thread) {
        return null;
      }

      const graphId = thread.metadata?.graph_id;
      if (
        resolvedAssistantId &&
        typeof graphId === "string" &&
        graphId.trim() &&
        graphId !== resolvedAssistantId
      ) {
        return null;
      }

      return thread;
    },
    [resolvedApiUrl, resolvedAssistantId],
  );

  const value = {
    getThreads,
    getThread,
    threads,
    setThreads,
    threadsLoading,
    setThreadsLoading,
    threadScopeKey,
  };

  return (
    <ThreadContext.Provider value={value}>{children}</ThreadContext.Provider>
  );
}

export function useThreads() {
  const context = useContext(ThreadContext);
  if (context === undefined) {
    throw new Error("useThreads must be used within a ThreadProvider");
  }
  return context;
}
