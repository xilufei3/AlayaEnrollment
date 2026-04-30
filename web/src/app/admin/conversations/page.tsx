"use client";

import { Suspense, useEffect, useMemo, useState } from "react";
import { useQueryState } from "nuqs";
import {
  MessageSquareText,
  RefreshCw,
  Search,
  Smartphone,
  Trash2,
  UserRound,
} from "lucide-react";
import { toast } from "sonner";

import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Skeleton } from "@/components/ui/skeleton";
import { Button } from "@/components/ui/button";
import { Toaster } from "@/components/ui/sonner";
import { cn } from "@/lib/utils";
import { DEFAULT_API_URL } from "@/providers/constants";

type AdminConversationThread = {
  thread_id: string;
  user_id: string;
  assistant_id: string;
  created_at: string | null;
  updated_at: string | null;
  title: string;
  preview: string;
  message_count: number;
  user_message_count: number;
  assistant_message_count: number;
  metadata: Record<string, unknown>;
};

type AdminConversationUser = {
  user_id: string;
  thread_count: number;
  message_count: number;
  last_active_at: string | null;
  threads: AdminConversationThread[];
};

type AdminConversationOverview = {
  users: AdminConversationUser[];
  stats: {
    user_count: number;
    thread_count: number;
    message_count: number;
  };
  totals: {
    user_count: number;
    thread_count: number;
  };
  pagination: {
    limit: number;
    offset: number;
    page: number;
    page_count: number;
    has_prev: boolean;
    has_next: boolean;
  };
};

type AdminConversationMessage = {
  id: string;
  index: number;
  type: string;
  role: string;
  text: string;
  content: unknown;
};

type AdminConversationDetail = {
  thread_id: string;
  user_id: string;
  assistant_id: string;
  created_at: string | null;
  updated_at: string | null;
  title: string;
  message_count: number;
  metadata: Record<string, unknown>;
  messages: AdminConversationMessage[];
};

function formatDateTime(value: string | null | undefined): string {
  if (!value) return "暂无记录";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return value;
  }
  return new Intl.DateTimeFormat("zh-CN", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}

function roleLabel(role: string): string {
  if (role === "user") return "用户";
  if (role === "assistant") return "助手";
  if (role === "tool") return "工具";
  if (role === "system") return "系统";
  return role || "未知";
}

function messageRoleStyles(role: string): string {
  if (role === "user") {
    return "ml-auto border-primary/18 bg-brand-gradient text-primary-foreground";
  }
  if (role === "assistant") {
    return "mr-auto border-white/80 bg-white/92 text-foreground";
  }
  if (role === "tool") {
    return "mr-auto border-amber-200 bg-amber-50/95 text-amber-900";
  }
  return "mr-auto border-slate-200 bg-slate-50/95 text-slate-700";
}

function StatTile(props: { label: string; value: number; hint: string }) {
  return (
    <div className="rounded-[1.4rem] border border-white/70 bg-white/72 px-4 py-4 shadow-[0_16px_36px_rgba(24,72,71,0.07)] backdrop-blur">
      <p className="text-[11px] font-semibold tracking-[0.16em] text-primary/72">
        {props.label}
      </p>
      <p className="mt-2 text-3xl font-semibold text-foreground">{props.value}</p>
      <p className="mt-1 text-sm text-muted-foreground">{props.hint}</p>
    </div>
  );
}

const PAGE_SIZE = 100;

function normalizePage(value: string | null): number {
  const parsed = Number.parseInt(value ?? "1", 10);
  if (!Number.isFinite(parsed) || parsed < 1) {
    return 1;
  }
  return parsed;
}

