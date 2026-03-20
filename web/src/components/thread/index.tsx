import { v4 as uuidv4 } from "uuid";
import {
  FormEvent,
  ReactNode,
  CSSProperties,
  useEffect,
  useRef,
  useState,
} from "react";
import { AnimatePresence, motion } from "framer-motion";
import { Checkpoint, Message } from "@langchain/langgraph-sdk";
import { parseAsBoolean, useQueryState } from "nuqs";
import { toast } from "sonner";
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import {
  ArrowDown,
  ChevronRight,
  FileText,
  GraduationCap,
  House,
  LoaderCircle,
  MapPinned,
  Microscope,
  PanelRightClose,
  PanelRightOpen,
  Rocket,
  SendHorizontal,
  ShieldCheck,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useStreamContext } from "@/providers/Stream";
import {
  DO_NOT_RENDER_ID_PREFIX,
  ensureToolCallsHaveResponses,
} from "@/lib/ensure-tool-responses";

import { AssistantMessage, AssistantMessageLoading } from "./messages/ai";
import { ThreadHeader } from "./header";
import { HumanMessage } from "./messages/human";
import ThreadHistory from "./history";
import { TooltipIconButton } from "./tooltip-icon-button";
import { BRAND_COPY, QUICK_PROMPTS } from "./branding";
import {
  shouldShowStandaloneHistoryToggle,
} from "./top-bar-visibility";
import { Button } from "../ui/button";

const PROMPT_THEMES = [
  {
    accent: "#1D9E75",
    chipBackground: "rgba(29, 158, 117, 0.12)",
    chipColor: "#166e56",
    hintColor: "rgba(24, 72, 71, 0.72)",
    background:
      "linear-gradient(180deg, rgba(239, 249, 244, 0.98) 0%, rgba(255, 255, 255, 0.96) 100%)",
    borderColor: "rgba(29, 158, 117, 0.18)",
    shadow: "0 24px 48px rgba(29, 158, 117, 0.18)",
    icon: FileText,
  },
  {
    accent: "#3B82F6",
    chipBackground: "rgba(59, 130, 246, 0.12)",
    chipColor: "#1d5fcb",
    hintColor: "rgba(33, 72, 135, 0.72)",
    background:
      "linear-gradient(180deg, rgba(240, 246, 255, 0.98) 0%, rgba(255, 255, 255, 0.96) 100%)",
    borderColor: "rgba(59, 130, 246, 0.16)",
    shadow: "0 24px 48px rgba(59, 130, 246, 0.16)",
    icon: GraduationCap,
  },
  {
    accent: "#D39A2C",
    chipBackground: "rgba(211, 154, 44, 0.13)",
    chipColor: "#a86a00",
    hintColor: "rgba(120, 83, 16, 0.75)",
    background:
      "linear-gradient(180deg, rgba(255, 248, 232, 0.98) 0%, rgba(255, 255, 255, 0.96) 100%)",
    borderColor: "rgba(211, 154, 44, 0.17)",
    shadow: "0 24px 48px rgba(211, 154, 44, 0.15)",
    icon: House,
  },
  {
    accent: "#7C5CFC",
    chipBackground: "rgba(124, 92, 252, 0.12)",
    chipColor: "#5d3ee0",
    hintColor: "rgba(83, 55, 160, 0.74)",
    background:
      "linear-gradient(180deg, rgba(246, 243, 255, 0.98) 0%, rgba(255, 255, 255, 0.96) 100%)",
    borderColor: "rgba(124, 92, 252, 0.16)",
    shadow: "0 24px 48px rgba(124, 92, 252, 0.14)",
    icon: Microscope,
  },
  {
    accent: "#D64A8B",
    chipBackground: "rgba(214, 74, 139, 0.12)",
    chipColor: "#b73170",
    hintColor: "rgba(132, 44, 87, 0.72)",
    background:
      "linear-gradient(180deg, rgba(255, 243, 249, 0.98) 0%, rgba(255, 255, 255, 0.96) 100%)",
    borderColor: "rgba(214, 74, 139, 0.16)",
    shadow: "0 24px 48px rgba(214, 74, 139, 0.14)",
    icon: MapPinned,
  },
  {
    accent: "#0F766E",
    chipBackground: "rgba(15, 118, 110, 0.13)",
    chipColor: "#0d5e58",
    hintColor: "rgba(14, 88, 82, 0.76)",
    background:
      "linear-gradient(180deg, rgba(236, 248, 247, 0.98) 0%, rgba(255, 255, 255, 0.96) 100%)",
    borderColor: "rgba(15, 118, 110, 0.17)",
    shadow: "0 24px 48px rgba(15, 118, 110, 0.14)",
    icon: Rocket,
  },
] as const;

