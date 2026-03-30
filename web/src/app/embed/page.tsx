"use client";

import React from "react";

import { Thread } from "@/components/thread";
import { Toaster } from "@/components/ui/sonner";
import { StreamProvider } from "@/providers/Stream";
import { ThreadProvider } from "@/providers/Thread";

export default function EmbedPage(): React.ReactNode {
  return (
    <React.Suspense fallback={<div>Loading (layout)...</div>}>
      <Toaster />
      <ThreadProvider>
        <StreamProvider>
          <Thread compact showHistoryInCompact />
        </StreamProvider>
      </ThreadProvider>
    </React.Suspense>
  );
}
