import { getApiKey } from "@/lib/api-key";
import { getDeviceId } from "@/lib/device-id";
import { Thread } from "@langchain/langgraph-sdk";
import { useQueryState } from "nuqs";
import {
  createContext,
  useContext,
  ReactNode,
  useCallback,
  useState,
  Dispatch,
  SetStateAction,
} from "react";
import { createClient } from "./client";
import {
  getThreadSearchMetadata,
  resolveThreadConnection,
} from "./thread-query-config";

interface ThreadContextType {
  getThreads: () => Promise<Thread[]>;
  threads: Thread[];
  setThreads: Dispatch<SetStateAction<Thread[]>>;
  threadsLoading: boolean;
  setThreadsLoading: Dispatch<SetStateAction<boolean>>;
}

const ThreadContext = createContext<ThreadContextType | undefined>(undefined);

export function ThreadProvider({ children }: { children: ReactNode }) {
  const [apiUrl] = useQueryState("apiUrl");
  const [assistantId] = useQueryState("assistantId");
  const [threads, setThreads] = useState<Thread[]>([]);
  const [threadsLoading, setThreadsLoading] = useState(false);

  const getThreads = useCallback(async (): Promise<Thread[]> => {
    const { apiUrl: resolvedApiUrl, assistantId: resolvedAssistantId } =
      resolveThreadConnection({
        apiUrlFromQuery: apiUrl,
        assistantIdFromQuery: assistantId,
        envApiUrl: process.env.NEXT_PUBLIC_API_URL,
        envAssistantId: process.env.NEXT_PUBLIC_ASSISTANT_ID,
      });

    if (!resolvedApiUrl || !resolvedAssistantId) return [];

    const client = createClient(resolvedApiUrl, getApiKey() ?? undefined);

    const threads = await client.threads.search({
      metadata: getThreadSearchMetadata(
        resolvedAssistantId,
        getDeviceId(),
      ),
      limit: 100,
    });

    return threads;
  }, [apiUrl, assistantId]);

  const value = {
    getThreads,
    threads,
    setThreads,
    threadsLoading,
    setThreadsLoading,
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