const HISTORY_PANEL_WIDTH = 320;

function StickyToBottomContent(props: {
  content: ReactNode;
  footer?: ReactNode;
  className?: string;
  contentClassName?: string;
  contentStyle?: CSSProperties;
}) {
  const context = useStickToBottomContext();
  return (
    <div
      ref={context.scrollRef}
      style={{ width: "100%", height: "100%" }}
      className={props.className}
    >
      <div
        ref={context.contentRef}
        className={props.contentClassName}
        style={props.contentStyle}
      >
        {props.content}
      </div>

      {props.footer}
    </div>
  );
}

function ScrollToBottom(props: { className?: string; style?: CSSProperties }) {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();

  if (isAtBottom) return null;
  return (
    <Button
      variant="outline"
      className={cn(
        "surface-glass rounded-full border-white/80 px-4 py-2 text-foreground shadow-[0_14px_28px_rgba(24,72,71,0.14)]",
        props.className,
      )}
      style={props.style}
      onClick={() => scrollToBottom()}
    >
      <ArrowDown className="h-4 w-4" />
      <span>回到底部</span>
    </Button>
  );
}

function LandingHero(props: { onPromptSelect: (question: string) => void }) {
  return (
    <div className="space-y-5 pb-4">
      <div className="flex items-center justify-between gap-4 px-1">
        <p className="text-sm font-semibold tracking-[0.18em] text-foreground/88">
          热门问题
        </p>
      </div>

      <div className="grid items-stretch gap-3 sm:grid-cols-2 sm:auto-rows-fr lg:grid-cols-3 lg:grid-rows-2">
        {QUICK_PROMPTS.map((prompt, index) => {
          const theme = PROMPT_THEMES[index % PROMPT_THEMES.length];
          const Icon = theme.icon;

          return (
            <motion.button
              key={prompt.label}
              type="button"
              initial={{ opacity: 0, y: 12 }}
              animate={{ opacity: 1, y: 0 }}
              transition={{ delay: 0.05 * index, duration: 0.3 }}
              whileHover={{
                y: -2,
                boxShadow: theme.shadow,
              }}
              onClick={() => props.onPromptSelect(prompt.question)}
              className="group relative h-full overflow-hidden rounded-[1.35rem] border p-4 text-left transition-all duration-300 focus-visible:outline-none focus-visible:ring-4 focus-visible:ring-[#1D9E75]/15"
              style={{
                background: theme.background,
                borderColor: theme.borderColor,
                boxShadow: "0 10px 24px rgba(24, 72, 71, 0.07)",
              }}
            >
              <span className="absolute bottom-4 left-0 top-4 flex w-1 items-center">
                <span
                  className="h-full w-full origin-center rounded-r-full scale-y-[0.42] transition-transform duration-300 group-hover:scale-y-100"
                  style={{ background: theme.accent }}
                />
              </span>
              <div className="relative flex h-full flex-col">
                <div className="flex items-start justify-between gap-3">
                  <div
                    className="inline-flex items-center gap-2 rounded-full px-3 py-1.5 text-[11px] font-semibold tracking-[0.12em]"
                    style={{
                      background: theme.chipBackground,
                      color: theme.chipColor,
                    }}
                  >
                    <Icon className="size-3.5" />
                    {prompt.label}
                  </div>
                  <span className="text-[11px] text-muted-foreground">
                    热门咨询
                  </span>
                </div>

                <div className="mt-4 flex flex-1 flex-col">
                  <p
                    className="text-[15px] font-medium leading-7 text-foreground sm:text-base"
                    style={{
                      display: "-webkit-box",
                      overflow: "hidden",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                    }}
                  >
                    {prompt.question}
                  </p>
                  <p
                    className="mt-2 text-[13px] leading-6"
                    style={{
                      color: theme.hintColor,
                      display: "-webkit-box",
                      overflow: "hidden",
                      WebkitLineClamp: 2,
                      WebkitBoxOrient: "vertical",
                    }}
                  >
                    {prompt.hint}
                  </p>
                </div>

                <div className="mt-auto flex items-center justify-end gap-3 pt-4">
                  <div
                    className="flex items-center gap-1.5 text-[13px] font-semibold"
                    style={{ color: theme.accent }}
                  >
                    立即提问
                    <ChevronRight className="size-4 transition-transform group-hover:translate-x-0.5" />
                  </div>
                </div>
              </div>
            </motion.button>
          );
        })}
      </div>
    </div>
  );
}

