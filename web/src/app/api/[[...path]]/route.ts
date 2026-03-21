import { NextRequest } from "next/server";

import {
  buildUpstreamHeaders,
  buildUpstreamResponseHeaders,
  buildUpstreamUrl,
  extractProxyPath,
  isAllowedProxyPath,
  rewriteBrowserInfoPayload,
  toUpstreamPath,
} from "@/lib/server/backend-proxy";

export const runtime = "nodejs";
export const dynamic = "force-dynamic";

function jsonResponse(status: number, payload: Record<string, unknown>): Response {
  return new Response(JSON.stringify(payload), {
    status,
    headers: {
      "content-type": "application/json",
    },
  });
}

async function proxyRequest(request: NextRequest): Promise<Response> {
  const apiSharedKey = process.env.API_SHARED_KEY?.trim();
  const backendInternalUrl = process.env.BACKEND_INTERNAL_URL?.trim();

  if (!apiSharedKey) {
    return jsonResponse(500, { detail: "Missing API_SHARED_KEY" });
  }
  if (!backendInternalUrl) {
    return jsonResponse(500, { detail: "Missing BACKEND_INTERNAL_URL" });
  }

  const path = extractProxyPath(request.nextUrl.pathname);
  if (!isAllowedProxyPath(path)) {
    return jsonResponse(404, { detail: "Not found" });
  }

  const upstreamUrl = buildUpstreamUrl(
    backendInternalUrl,
    path,
    request.nextUrl.search,
  );
  const upstreamHeaders = buildUpstreamHeaders(request.headers, apiSharedKey);
  const body =
    request.method === "GET" || request.method === "HEAD"
      ? undefined
      : await request.text();

  const upstream = await fetch(upstreamUrl, {
    method: request.method,
    headers: upstreamHeaders,
    body,
    cache: "no-store",
    redirect: "manual",
  });
  const responseHeaders = buildUpstreamResponseHeaders(upstream.headers);

  if (
    toUpstreamPath(path) === "/info" &&
    (upstream.headers.get("content-type") || "").includes("application/json")
  ) {
    const payload = await upstream.json() as Record<string, unknown>;
    const browserPayload = rewriteBrowserInfoPayload(payload);
    responseHeaders.set("content-type", "application/json");
    return new Response(JSON.stringify(browserPayload), {
      status: upstream.status,
      headers: responseHeaders,
    });
  }

  return new Response(upstream.body, {
    status: upstream.status,
    headers: responseHeaders,
  });
}

export async function GET(request: NextRequest): Promise<Response> {
  return proxyRequest(request);
}

export async function POST(request: NextRequest): Promise<Response> {
  return proxyRequest(request);
}
