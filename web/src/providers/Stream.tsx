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
import { SustechMark } from "@/components/icons/sustech-mark";
import { Label } from "@/components/ui/label";
import { ArrowRight, ShieldCheck } from "lucide-react";
import { getClientHeaders } from "@/lib/device-id";
import { resolveApiUrl } from "@/lib/resolve-api-url";
import { useThreads } from "./Thread";
import { mergeThreadLists, rememberThread } from "./thread-list";
import { toast } from "sonner";
import { BRAND_COPY, CONNECTION_COPY } from "@/components/thread/branding";
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
      <div className="flex min-h-screen w-full items-center justify-center px-4 py-10">
        <div className="surface-glass flex w-full max-w-xl items-center justify-center rounded-[2rem] border border-white/70 px-8 py-12 text-sm text-muted-foreground shadow-[0_24px_80px_rgba(24,72,71,0.12)]">
          Checking backend connection...
        </div>
      </div>
    );
  }

  if (showConnectionForm) {
    return (
      <div className="flex min-h-screen w-full items-center justify-center px-4 py-10">
        <div className="surface-glass animate-in fade-in-0 zoom-in-95 flex w-full max-w-4xl overflow-hidden rounded-[2rem] border border-white/70 shadow-[0_24px_80px_rgba(24,72,71,0.18)]">
          <div className="hidden w-[38%] flex-col justify-between bg-[linear-gradient(160deg,rgba(24,72,71,0.96)_0%,rgba(47,104,104,0.9)_52%,rgba(201,163,93,0.72)_100%)] p-8 text-white lg:flex">
            <div className="space-y-5">
              <SustechMark className="h-16 w-16 border-white/15 bg-white/10 shadow-none" />
              <div className="space-y-3">
                <p className="text-xs tracking-[0.18em] text-white/70">
                  SUSTech Admissions
                </p>
                <h1 className="font-serif text-3xl leading-tight">
                  {BRAND_COPY.title}
                </h1>
                <p className="text-sm leading-6 text-white/78">
                  {BRAND_COPY.subtitle}
                </p>
              </div>
            </div>
            <div className="rounded-[1.5rem] border border-white/15 bg-white/10 p-5">
              <div className="mb-3 flex items-center gap-2 text-sm font-medium">
                <ShieldCheck className="size-4" />
                Connection Settings
              </div>
              <p className="text-sm leading-6 text-white/75">
                Configure the API endpoint and assistant ID used by this browser
                session before starting a conversation.
              </p>
            </div>
          </div>
          <div className="flex-1">
            <div className="border-b border-border/60 px-6 py-7 sm:px-8">
              <div className="mb-4 flex items-center gap-3 lg:hidden">
                <SustechMark className="h-12 w-12" />
                <div className="min-w-0">
                  <p className="text-xs tracking-[0.18em] text-primary/70">
                    SUSTech Admissions
                  </p>
                  <h1 className="font-serif text-2xl text-foreground">
                    {BRAND_COPY.title}
                  </h1>
                </div>
              </div>
              <h2 className="font-serif text-2xl text-foreground">
                {CONNECTION_COPY.title}
              </h2>
              <p className="mt-3 max-w-2xl text-sm leading-6 text-muted-foreground">
                {CONNECTION_COPY.description}
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
              className="grid gap-6 px-6 py-6 sm:px-8 sm:py-8"
            >
              <div className="grid gap-6 lg:grid-cols-2">
                <div className="flex flex-col gap-2">
                  <Label htmlFor="apiUrl">
                    {CONNECTION_COPY.apiUrlLabel}
                    <span className="text-rose-500">*</span>
                  </Label>
                  <p className="text-sm leading-6 text-muted-foreground">
                    {CONNECTION_COPY.apiUrlHint}
                  </p>
                  <Input
                    id="apiUrl"
                    name="apiUrl"
                    className="h-12 rounded-2xl bg-white/70"
                    defaultValue={apiUrl || DEFAULT_API_URL}
                    required
                  />
                </div>

                <div className="flex flex-col gap-2">
                  <Label htmlFor="assistantId">
                    {CONNECTION_COPY.assistantIdLabel}
                    <span className="text-rose-500">*</span>
                  </Label>
                  <p className="text-sm leading-6 text-muted-foreground">
                    {CONNECTION_COPY.assistantIdHint}
                  </p>
                  <Input
                    id="assistantId"
                    name="assistantId"
                    className="h-12 rounded-2xl bg-white/70"
                    defaultValue={assistantId || DEFAULT_ASSISTANT_ID}
                    required
                  />
                </div>
              </div>

              <div className="flex flex-col gap-4 border-t border-border/60 pt-5 sm:flex-row sm:items-center sm:justify-between">
                <p className="max-w-xl text-sm leading-6 text-muted-foreground">
                  The browser now connects through a same-origin BFF route, so no
                  shared API key needs to be entered here.
                </p>
                <Button
                  type="submit"
                  size="lg"
                  variant="brand"
                  className="h-12 rounded-full px-6"
                >
                  {CONNECTION_COPY.submitLabel}
                  <ArrowRight className="size-5" />
                </Button>
              </div>
            </form>
          </div>
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
