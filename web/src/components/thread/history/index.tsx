import { Button } from "@/components/ui/button";
import { useThreads } from "@/providers/Thread";
import { Thread } from "@langchain/langgraph-sdk";
import { useEffect, useState } from "react";

import { getContentString } from "../utils";
import { useQueryState, parseAsBoolean } from "nuqs";
import {
  Sheet,
  SheetContent,
  SheetHeader,
  SheetTitle,
} from "@/components/ui/sheet";
import { Skeleton } from "@/components/ui/skeleton";
import { PanelRightOpen, PanelRightClose } from "lucide-react";
import { useMediaQuery } from "@/hooks/useMediaQuery";
import { BRAND_COPY } from "../branding";
import { SustechMark } from "@/components/icons/sustech-mark";
import { cn } from "@/lib/utils";
import { mergeThreadLists } from "@/providers/thread-list";

function ThreadList({
  threads,
  onThreadClick,
}: {
  threads: Thread[];
  onThreadClick?: (threadId: string) => void;
}) {
  const [threadId, setThreadId] = useQueryState("threadId");

  return (
    <div className="h-full flex flex-col w-full gap-2 items-start justify-start overflow-y-scroll [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-gray-300 [&::-webkit-scrollbar-track]:bg-transparent">
      {threads.map((t) => {
        const isActive = t.thread_id === threadId;
        let itemText = t.thread_id;
        if (
          typeof t.values === "object" &&
          t.values &&
          "messages" in t.values &&
          Array.isArray(t.values.messages) &&
          t.values.messages?.length > 0
        ) {
          const firstMessage = t.values.messages[0];
          itemText = getContentString(firstMessage.content);
        }
        return (
          <div key={t.thread_id} className="w-full px-1">
            <Button
              variant="ghost"
              className={cn(
                "h-auto w-full justify-start rounded-[1.4rem] px-4 py-4 text-left font-normal transition-all",
                isActive
                  ? "bg-primary text-primary-foreground shadow-[0_14px_30px_rgba(24,72,71,0.18)] hover:bg-primary/95"
                  : "bg-white/45 text-foreground hover:bg-white/80",
              )}
              onClick={(e) => {
                e.preventDefault();
                onThreadClick?.(t.thread_id);
                if (t.thread_id === threadId) return;
                setThreadId(t.thread_id);
              }}
            >
              <div className="flex w-full flex-col items-start gap-1">
                <p className="w-full truncate text-sm font-medium">
                  {itemText}
                </p>
                <p
                  className={cn(
                    "text-xs",
                    isActive
                      ? "text-primary-foreground/75"
                      : "text-muted-foreground",
                  )}
                >
                  点击继续查看本次咨询
                </p>
              </div>
            </Button>
          </div>
        );
      })}
    </div>
  );
}

function ThreadHistoryLoading() {
  return (
    <div className="h-full flex w-full flex-col items-start justify-start gap-2 overflow-y-scroll pr-1 [&::-webkit-scrollbar]:w-1.5 [&::-webkit-scrollbar-thumb]:rounded-full [&::-webkit-scrollbar-thumb]:bg-primary/20 [&::-webkit-scrollbar-track]:bg-transparent">
      {Array.from({ length: 8 }).map((_, i) => (
        <Skeleton
          key={`skeleton-${i}`}
          className="h-[4.5rem] w-full rounded-[1.4rem] bg-white/60"
        />
      ))}
    </div>
  );
}

export default function ThreadHistory() {
  const isLargeScreen = useMediaQuery("(min-width: 1024px)");
  const [threadId, setThreadId] = useQueryState("threadId");
  const [chatHistoryOpen, setChatHistoryOpen] = useQueryState(
    "chatHistoryOpen",
    parseAsBoolean.withDefault(false),
  );
  const { getThreads, getThread, threads, setThreads, threadsLoading, setThreadsLoading } =
    useThreads();

  useEffect(() => {
    if (typeof window === "undefined") return;
    let cancelled = false;
    setThreadsLoading(true);
    getThreads()
      .then((fetchedThreads) => {
        if (cancelled) return;
        setThreads((prev) => mergeThreadLists(prev, fetchedThreads));
      })
      .catch((error) => {
        if (cancelled) return;
        console.error(error);
      })
      .finally(() => {
        if (cancelled) return;
        setThreadsLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [getThreads, setThreads, setThreadsLoading]);

  useEffect(() => {
    if (!threadId) {
      return;
    }

    let cancelled = false;

    getThread(threadId)
      .then((thread) => {
        if (cancelled) {
          return;
        }

        if (!thread) {
          setThreadId(null);
          return;
        }

        setThreads((prev) => mergeThreadLists(prev, [thread]));
      })
      .catch((error) => {
        if (cancelled) {
          return;
        }

        console.error(error);
      });

    return () => {
      cancelled = true;
    };
  }, [getThread, setThreadId, setThreads, threadId]);

  return (
    <>
      <div className="surface-glass hidden h-screen w-[320px] shrink-0 flex-col items-start justify-start gap-6 border-r border-white/55 px-4 pb-5 pt-4 shadow-inner-right lg:flex">
        <div className="flex w-full items-start justify-between gap-3">
          <div className="flex items-start gap-3">
            <SustechMark className="h-11 w-11" />
            <div>
              <p className="text-[11px] font-medium tracking-[0.18em] text-primary/72">
                SUSTech Admissions
              </p>
              <h1 className="mt-1 text-sm font-medium text-foreground">
                {BRAND_COPY.historyTitle}
              </h1>
            </div>
          </div>
          <Button
            className="rounded-full hover:bg-white/75"
            variant="ghost"
            onClick={() => setChatHistoryOpen((p) => !p)}
          >
            {chatHistoryOpen ? (
              <PanelRightOpen className="size-5" />
            ) : (
              <PanelRightClose className="size-5" />
            )}
          </Button>
        </div>
        {threadsLoading ? (
          <ThreadHistoryLoading />
        ) : (
          <ThreadList threads={threads} />
        )}
      </div>
      <div className="lg:hidden">
        <Sheet
          open={!!chatHistoryOpen && !isLargeScreen}
          onOpenChange={(open) => {
            if (isLargeScreen) return;
            setChatHistoryOpen(open);
          }}
        >
          <SheetContent side="left" className="surface-glass flex border-white/70 lg:hidden">
            <SheetHeader>
              <SheetTitle className="text-sm font-medium text-foreground">
                {BRAND_COPY.historyTitle}
              </SheetTitle>
            </SheetHeader>
            <ThreadList
              threads={threads}
              onThreadClick={() => setChatHistoryOpen((o) => !o)}
            />
          </SheetContent>
        </Sheet>
      </div>
    </>
  );
}
