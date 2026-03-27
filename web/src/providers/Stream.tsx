import React, {
  createContext,
  useContext,
  ReactNode,
  useState,
  useEffect,
  useMemo,
  useRef,
} from "react";
import { useStream } from "@langchain/langgraph-sdk/react";
import { type Message } from "@langchain/langgraph-sdk";
import {
  uiMessageReducer,
  type UIMessage,
  type RemoveUIMessage,
} from "@langchain/langgraph-sdk/react-ui";
import { useQueryState } from "nuqs";
import { Input } from "@/components/ui/input";
import { Button } from "@/components/ui/button";
import { LangGraphLogoSVG } from "@/components/icons/langgraph";
import { Label } from "@/components/ui/label";
import { ArrowRight } from "lucide-react";
import { getClientHeaders } from "@/lib/device-id";
import { resolveApiUrl } from "@/lib/resolve-api-url";
import { useThreads } from "./Thread";
import { mergeThreadLists, rememberThread } from "./thread-list";
import { toast } from "sonner";
import {
  GraphConnectionInfo,
  shouldShowConnectionForm,
} from "./stream-connection";
import { DEFAULT_API_URL, DEFAULT_ASSISTANT_ID } from "./constants";

export type StateType = { messages: Message[]; ui?: UIMessage[] };

const useTypedStream = useStream<
  StateType,
  {
    UpdateType: {
      messages?: Message[] | Message | string;
      ui?: (UIMessage | RemoveUIMessage)[] | UIMessage | RemoveUIMessage;
    };
    CustomEventType: UIMessage | RemoveUIMessage;
  }
>;

type StreamContextType = ReturnType<typeof useTypedStream>;
const StreamContext = createContext<StreamContextType | undefined>(undefined);

const THREAD_LIST_REFRESH_DELAY_MS = 4000;

async function fetchGraphConnectionInfo(
  apiUrl: string,
): Promise<GraphConnectionInfo> {
  try {
    const res = await fetch(`${apiUrl}/info`, {
      headers: getClientHeaders(),
    });

    if (!res.ok) {
      return { ok: false, apiKeyRequired: false };
    }

    const payload = (await res.json()) as { api_key_required?: boolean } | null;
    return {
      ok: true,
      apiKeyRequired: Boolean(payload?.api_key_required),
    };
  } catch (e) {
    console.error(e);
    return { ok: false, apiKeyRequired: false };
  }
}

function showBackendConnectionToast(apiUrl: string) {
  toast.error("Backend connection failed", {
    description: () => (
      <p>
        Unable to reach <code>{apiUrl}</code>. Check that the FastAPI service is
        running and that the URL is correct.
      </p>
    ),
    duration: 10000,
    richColors: true,
    closeButton: true,
  });
}

const StreamSession = ({
  children,
  apiUrl,
  assistantId,
}: {
  children: ReactNode;
  apiUrl: string;
  assistantId: string;
}) => {
  const [threadId, setThreadId] = useQueryState("threadId");
  const { getThreads, setThreads, threadScopeKey } = useThreads();
  const resolvedApiUrl = resolveApiUrl(apiUrl);
  const defaultHeaders = useMemo(() => getClientHeaders(), []);
  const latestThreadScopeRef = useRef<string | null>(threadScopeKey);
  const previousThreadScopeRef = useRef<string | null>(threadScopeKey);
  const refreshTimerRef = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    latestThreadScopeRef.current = threadScopeKey;
  }, [threadScopeKey]);

  useEffect(() => {
    const previousScopeKey = previousThreadScopeRef.current;
    previousThreadScopeRef.current = threadScopeKey;

    if (previousScopeKey && previousScopeKey !== threadScopeKey) {
      setThreadId(null);
    }
  }, [setThreadId, threadScopeKey]);

  useEffect(() => {
    if (!threadScopeKey && refreshTimerRef.current) {
      clearTimeout(refreshTimerRef.current);
      refreshTimerRef.current = null;
    }
  }, [threadScopeKey]);

  useEffect(() => {
    return () => {
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
        refreshTimerRef.current = null;
      }
    };
  }, []);

  const streamValue = useTypedStream({
    apiUrl: resolvedApiUrl,
    defaultHeaders,
    assistantId,
    threadId: threadId ?? null,
    onCustomEvent: (event, options) => {
      options.mutate((prev) => {
        const ui = uiMessageReducer(prev.ui ?? [], event);
        return { ...prev, ui };
      });
    },
    onThreadId: (id) => {
      const refreshScopeKey = latestThreadScopeRef.current;
      setThreads((prev) => rememberThread(prev, id));
      setThreadId(id);
      if (refreshTimerRef.current) {
        clearTimeout(refreshTimerRef.current);
      }

      // Refetch after the backend has had a chance to persist the new thread.
      refreshTimerRef.current = setTimeout(() => {
        if (!refreshScopeKey || latestThreadScopeRef.current !== refreshScopeKey) {
          return;
        }

        getThreads()
          .then((threads) => {
            if (latestThreadScopeRef.current !== refreshScopeKey) {
              return;
            }

            setThreads((prev) => mergeThreadLists(prev, threads));
          })
          .catch(console.error)
          .finally(() => {
            if (refreshTimerRef.current) {
              refreshTimerRef.current = null;
            }
          });
      }, THREAD_LIST_REFRESH_DELAY_MS);
    },
  });

  return (
    <StreamContext.Provider value={streamValue}>
      {children}
    </StreamContext.Provider>
  );
};

