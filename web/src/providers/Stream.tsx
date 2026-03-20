import React, {
  createContext,
  useContext,
  ReactNode,
  useState,
  useEffect,
  useMemo,
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
import { PasswordInput } from "@/components/ui/password-input";
import { getApiKey } from "@/lib/api-key";
import { getClientHeaders } from "@/lib/device-id";
import { resolveApiUrl } from "@/lib/resolve-api-url";
import { useThreads } from "./Thread";
import { toast } from "sonner";
import { BRAND_COPY, CONNECTION_COPY } from "@/components/thread/branding";

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

async function sleep(ms = 4000) {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

async function checkGraphStatus(
  apiUrl: string,
  apiKey: string | null,
): Promise<boolean> {
  try {
    const res = await fetch(`${apiUrl}/info`, {
      headers: getClientHeaders(apiKey),
    });

    return res.ok;
  } catch (e) {
    console.error(e);
    return false;
  }
}

const StreamSession = ({
  children,
  apiKey,
  apiUrl,
  assistantId,
}: {
  children: ReactNode;
  apiKey: string | null;
  apiUrl: string;
  assistantId: string;
}) => {
  const [threadId, setThreadId] = useQueryState("threadId");
  const { getThreads, setThreads } = useThreads();
  const resolvedApiUrl = resolveApiUrl(apiUrl);
  const defaultHeaders = useMemo(() => getClientHeaders(apiKey), [apiKey]);
  const streamValue = useTypedStream({
    apiUrl: resolvedApiUrl,
    apiKey: apiKey ?? undefined,
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
      setThreadId(id);
      // Refetch threads list when thread ID changes.
      // Wait for some seconds before fetching so we're able to get the new thread that was created.
      sleep().then(() => getThreads().then(setThreads).catch(console.error));
    },
  });

  useEffect(() => {
    checkGraphStatus(resolvedApiUrl, apiKey).then((ok) => {
      if (!ok) {
        toast.error("未能连接招生智能体服务", {
          description: () => (
            <p>
              请确认服务已运行于 <code>{resolvedApiUrl}</code>，并检查当前访问
              密钥与前端环境配置是否正确。
            </p>
          ),
          duration: 10000,
          richColors: true,
          closeButton: true,
        });
      }
    });
  }, [apiKey, resolvedApiUrl, defaultHeaders]);

  return (
    <StreamContext.Provider value={streamValue}>
      {children}
    </StreamContext.Provider>
  );
};

// Default values for the form
const DEFAULT_API_URL = "/api";
const DEFAULT_ASSISTANT_ID = "agent";

export const StreamProvider: React.FC<{ children: ReactNode }> = ({
  children,
}) => {
  // Get environment variables
  const envApiUrl: string | undefined = process.env.NEXT_PUBLIC_API_URL;
  const envAssistantId: string | undefined =
    process.env.NEXT_PUBLIC_ASSISTANT_ID;
  const envApiKey: string | undefined =
    process.env.NEXT_PUBLIC_LANGSMITH_API_KEY;

  // Use URL params with env var fallbacks
  const [apiUrl, setApiUrl] = useQueryState("apiUrl", {
    defaultValue: envApiUrl || "",
  });
  const [assistantId, setAssistantId] = useQueryState("assistantId", {
    defaultValue: envAssistantId || "",
  });

  // For API key, use localStorage with env var fallback
  const [apiKey, _setApiKey] = useState(() => {
    const storedKey = getApiKey();
    return storedKey || envApiKey || "";
  });

  const setApiKey = (key: string) => {
    window.localStorage.setItem("lg:chat:apiKey", key);
    _setApiKey(key);
  };

  // Determine final values to use, prioritizing URL params then env vars
  const finalApiUrl = apiUrl || envApiUrl || DEFAULT_API_URL;
  const finalAssistantId = assistantId || envAssistantId || DEFAULT_ASSISTANT_ID;

  // If we're missing any required values, show the form
  if (!finalApiUrl || !finalAssistantId) {
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
                配置完成后即可进入咨询界面
              </div>
              <p className="text-sm leading-6 text-white/75">
                若本项目已经通过环境变量注入默认值，终端用户通常不会看到这个页面。
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
                const apiUrl = formData.get("apiUrl") as string;
                const assistantId = formData.get("assistantId") as string;
                const apiKey = formData.get("apiKey") as string;

                setApiUrl(apiUrl);
                setApiKey(apiKey);
                setAssistantId(assistantId);

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

              <div className="flex flex-col gap-2">
                <Label htmlFor="apiKey">{CONNECTION_COPY.apiKeyLabel}</Label>
                <p className="text-sm leading-6 text-muted-foreground">
                  {CONNECTION_COPY.apiKeyHint}
                </p>
                <PasswordInput
                  id="apiKey"
                  name="apiKey"
                  defaultValue={apiKey ?? ""}
                  className="h-12 rounded-2xl bg-white/70"
                  placeholder="lsv2_pt_..."
                />
              </div>

              <div className="flex flex-col gap-4 border-t border-border/60 pt-5 sm:flex-row sm:items-center sm:justify-between">
                <p className="max-w-xl text-sm leading-6 text-muted-foreground">
                  页面部署给真实用户前，建议优先通过环境变量写入默认配置，避免访客手动输入服务参数。
                </p>
                <Button type="submit" size="lg" variant="brand" className="h-12 rounded-full px-6">
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
      apiKey={apiKey}
      apiUrl={finalApiUrl}
      assistantId={finalAssistantId}
    >
      {children}
    </StreamSession>
  );
};

// Create a custom hook to use the context
export const useStreamContext = (): StreamContextType => {
  const context = useContext(StreamContext);
  if (context === undefined) {
    throw new Error("useStreamContext must be used within a StreamProvider");
  }
  return context;
};

export default StreamContext;
