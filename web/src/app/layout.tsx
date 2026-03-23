import type { Metadata } from "next";
import React from "react";
import { NuqsAdapter } from "nuqs/adapters/next/app";

import "./globals.css";
import { APP_METADATA } from "@/components/thread/branding";
import { withBasePath } from "@/lib/public-path";

export const metadata: Metadata = {
  title: APP_METADATA.title,
  description: APP_METADATA.description,
  icons: {
    icon: withBasePath("/branding/sustech-logo.png"),
    shortcut: withBasePath("/branding/sustech-logo.png"),
    apple: withBasePath("/branding/sustech-logo.png"),
  },
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="font-sans">
        <NuqsAdapter>{children}</NuqsAdapter>
      </body>
    </html>
  );
}