function AdminConversationsPageContent() {
  const [page, setPage] = useQueryState("page");
  const [userId, setUserId] = useQueryState("userId");
  const [threadId, setThreadId] = useQueryState("threadId");
  const [search, setSearch] = useState("");
  const [overview, setOverview] = useState<AdminConversationOverview | null>(null);
  const [detail, setDetail] = useState<AdminConversationDetail | null>(null);
  const [loadingOverview, setLoadingOverview] = useState(true);
  const [loadingDetail, setLoadingDetail] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [detailError, setDetailError] = useState<string | null>(null);
  const [deletingThreadId, setDeletingThreadId] = useState<string | null>(null);
  const [hiddenThreadIds, setHiddenThreadIds] = useState<string[]>([]);
  const [refreshTick, setRefreshTick] = useState(0);
  const currentPage = normalizePage(page);
  const currentOffset = (currentPage - 1) * PAGE_SIZE;

  useEffect(() => {
    let cancelled = false;
    setLoadingOverview(true);
    setError(null);

    fetch(
      `${DEFAULT_API_URL}/admin/conversations?limit=${PAGE_SIZE}&offset=${currentOffset}`,
      {
        cache: "no-store",
      },
    )
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`加载会话列表失败（${response.status}）`);
        }
        return response.json() as Promise<AdminConversationOverview>;
      })
      .then((payload) => {
        if (cancelled) return;
        setOverview(payload);
      })
      .catch((fetchError: unknown) => {
        if (cancelled) return;
        setOverview(null);
        setError(
          fetchError instanceof Error ? fetchError.message : "加载会话列表失败",
        );
      })
      .finally(() => {
        if (cancelled) return;
        setLoadingOverview(false);
      });

    return () => {
      cancelled = true;
    };
  }, [currentOffset, refreshTick]);

  useEffect(() => {
    const pageCount = overview?.pagination.page_count ?? 1;
    if (currentPage > pageCount) {
      void setPage(String(pageCount));
    }
  }, [currentPage, overview?.pagination.page_count, setPage]);

  const filteredUsers = useMemo(() => {
    if (!overview) return [];
    const keyword = search.trim().toLowerCase();
    const visibleUsers = overview.users
      .map((user) => {
        const visibleThreads = user.threads.filter(
          (thread) => !hiddenThreadIds.includes(thread.thread_id),
        );
        return {
          ...user,
          threads: visibleThreads,
          thread_count: visibleThreads.length,
          message_count: visibleThreads.reduce(
            (sum, thread) => sum + thread.message_count,
            0,
          ),
          last_active_at: visibleThreads[0]?.updated_at ?? user.last_active_at,
        };
      })
      .filter((user) => user.threads.length > 0);

    if (!keyword) return visibleUsers;

    return visibleUsers
      .map((user) => {
        const matchedThreads = user.threads.filter((thread) => {
          const haystack = [
            user.user_id,
            thread.thread_id,
            thread.title,
            thread.preview,
          ]
            .join(" ")
            .toLowerCase();
          return haystack.includes(keyword);
        });

        if (user.user_id.toLowerCase().includes(keyword)) {
          return user;
        }
        if (matchedThreads.length === 0) {
          return null;
        }
        return {
          ...user,
          threads: matchedThreads,
          thread_count: matchedThreads.length,
          message_count: matchedThreads.reduce(
            (sum, thread) => sum + thread.message_count,
            0,
          ),
          last_active_at: matchedThreads[0]?.updated_at ?? user.last_active_at,
        };
      })
      .filter((user): user is AdminConversationUser => user !== null);
  }, [hiddenThreadIds, overview, search]);

  const selectedUser = useMemo(() => {
    if (filteredUsers.length === 0) return null;
    if (userId) {
      return filteredUsers.find((user) => user.user_id === userId) ?? null;
    }
    return filteredUsers[0];
  }, [filteredUsers, userId]);

  const selectedThread = useMemo(() => {
    const threads = selectedUser?.threads ?? [];
    if (threads.length === 0) return null;
    if (threadId) {
      return threads.find((thread) => thread.thread_id === threadId) ?? null;
    }
    return threads[0];
  }, [selectedUser, threadId]);

  useEffect(() => {
    if (!selectedUser) {
      if (userId) {
        void setUserId(null);
      }
      if (threadId) {
        void setThreadId(null);
      }
      return;
    }

    if (selectedUser.user_id !== userId) {
      void setUserId(selectedUser.user_id);
    }

    const threads = selectedUser.threads;
    if (threads.length === 0) {
      if (threadId) {
        void setThreadId(null);
      }
      return;
    }

    const hasSelectedThread = threadId
      ? threads.some((thread) => thread.thread_id === threadId)
      : false;

    if (!hasSelectedThread) {
      void setThreadId(threads[0].thread_id);
    }
  }, [selectedUser, setThreadId, setUserId, threadId, userId]);

  useEffect(() => {
    if (!selectedThread?.thread_id) {
      setDetail(null);
      return;
    }

    let cancelled = false;
    setLoadingDetail(true);
    setDetailError(null);

    fetch(
      `${DEFAULT_API_URL}/admin/conversations/${encodeURIComponent(selectedThread.thread_id)}`,
      { cache: "no-store" },
    )
      .then(async (response) => {
        if (!response.ok) {
          throw new Error(`加载对话详情失败（${response.status}）`);
        }
        return response.json() as Promise<AdminConversationDetail>;
      })
      .then((payload) => {
        if (cancelled) return;
        setDetail(payload);
      })
      .catch((fetchError: unknown) => {
        if (cancelled) return;
        setDetail(null);
        setDetailError(
          fetchError instanceof Error ? fetchError.message : "加载对话详情失败",
        );
      })
      .finally(() => {
        if (cancelled) return;
        setLoadingDetail(false);
      });

    return () => {
      cancelled = true;
    };
  }, [selectedThread?.thread_id]);

  async function handleDeleteThread(): Promise<void> {
    const targetThread = selectedThread;
    if (!targetThread?.thread_id) {
      return;
    }

    const confirmed = window.confirm(
      `确认删除这个线程吗？\n\nThread ID: ${targetThread.thread_id}\n\n删除后会从管理台移除该线程的运行时对话记录，且无法恢复。`,
    );
    if (!confirmed) {
      return;
    }

    setDeletingThreadId(targetThread.thread_id);
    setDetailError(null);

    try {
      const response = await fetch(
        `${DEFAULT_API_URL}/admin/conversations/${encodeURIComponent(targetThread.thread_id)}`,
        {
          method: "DELETE",
        },
      );

      if (!response.ok) {
        let message = `删除线程失败（${response.status}）`;
        try {
          const payload = (await response.json()) as { detail?: string };
          if (payload?.detail) {
            message = payload.detail;
          }
        } catch {
          // Keep the fallback message when the response body is not JSON.
        }
        throw new Error(message);
      }

      setHiddenThreadIds((current) =>
        current.includes(targetThread.thread_id)
          ? current
          : [...current, targetThread.thread_id],
      );
      setDetail((current) =>
        current?.thread_id === targetThread.thread_id ? null : current,
      );
      if (threadId === targetThread.thread_id) {
        void setThreadId(null);
      }

      setRefreshTick((value) => value + 1);
      toast("线程已删除", {
        description: `已删除 ${targetThread.thread_id}`,
      });
    } catch (deleteError: unknown) {
      const message =
        deleteError instanceof Error ? deleteError.message : "删除线程失败";
      setDetailError(message);
      toast("删除失败", {
        description: message,
      });
    } finally {
      setDeletingThreadId(null);
    }
  }

  return (
    <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-[1680px] flex-col gap-6">
        <section className="surface-glass overflow-hidden rounded-[2rem] border border-white/65 p-6 shadow-[0_28px_80px_rgba(24,72,71,0.12)]">
          <div className="flex flex-col gap-5 lg:flex-row lg:items-end lg:justify-between">
            <div>
              <p className="text-xs font-semibold tracking-[0.2em] text-primary/75">
                CONVERSATION ADMIN
              </p>
              <h1 className="mt-3 font-serif text-3xl text-foreground sm:text-4xl">
                聊天记录管理台
              </h1>
              <p className="mt-3 max-w-3xl text-sm leading-6 text-muted-foreground sm:text-base">
                按用户区分所有会话，并查看每个会话的完整端到端对话内容。
              </p>
            </div>
            <div className="flex flex-col gap-3 sm:flex-row sm:items-center">
              <div className="relative min-w-[280px]">
                <Search className="pointer-events-none absolute left-3 top-1/2 size-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={search}
                  onChange={(event) => setSearch(event.target.value)}
                  placeholder="搜索用户 ID、会话标题、预览内容"
                  className="h-11 rounded-full border-white/80 bg-white/78 pl-9"
                />
              </div>
              <Button
                type="button"
                variant="outline"
                className="h-11 rounded-full border-white/80 bg-white/70 px-5"
                onClick={() => setRefreshTick((value) => value + 1)}
              >
                <RefreshCw className="size-4" />
                刷新数据
              </Button>
            </div>
          </div>

          <div className="mt-6 grid gap-4 sm:grid-cols-3">
            <StatTile
              label="用户数"
              value={overview?.totals.user_count ?? 0}
              hint={`当前页 ${overview?.stats.user_count ?? 0} 个`}
            />
            <StatTile
              label="会话数"
              value={overview?.totals.thread_count ?? 0}
              hint={`当前页 ${overview?.stats.thread_count ?? 0} 个`}
            />
            <StatTile
              label="消息数"
              value={overview?.stats.message_count ?? 0}
              hint="当前页消息量"
            />
          </div>
          <div className="mt-5 flex flex-col gap-3 rounded-[1.4rem] border border-white/70 bg-white/58 px-4 py-4 text-sm text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
            <p>
              当前第 {overview?.pagination.page ?? currentPage} / {overview?.pagination.page_count ?? 1} 页，
              每页 {overview?.pagination.limit ?? PAGE_SIZE} 个会话线程。
            </p>
            <div className="flex items-center gap-3">
              <Button
                type="button"
                variant="outline"
                className="rounded-full border-white/80 bg-white/75"
                disabled={!overview?.pagination.has_prev || loadingOverview}
                onClick={() => void setPage(String(Math.max(1, currentPage - 1)))}
              >
                上一页
              </Button>
              <Button
                type="button"
                variant="outline"
                className="rounded-full border-white/80 bg-white/75"
                disabled={!overview?.pagination.has_next || loadingOverview}
                onClick={() => void setPage(String(currentPage + 1))}
              >
                下一页
              </Button>
            </div>
          </div>
        </section>

        {error ? (
          <Card className="border-destructive/25 bg-white/88">
            <CardContent className="pt-6 text-sm text-destructive">
              {error}
            </CardContent>
          </Card>
        ) : null}

        <section className="grid gap-5 xl:grid-cols-[320px_360px_minmax(0,1fr)]">
          <Card className="surface-glass gap-0 border-white/70 py-0">
            <CardHeader className="border-b border-white/65 px-5 py-5">
              <CardTitle className="flex items-center gap-2 text-base">
                <UserRound className="size-4 text-primary" />
                用户列表
              </CardTitle>
            </CardHeader>
            <CardContent className="max-h-[70vh] overflow-y-auto px-3 py-3">
              {loadingOverview ? (
                <div className="space-y-3">
                  {Array.from({ length: 6 }).map((_, index) => (
                    <Skeleton
                      key={`user-skeleton-${index}`}
                      className="h-24 rounded-[1.2rem] bg-white/70"
                    />
                  ))}
                </div>
              ) : filteredUsers.length === 0 ? (
                <div className="flex min-h-40 items-center justify-center rounded-[1.2rem] border border-dashed border-border/80 bg-white/45 p-6 text-center text-sm text-muted-foreground">
                  当前没有可显示的用户或搜索结果为空。
                </div>
              ) : (
                <div className="space-y-3">
                  {filteredUsers.map((user) => {
                    const isActive = user.user_id === selectedUser?.user_id;
                    return (
                      <button
                        key={user.user_id}
                        type="button"
                        onClick={() => {
                          void setUserId(user.user_id);
                          void setThreadId(user.threads[0]?.thread_id ?? null);
                        }}
                        className={cn(
                          "w-full rounded-[1.2rem] border px-4 py-4 text-left transition-all",
                          isActive
                            ? "border-primary/25 bg-primary/10 shadow-[0_18px_34px_rgba(29,158,117,0.14)]"
                            : "border-white/80 bg-white/58 hover:bg-white/82",
                        )}
                      >
                        <div className="flex items-center justify-between gap-3">
                          <div className="flex min-w-0 items-center gap-3">
                            <div className="flex size-10 items-center justify-center rounded-full bg-secondary text-secondary-foreground">
                              <Smartphone className="size-4" />
                            </div>
                            <div className="min-w-0">
                              <p className="truncate text-sm font-semibold text-foreground">
                                {user.user_id}
                              </p>
                              <p className="mt-1 text-xs text-muted-foreground">
                                最近活跃 {formatDateTime(user.last_active_at)}
                              </p>
                            </div>
                          </div>
                          <div className="rounded-full bg-white/80 px-3 py-1 text-xs font-medium text-muted-foreground">
                            {user.thread_count} 个会话
                          </div>
                        </div>
                        <div className="mt-3 flex items-center gap-3 text-xs text-muted-foreground">
                          <span>{user.message_count} 条消息</span>
                          <span>首个会话 {user.threads[0]?.title ?? "暂无"}</span>
                        </div>
                      </button>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="surface-glass gap-0 border-white/70 py-0">
            <CardHeader className="border-b border-white/65 px-5 py-5">
              <CardTitle className="flex items-center gap-2 text-base">
                <MessageSquareText className="size-4 text-primary" />
                对话列表
              </CardTitle>
            </CardHeader>
            <CardContent className="max-h-[70vh] overflow-y-auto px-3 py-3">
              {!selectedUser ? (
                <div className="flex min-h-40 items-center justify-center rounded-[1.2rem] border border-dashed border-border/80 bg-white/45 p-6 text-center text-sm text-muted-foreground">
                  先在左侧选择一个用户。
                </div>
              ) : (
                <div className="space-y-3">
                  {selectedUser.threads.map((thread) => {
                    const isActive = thread.thread_id === selectedThread?.thread_id;
                    return (
                      <button
                        key={thread.thread_id}
                        type="button"
                        onClick={() => void setThreadId(thread.thread_id)}
                        className={cn(
                          "w-full rounded-[1.2rem] border px-4 py-4 text-left transition-all",
                          isActive
                            ? "border-[#c9a35d]/35 bg-[rgba(201,163,93,0.12)] shadow-[0_18px_34px_rgba(201,163,93,0.12)]"
                            : "border-white/80 bg-white/58 hover:bg-white/82",
                        )}
                      >
                        <div className="flex items-start justify-between gap-3">
                          <div className="min-w-0">
                            <p className="line-clamp-2 text-sm font-semibold leading-6 text-foreground">
                              {thread.title}
                            </p>
                            <p className="mt-2 line-clamp-2 text-xs leading-5 text-muted-foreground">
                              {thread.preview || "暂无预览"}
                            </p>
                          </div>
                          <div className="rounded-full bg-white/82 px-2.5 py-1 text-[11px] font-medium text-muted-foreground">
                            {thread.message_count} 条
                          </div>
                        </div>
                        <div className="mt-3 flex flex-wrap gap-x-3 gap-y-1 text-[11px] text-muted-foreground">
                          <span>更新时间 {formatDateTime(thread.updated_at)}</span>
                          <span>用户 {thread.user_message_count}</span>
                          <span>助手 {thread.assistant_message_count}</span>
                        </div>
                        <p className="mt-2 truncate text-[11px] text-primary/78">
                          {thread.thread_id}
                        </p>
                      </button>
                    );
                  })}
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="surface-glass gap-0 border-white/70 py-0">
            <CardHeader className="border-b border-white/65 px-5 py-5">
              <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
                <CardTitle className="text-base">
                  {detail?.title || selectedThread?.title || "对话详情"}
                </CardTitle>
                <Button
                  type="button"
                  variant="destructive"
                  className="rounded-full"
                  disabled={!selectedThread?.thread_id || deletingThreadId !== null}
                  onClick={() => void handleDeleteThread()}
                >
                  {deletingThreadId === selectedThread?.thread_id ? (
                    <RefreshCw className="size-4 animate-spin" />
                  ) : (
                    <Trash2 className="size-4" />
                  )}
                  删除线程
                </Button>
              </div>
              <div className="mt-3 flex flex-wrap gap-x-4 gap-y-2 text-xs text-muted-foreground">
                <span>用户 ID: {detail?.user_id || selectedUser?.user_id || "暂无"}</span>
                <span>Thread ID: {detail?.thread_id || selectedThread?.thread_id || "暂无"}</span>
                <span>更新时间: {formatDateTime(detail?.updated_at || selectedThread?.updated_at)}</span>
              </div>
            </CardHeader>
            <CardContent className="flex min-h-[70vh] flex-col px-4 py-4">
              {loadingDetail ? (
                <div className="space-y-4">
                  {Array.from({ length: 5 }).map((_, index) => (
                    <Skeleton
                      key={`detail-skeleton-${index}`}
                      className="h-24 rounded-[1.4rem] bg-white/70"
                    />
                  ))}
                </div>
              ) : detailError ? (
                <div className="flex min-h-40 items-center justify-center rounded-[1.2rem] border border-destructive/20 bg-white/70 p-6 text-center text-sm text-destructive">
                  {detailError}
                </div>
              ) : !detail ? (
                <div className="flex min-h-40 items-center justify-center rounded-[1.2rem] border border-dashed border-border/80 bg-white/45 p-6 text-center text-sm text-muted-foreground">
                  选择一个对话后，这里会展示完整聊天记录。
                </div>
              ) : detail.messages.length === 0 ? (
                <div className="flex min-h-40 items-center justify-center rounded-[1.2rem] border border-dashed border-border/80 bg-white/45 p-6 text-center text-sm text-muted-foreground">
                  这个会话当前没有消息内容。
                </div>
              ) : (
                <div className="flex flex-1 flex-col gap-4 overflow-y-auto pr-1">
                  {detail.messages.map((message) => (
                    <div
                      key={message.id}
                      className={cn(
                        "max-w-[88%] rounded-[1.5rem] border px-4 py-3 shadow-[0_16px_36px_rgba(24,72,71,0.08)]",
                        messageRoleStyles(message.role),
                      )}
                    >
                      <div className="flex items-center justify-between gap-3 text-[11px]">
                        <span className="font-semibold uppercase tracking-[0.14em]">
                          {roleLabel(message.role)}
                        </span>
                        <span className="opacity-75">
                          #{message.index + 1} · {message.type}
                        </span>
                      </div>
                      <pre className="mt-3 whitespace-pre-wrap break-words font-sans text-sm leading-6">
                        {message.text || "该消息没有可直接显示的文本内容。"}
                      </pre>
                    </div>
                  ))}
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}

function AdminConversationsPageFallback() {
  return (
    <main className="min-h-screen px-4 py-6 sm:px-6 lg:px-8">
      <div className="mx-auto flex max-w-[1680px] flex-col gap-6">
        <section className="surface-glass overflow-hidden rounded-[2rem] border border-white/65 p-6 shadow-[0_28px_80px_rgba(24,72,71,0.12)]">
          <div className="grid gap-4 sm:grid-cols-3">
            {Array.from({ length: 3 }).map((_, index) => (
              <Skeleton
                key={`stats-fallback-${index}`}
                className="h-28 rounded-[1.4rem] bg-white/70"
              />
            ))}
          </div>
        </section>
        <section className="grid gap-5 xl:grid-cols-[320px_360px_minmax(0,1fr)]">
          <Card className="surface-glass gap-0 border-white/70 py-0">
            <CardContent className="space-y-3 px-3 py-5">
              {Array.from({ length: 5 }).map((_, index) => (
                <Skeleton
                  key={`users-fallback-${index}`}
                  className="h-24 rounded-[1.2rem] bg-white/70"
                />
              ))}
            </CardContent>
          </Card>
          <Card className="surface-glass gap-0 border-white/70 py-0">
            <CardContent className="space-y-3 px-3 py-5">
              {Array.from({ length: 5 }).map((_, index) => (
                <Skeleton
                  key={`threads-fallback-${index}`}
                  className="h-28 rounded-[1.2rem] bg-white/70"
                />
              ))}
            </CardContent>
          </Card>
          <Card className="surface-glass gap-0 border-white/70 py-0">
            <CardContent className="space-y-4 px-4 py-5">
              {Array.from({ length: 6 }).map((_, index) => (
                <Skeleton
                  key={`messages-fallback-${index}`}
                  className="h-24 rounded-[1.4rem] bg-white/70"
                />
              ))}
            </CardContent>
          </Card>
        </section>
      </div>
    </main>
  );
}

export default function AdminConversationsPage() {
  return (
    <>
      <Toaster />
      <Suspense fallback={<AdminConversationsPageFallback />}>
        <AdminConversationsPageContent />
      </Suspense>
    </>
  );
}