export const StreamProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  const envApiUrl: string | undefined = process.env.NEXT_PUBLIC_API_URL;
  const envAssistantId: string | undefined =
    process.env.NEXT_PUBLIC_ASSISTANT_ID;

  const [apiUrl, setApiUrl] = useQueryState("apiUrl", {
    defaultValue: envApiUrl || "",
  });
  const [assistantId, setAssistantId] = useQueryState("assistantId", {
    defaultValue: envAssistantId || "",
  });
  const [connectionInfo, setConnectionInfo] =
    useState<GraphConnectionInfo | null>(null);

  const finalApiUrl = apiUrl || envApiUrl || DEFAULT_API_URL;
  const finalAssistantId = assistantId || envAssistantId || DEFAULT_ASSISTANT_ID;
  const resolvedFinalApiUrl = resolveApiUrl(finalApiUrl);

  useEffect(() => {
    if (!finalApiUrl || !finalAssistantId) {
      setConnectionInfo(null);
      return;
    }

    let cancelled = false;
    setConnectionInfo(null);

    fetchGraphConnectionInfo(resolvedFinalApiUrl).then((info) => {
      if (cancelled) {
        return;
      }

      setConnectionInfo(info);
      if (!info.ok) {
        showBackendConnectionToast(resolvedFinalApiUrl);
      }
    });

    return () => {
      cancelled = true;
    };
  }, [finalApiUrl, finalAssistantId, resolvedFinalApiUrl]);

  const waitingForConnectionInfo =
    Boolean(finalApiUrl && finalAssistantId) && connectionInfo === null;
  const showConnectionForm = shouldShowConnectionForm({
    finalApiUrl,
    finalAssistantId,
    connectionInfo,
  });

  if (waitingForConnectionInfo) {
    return (
      <div className="flex items-center justify-center min-h-screen w-full p-4">
        <div className="flex items-center justify-center border bg-background shadow-lg rounded-lg max-w-xl px-8 py-12 text-sm text-muted-foreground">
          正在检查服务连接...
        </div>
      </div>
    );
  }

  if (showConnectionForm) {
    return (
      <div className="flex items-center justify-center min-h-screen w-full p-4">
        <div className="animate-in fade-in-0 zoom-in-95 flex flex-col border bg-background shadow-lg rounded-lg max-w-3xl">
          <div className="flex flex-col gap-2 mt-14 p-6 border-b">
            <div className="flex items-start flex-col gap-2">
              <LangGraphLogoSVG className="h-6" />
              <h1 className="text-xl font-semibold tracking-tight text-foreground">
                研究生招生智能体
              </h1>
            </div>
            <p className="text-muted-foreground">
              欢迎使用研究生招生智能体。请配置服务地址和助手 ID 以开始使用。
            </p>
          </div>
          <form
            onSubmit={(e) => {
              e.preventDefault();

              const form = e.target as HTMLFormElement;
              const formData = new FormData(form);
              const nextApiUrl = formData.get("apiUrl") as string;
              const nextAssistantId = formData.get("assistantId") as string;

              setApiUrl(nextApiUrl);
              setAssistantId(nextAssistantId);

              form.reset();
            }}
            className="flex flex-col gap-6 p-6 bg-muted/50"
          >
            <div className="flex flex-col gap-2">
              <Label htmlFor="apiUrl">
                Deployment URL<span className="text-rose-500">*</span>
              </Label>
              <p className="text-muted-foreground text-sm">
                This is the URL of your LangGraph deployment. Can be a local, or
                production deployment.
              </p>
              <Input
                id="apiUrl"
                name="apiUrl"
                className="bg-background"
                defaultValue={apiUrl || DEFAULT_API_URL}
                required
              />
            </div>

            <div className="flex flex-col gap-2">
              <Label htmlFor="assistantId">
                Assistant / Graph ID<span className="text-rose-500">*</span>
              </Label>
              <p className="text-muted-foreground text-sm">
                This is the ID of the graph (can be the graph name), or
                assistant to fetch threads from, and invoke when actions are
                taken.
              </p>
              <Input
                id="assistantId"
                name="assistantId"
                className="bg-background"
                defaultValue={assistantId || DEFAULT_ASSISTANT_ID}
                required
              />
            </div>

            <div className="flex justify-end mt-2">
              <Button type="submit" size="lg">
                Continue
                <ArrowRight className="size-5" />
              </Button>
            </div>
          </form>
        </div>
      </div>
    );
  }

  return (
    <StreamSession
      apiUrl={finalApiUrl}
      assistantId={finalAssistantId}
    >
      {children}
    </StreamSession>
  );
};

export const useStreamContext = (): StreamContextType => {
  const context = useContext(StreamContext);
  if (context === undefined) {
    throw new Error("useStreamContext must be used within a StreamProvider");
  }
  return context;
};

export default StreamContext;
