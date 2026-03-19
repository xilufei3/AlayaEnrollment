import { v4 as uuidv4 } from "uuid";
import { FormEvent, ReactNode, useEffect, useRef, useState } from "react";
import { motion } from "framer-motion";
import { Checkpoint, Message } from "@langchain/langgraph-sdk";
import { parseAsBoolean, useQueryState } from "nuqs";
import { toast } from "sonner";
import { StickToBottom, useStickToBottomContext } from "use-stick-to-bottom";
import {
  ArrowDown,
  ChevronRight,
  LoaderCircle,
  PanelRightClose,
  PanelRightOpen,
  ShieldCheck,
  Sparkles,
  SquarePen,
} from "lucide-react";

import { cn } from "@/lib/utils";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { useStreamContext } from "@/providers/Stream";
import {
  DO_NOT_RENDER_ID_PREFIX,
  ensureToolCallsHaveResponses,
} from "@/lib/ensure-tool-responses";

import { AssistantMessage, AssistantMessageLoading } from "./messages/ai";
import { HumanMessage } from "./messages/human";
import ThreadHistory from "./history";
import { TooltipIconButton } from "./tooltip-icon-button";
import { BRAND_COPY, QUICK_PROMPTS } from "./branding";
import { LANDING_HINT } from "./landing-hint";
import {
  shouldShowStandaloneHistoryToggle,
  shouldShowTopBar,
} from "./top-bar-visibility";
import { SustechMark } from "../icons/sustech-mark";
import { Button } from "../ui/button";

function StickyToBottomContent(props: {
  content: ReactNode;
  footer?: ReactNode;
  className?: string;
  contentClassName?: string;
}) {
  const context = useStickToBottomContext();
  return (
    <div
      ref={context.scrollRef}
      style={{ width: "100%", height: "100%" }}
      className={props.className}
    >
      <div ref={context.contentRef} className={props.contentClassName}>
        {props.content}
      </div>

      {props.footer}
    </div>
  );
}

function ScrollToBottom(props: { className?: string }) {
  const { isAtBottom, scrollToBottom } = useStickToBottomContext();

  if (isAtBottom) return null;
  return (
    <Button
      variant="outline"
      className={cn(
        "surface-glass rounded-full border-white/80 px-4 py-2 text-foreground shadow-[0_14px_28px_rgba(24,72,71,0.14)]",
        props.className,
      )}
      onClick={() => scrollToBottom()}
    >
      <ArrowDown className="h-4 w-4" />
      <span>回到底部</span>
    </Button>
  );
}