export function Thread() {
  const [threadId, setThreadId] = useQueryState("threadId");
  const [chatHistoryOpen, setChatHistoryOpen] = useQueryState(
    "chatHistoryOpen",
    parseAsBoolean.withDefault(false),
  );
  const [input, setInput] = useState("");
  const [composerFocused, setComposerFocused] = useState(false);
  const [firstTokenReceived, setFirstTokenReceived] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const composerDockRef = useRef<HTMLDivElement | null>(null);
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");
  const [composerHeight, setComposerHeight] = useState(260);

  const stream = useStreamContext();
  const messages = stream.messages;
  const isLoading = stream.isLoading;

  const lastError = useRef<string | undefined>(undefined);

  useEffect(() => {
    if (!stream.error) {
      lastError.current = undefined;
      return;
    }
    try {
      const message = (stream.error as { message?: string }).message;
      if (!message || lastError.current === message) {
        return;
      }

      lastError.current = message;
      toast.error("Message failed to send. Please try again shortly.", {
        description: (
          <p>
            <strong>Error:</strong> <code>{message}</code>
          </p>
        ),
        richColors: true,
        closeButton: true,
      });
    } catch {
      // no-op
    }
  }, [stream.error]);

  const prevMessageLength = useRef(0);
  useEffect(() => {
    if (
      messages.length !== prevMessageLength.current &&
      messages.length &&
      messages[messages.length - 1].type === "ai"
    ) {
      setFirstTokenReceived(true);
    }

    prevMessageLength.current = messages.length;
  }, [messages]);

  const handleSubmit = (e: FormEvent) => {
    e.preventDefault();
    if (!input.trim() || isLoading) return;
    setFirstTokenReceived(false);

    const newHumanMessage: Message = {
      id: uuidv4(),
      type: "human",
      content: input.trim(),
    };

    const toolMessages = ensureToolCallsHaveResponses(stream.messages);
    stream.submit(
      { messages: [...toolMessages, newHumanMessage] },
      {
        streamMode: ["values", "messages"],
        optimisticValues: (prev) => ({
          ...prev,
          messages: [
            ...(prev.messages ?? []),
            ...toolMessages,
            newHumanMessage,
          ],
        }),
      },
    );

    setInput("");
  };

  const handleRegenerate = (
    parentCheckpoint: Checkpoint | null | undefined,
  ) => {
    prevMessageLength.current = prevMessageLength.current - 1;
    setFirstTokenReceived(false);
    stream.submit(undefined, {
      checkpoint: parentCheckpoint,
      streamMode: ["values", "messages"],
    });
  };

  const handlePromptSelect = (question: string) => {
    setInput(question);
    requestAnimationFrame(() => textareaRef.current?.focus());
  };

  const handleResetThread = () => {
    setThreadId(null);
    setInput("");
  };

  const chatStarted = !!threadId || !!messages.length;
  const showStandaloneHistoryToggle =
    shouldShowStandaloneHistoryToggle(chatStarted);
  const hasNoAIOrToolMessages = !messages.find(
    (m) => m.type === "ai" || m.type === "tool",
  );
  const composerInsetLeft = isLargeScreen && chatHistoryOpen ? 320 : 0;
  const historyPanelTransition = isLargeScreen
    ? { type: "spring", stiffness: 300, damping: 32 }
    : { duration: 0 };
  const contentCenterOffset =
    isLargeScreen && chatHistoryOpen ? HISTORY_PANEL_WIDTH / 2 : 0;
  const reservedComposerSpace = Math.max(
    composerHeight + 28,
    chatStarted ? 220 : 310,
  );

  useEffect(() => {
    const node = composerDockRef.current;
    if (!node) return;

    const updateHeight = () => {
      setComposerHeight(Math.ceil(node.getBoundingClientRect().height));
    };

    updateHeight();

    if (typeof ResizeObserver === "undefined") {
      return;
    }

    const observer = new ResizeObserver(() => updateHeight());
    observer.observe(node);

    return () => observer.disconnect();
  }, [chatHistoryOpen, chatStarted]);

  return (
    <div className="relative flex h-screen w-full overflow-hidden">
      <div className="relative hidden lg:flex">
        <motion.div
          className="absolute z-20 h-full overflow-hidden"
          style={{ width: HISTORY_PANEL_WIDTH }}
          animate={{ x: chatHistoryOpen ? 0 : -HISTORY_PANEL_WIDTH }}
          initial={{ x: -HISTORY_PANEL_WIDTH }}
          transition={historyPanelTransition}
        >
          <div
            className="relative h-full"
            style={{ width: HISTORY_PANEL_WIDTH }}
          >
            <ThreadHistory />
          </div>
        </motion.div>
      </div>

      <motion.div
        className="relative flex min-w-0 flex-1 flex-col overflow-hidden"
        layout={isLargeScreen}
        animate={{
          marginLeft: chatHistoryOpen ? (isLargeScreen ? HISTORY_PANEL_WIDTH : 0) : 0,
          width: chatHistoryOpen
            ? isLargeScreen
              ? `calc(100% - ${HISTORY_PANEL_WIDTH}px)`
              : "100%"
            : "100%",
        }}
        transition={historyPanelTransition}
      >
        {showStandaloneHistoryToggle && (
          <div className="pointer-events-none absolute left-4 top-4 z-20 sm:left-6 lg:left-8">
            <TooltipIconButton
              size="lg"
              side="right"
              tooltip={chatHistoryOpen ? "Hide history" : "Show history"}
              variant="ghost"
              className="pointer-events-auto size-11 rounded-full border border-white/80 bg-white/82 p-0 shadow-[0_14px_32px_rgba(24,72,71,0.14)] backdrop-blur hover:bg-white"
              onClick={() => setChatHistoryOpen((prev) => !prev)}
            >
              {chatHistoryOpen ? (
                <PanelRightOpen className="size-5" />
              ) : (
                <PanelRightClose className="size-5" />
              )}
            </TooltipIconButton>
          </div>
        )}

        <ThreadHeader
          variant={chatStarted ? "chat" : "landing"}
          onResetThread={handleResetThread}
          className={cn(
            "relative z-10",
            chatStarted
              ? "px-[4.5rem] pb-2 pt-4 sm:px-[5.5rem] sm:pb-2 lg:px-8"
              : "px-4 pb-3 pt-4 sm:px-6 lg:px-8",
          )}
        />

        <StickToBottom className="relative flex-1 overflow-hidden">
          <StickyToBottomContent
            className={cn(
              "absolute inset-0 overflow-y-scroll px-4 sm:px-6 lg:px-8",
              "[&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-primary/20 [&::-webkit-scrollbar-track]:bg-transparent",
            )}
            contentClassName={cn(
              "mx-auto flex w-full flex-col gap-5",
              chatStarted ? "max-w-4xl pt-3" : "max-w-4xl pt-4",
            )}
            contentStyle={{ paddingBottom: reservedComposerSpace }}
            content={
              <>
                <AnimatePresence initial={false}>
                  {!chatStarted && (
                    <motion.div
                      key="landing-shell"
                      initial={{ opacity: 1, height: "auto" }}
                      animate={{ opacity: 1, height: "auto" }}
                      exit={{ opacity: 0, height: 0, marginBottom: 0 }}
                      transition={{ duration: 0.22, ease: "easeInOut" }}
                      className="overflow-hidden"
                    >
                      <LandingHero onPromptSelect={handlePromptSelect} />
                    </motion.div>
                  )}
                </AnimatePresence>

                {messages
                  .filter((m) => !m.id?.startsWith(DO_NOT_RENDER_ID_PREFIX))
                  .map((message, index) =>
                    message.type === "human" ? (
                      <HumanMessage
                        key={message.id || `${message.type}-${index}`}
                        message={message}
                        isLoading={isLoading}
                      />
                    ) : (
                      <AssistantMessage
                        key={message.id || `${message.type}-${index}`}
                        message={message}
                        isLoading={isLoading}
                        handleRegenerate={handleRegenerate}
                      />
                    ),
                  )}

                {hasNoAIOrToolMessages && !!stream.interrupt && (
                  <AssistantMessage
                    key="interrupt-msg"
                    message={undefined}
                    isLoading={isLoading}
                    handleRegenerate={handleRegenerate}
                  />
                )}

                {isLoading && !firstTokenReceived && (
                  <AssistantMessageLoading />
                )}
              </>
            }
            footer={
              <ScrollToBottom
                className="fixed left-1/2 z-30 -translate-x-1/2 animate-in fade-in-0 zoom-in-95"
                style={{
                  bottom: composerHeight + 24,
                  marginLeft: contentCenterOffset,
                }}
              />
            }
          />
        </StickToBottom>

        <motion.div
          initial={false}
          className="pointer-events-none fixed bottom-0 right-0 z-20"
          animate={{ left: composerInsetLeft }}
          transition={historyPanelTransition}
        >
          <div className="bg-gradient-to-t from-[#f7f2e8] via-[#faf7f0]/96 to-transparent px-4 pb-4 pt-6 sm:px-6 lg:px-8">
            <div className="relative mx-auto w-full max-w-4xl">
              <div ref={composerDockRef} className="pointer-events-auto">
                {!chatStarted && (
                  <div className="mb-4 flex items-center gap-4 px-2">
                    <div className="h-px flex-1 bg-gradient-to-r from-transparent via-[#1D9E75]/28 to-[#1D9E75]/6" />
                    <span className="text-sm font-medium text-muted-foreground">
                      或直接输入你的问题
                    </span>
                    <div className="h-px flex-1 bg-gradient-to-l from-transparent via-[#1D9E75]/28 to-[#1D9E75]/6" />
                  </div>
                )}

                <div
                  className="surface-glass relative overflow-hidden rounded-[2rem] border transition-all duration-300"
                  style={{
                    borderColor: composerFocused
                      ? "rgba(29, 158, 117, 0.36)"
                      : "rgba(255, 255, 255, 0.82)",
                    boxShadow: composerFocused
                      ? "0 0 0 4px rgba(29, 158, 117, 0.11), 0 28px 60px rgba(29, 158, 117, 0.16)"
                      : "0 24px 60px rgba(24, 72, 71, 0.12)",
                  }}
                >
                  <div className="pointer-events-none absolute -right-10 top-0 h-28 w-28 rounded-full bg-[radial-gradient(circle,rgba(29,158,117,0.15),transparent_72%)]" />
                  <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#C9A35D]/75 to-transparent" />
                  <form onSubmit={handleSubmit} className="grid">
                    <div className="px-5 pt-5 sm:px-6 sm:pt-6">
                      <textarea
                        ref={textareaRef}
                        value={input}
                        onChange={(e) => setInput(e.target.value)}
                        onFocus={() => setComposerFocused(true)}
                        onBlur={() => setComposerFocused(false)}
                        onKeyDown={(e) => {
                          if (
                            e.key === "Enter" &&
                            !e.shiftKey &&
                            !e.metaKey &&
                            !e.nativeEvent.isComposing
                          ) {
                            e.preventDefault();
                            const el = e.target as HTMLElement | undefined;
                            const form = el?.closest("form");
                            form?.requestSubmit();
                          }
                        }}
                        placeholder={BRAND_COPY.composerPlaceholder}
                        className="min-h-[112px] w-full resize-none bg-transparent text-[15px] leading-7 text-foreground shadow-none outline-none placeholder:text-[15px] placeholder:text-muted-foreground/85 focus:outline-none"
                      />
                    </div>

                    <div className="flex flex-col gap-4 border-t border-[#1D9E75]/10 px-5 py-4 sm:flex-row sm:items-end sm:justify-between sm:px-6">
                      <div className="space-y-2">
                        <div className="flex items-start gap-2 text-sm leading-6 text-muted-foreground">
                          <ShieldCheck className="mt-1 size-4 shrink-0 text-[#C9A35D]" />
                          <p>{BRAND_COPY.disclaimer}</p>
                        </div>
                      </div>

                      <div className="flex items-center gap-3 self-end sm:self-auto">
                        {stream.isLoading ? (
                          <Button
                            key="stop"
                            variant="outline"
                            className="h-11 rounded-full border-[#1D9E75]/18 bg-white/80 px-5 text-foreground shadow-[0_12px_24px_rgba(24,72,71,0.08)]"
                            onClick={() => stream.stop()}
                          >
                            <LoaderCircle className="h-4 w-4 animate-spin" />
                            停止生成
                          </Button>
                        ) : (
                          <Button
                            type="submit"
                            variant="brand"
                            className="h-11 rounded-full px-6"
                            disabled={isLoading || !input.trim()}
                          >
                            <SendHorizontal className="size-4" />
                            发送咨询
                          </Button>
                        )}
                      </div>
                    </div>
                  </form>
                </div>
              </div>
            </div>
          </div>
        </motion.div>
      </motion.div>
    </div>
  );
}