function LandingHero(props: { onPromptSelect: (question: string) => void }) {
  return (
    <div className="space-y-3 pb-3">
      <motion.section
        initial={{ opacity: 0, y: 18 }}
        animate={{ opacity: 1, y: 0 }}
        transition={{ duration: 0.35 }}
        className="surface-glass rounded-[1.55rem] border border-white/75 px-4 py-3 shadow-[0_16px_36px_rgba(24,72,71,0.09)] sm:px-5"
      >
        <div className="flex items-center gap-3">
          <SustechMark className="h-10 w-10 shrink-0 rounded-2xl" />
          <p className="text-sm leading-6 text-muted-foreground">
            {LANDING_HINT}
          </p>
        </div>
      </motion.section>

      <div className="grid gap-2.5 sm:grid-cols-2 lg:grid-cols-3">
        {QUICK_PROMPTS.map((prompt, index) => (
          <motion.button
            key={prompt.label}
            type="button"
            initial={{ opacity: 0, y: 12 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ delay: 0.05 * index, duration: 0.3 }}
            onClick={() => props.onPromptSelect(prompt.question)}
            className="surface-glass group rounded-[1.15rem] border border-white/75 p-3.5 text-left shadow-[0_10px_22px_rgba(24,72,71,0.08)] transition-all hover:-translate-y-1 hover:shadow-[0_16px_30px_rgba(24,72,71,0.12)]"
          >
            <div className="inline-flex rounded-full border border-primary/10 bg-primary/10 px-2 py-1 text-[10px] font-semibold tracking-[0.12em] text-primary">
              {prompt.label}
            </div>
            <p className="mt-2.5 text-[13px] leading-5 text-foreground/88">
              {prompt.question}
            </p>
            <div className="mt-3 flex items-center gap-1 text-[13px] font-medium text-primary">
              立即提问
              <ChevronRight className="size-4 transition-transform group-hover:translate-x-0.5" />
            </div>
          </motion.button>
        ))}
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
  const [firstTokenReceived, setFirstTokenReceived] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement | null>(null);
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");

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

  return (
    <div className="relative flex h-screen w-full overflow-hidden">
      <div className="relative hidden lg:flex">
        <motion.div
          className="absolute z-20 h-full overflow-hidden"
          style={{ width: 320 }}
          animate={{ x: chatHistoryOpen ? 0 : -320 }}
          initial={{ x: -320 }}
          transition={
            isLargeScreen
              ? { type: "spring", stiffness: 300, damping: 32 }
              : { duration: 0 }
          }
        >
          <div className="relative h-full" style={{ width: 320 }}>
            <ThreadHistory />
          </div>
        </motion.div>
      </div>

      <motion.div
        className="relative flex min-w-0 flex-1 flex-col overflow-hidden"
        layout={isLargeScreen}
        animate={{
          marginLeft: chatHistoryOpen ? (isLargeScreen ? 320 : 0) : 0,
          width: chatHistoryOpen
            ? isLargeScreen
              ? "calc(100% - 320px)"
              : "100%"
            : "100%",
        }}
        transition={
          isLargeScreen
            ? { type: "spring", stiffness: 300, damping: 32 }
            : { duration: 0 }
        }
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

        {shouldShowTopBar(chatStarted) && (
          <div className="relative z-10 px-4 pb-2 pt-4 sm:px-6 lg:px-8">
            <div className="surface-glass mx-auto flex w-full max-w-6xl items-center justify-between gap-3 rounded-[1.85rem] border border-white/70 px-3 py-3 shadow-[0_18px_46px_rgba(24,72,71,0.12)]">
              <div className="flex min-w-0 items-center gap-3">
                {(!chatHistoryOpen || !isLargeScreen) && (
                  <Button
                    className="rounded-full hover:bg-white/80"
                    variant="ghost"
                    onClick={() => setChatHistoryOpen((prev) => !prev)}
                  >
                    {chatHistoryOpen ? (
                      <PanelRightOpen className="size-5" />
                    ) : (
                      <PanelRightClose className="size-5" />
                    )}
                  </Button>
                )}

                <button
                  type="button"
                  className="flex min-w-0 items-center gap-3 text-left"
                  onClick={handleResetThread}
                >
                  <SustechMark className="h-12 w-12 sm:h-14 sm:w-14" />
                  <div className="min-w-0">
                    <p className="text-[11px] uppercase tracking-[0.32em] text-primary/70">
                      SUSTech Admissions
                    </p>
                    <h1 className="truncate font-serif text-xl text-foreground sm:text-2xl">
                      {BRAND_COPY.title}
                    </h1>
                    <p className="hidden truncate text-sm text-muted-foreground md:block">
                      {BRAND_COPY.subtitle}
                    </p>
                  </div>
                </button>
              </div>

              <div className="flex items-center gap-2">
                <div className="hidden items-center gap-2 rounded-full border border-white/70 bg-white/65 px-3 py-2 text-xs text-muted-foreground xl:flex">
                  <Sparkles className="size-3.5 text-[#C9A35D]" />
                  面向高中生与家长的招生咨询入口</div>
                <TooltipIconButton
                  size="lg"
                  className="rounded-full p-4 hover:bg-white/80"
                  tooltip="新建咨询"
                  variant="ghost"
                  onClick={handleResetThread}
                >
                  <SquarePen className="size-5" />
                </TooltipIconButton>
              </div>
            </div>
          </div>
        )}

        <StickToBottom className="relative flex-1 overflow-hidden">
          <StickyToBottomContent
            className={cn(
              "absolute inset-0 overflow-y-scroll px-4 sm:px-6 lg:px-8",
              "[&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-primary/20 [&::-webkit-scrollbar-track]:bg-transparent",
            )}
            contentClassName={cn(
              "mx-auto flex w-full flex-col gap-5 pb-24",
              chatStarted ? "max-w-4xl pt-3" : "max-w-6xl pt-4",
            )}
            content={
              <>
                {!chatStarted && <LandingHero onPromptSelect={handlePromptSelect} />}

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
              <div className="sticky bottom-0 z-10 bg-gradient-to-t from-white via-white/96 to-transparent pb-4 pt-6">
                <div className="mx-auto w-full max-w-5xl">
                  <ScrollToBottom className="absolute bottom-full left-1/2 mb-4 -translate-x-1/2 animate-in fade-in-0 zoom-in-95" />

                  <div className="surface-glass relative overflow-hidden rounded-[2rem] border border-white/80 shadow-[0_24px_60px_rgba(24,72,71,0.12)]">
                    <div className="pointer-events-none absolute inset-x-0 top-0 h-px bg-gradient-to-r from-transparent via-[#C9A35D]/75 to-transparent" />
                    <form onSubmit={handleSubmit} className="grid">
                      <div className="px-5 pt-5 sm:px-6 sm:pt-6">
                        <textarea
                          ref={textareaRef}
                          value={input}
                          onChange={(e) => setInput(e.target.value)}
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
                          className="min-h-[112px] w-full resize-none bg-transparent text-[15px] leading-7 text-foreground shadow-none outline-none placeholder:text-muted-foreground/85 focus:outline-none"
                        />
                      </div>

                      <div className="flex flex-col gap-4 border-t border-border/60 px-5 py-4 sm:flex-row sm:items-end sm:justify-between sm:px-6">
                        <div className="space-y-2">
                          {!chatStarted && (
                            <p className="text-sm font-medium text-foreground">
                              从一个问题开始，我们会帮你更快梳理招生重点。</p>
                          )}
                          <div className="flex items-start gap-2 text-sm leading-6 text-muted-foreground">
                            <ShieldCheck className="mt-1 size-4 shrink-0 text-[#C9A35D]" />
                            <p>{BRAND_COPY.disclaimer}</p>
                          </div>
                        </div>

                        <div className="flex items-center gap-3 self-end sm:self-auto">
                          <span className="hidden text-xs text-muted-foreground md:inline">
                            Enter 发送，Shift + Enter 换行
                          </span>
                          {stream.isLoading ? (
                            <Button
                              key="stop"
                              variant="outline"
                              className="h-11 rounded-full px-5"
                              onClick={() => stream.stop()}
                            >
                              <LoaderCircle className="h-4 w-4 animate-spin" />
                              停止生成
                            </Button>
                          ) : (
                            <Button
                              type="submit"
                              variant="brand"
                              className="h-11 rounded-full px-6 shadow-md"
                              disabled={isLoading || !input.trim()}
                            >
                              发送咨询</Button>
                          )}
                        </div>
                      </div>
                    </form>
                  </div>
                </div>
              </div>
            }
          />
        </StickToBottom>
      </motion.div>
    </div>
  );
}
