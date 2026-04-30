const ALLOWED_STATIC_PATHS = new Set([
  "info",
  "threads",
  "threads/search",
  "runs/stream",
  "chat/stream",
  "admin/conversations",
  "admin/collection/stats",
  "admin/ingest",
]);

function normalizePathSegments(path: string[]): string[] {
  return path.map((segment) => segment.trim()).filter(Boolean);
}

export function extractProxyPath(pathname: string): string[] {
  const withoutPrefix = pathname.replace(/^\/api\/?/, "");
  if (!withoutPrefix) {
    return [];
  }
  return normalizePathSegments(withoutPrefix.split("/"));
}

export function isAllowedProxyPath(path: string[]): boolean {
  const segments = normalizePathSegments(path);
  const joined = segments.join("/");

  if (ALLOWED_STATIC_PATHS.has(joined)) {
    return true;
  }

  if (
    segments.length === 2 &&
    segments[0] === "threads"
  ) {
    return true;
  }

  if (
    segments.length === 3 &&
    segments[0] === "threads" &&
    (segments[2] === "state" || segments[2] === "history")
  ) {
    return true;
  }

  if (
    segments.length === 4 &&
    segments[0] === "threads" &&
    segments[2] === "runs" &&
    segments[3] === "stream"
  ) {
    return true;
  }

  if (
    segments.length === 3 &&
    segments[0] === "admin" &&
    segments[1] === "conversations"
  ) {
    return true;
  }

  return false;
}

export function toUpstreamPath(path: string[]): string {
  const segments = normalizePathSegments(path);
  return `/${segments.join("/")}`;
}

export function buildUpstreamUrl(
  backendInternalUrl: string,
  path: string[],
  search = "",
): string {
  const base = backendInternalUrl.trim().replace(/\/$/, "");
  return `${base}${toUpstreamPath(path)}${search}`;
}

export function buildUpstreamHeaders(
  requestHeaders: Headers,
  apiSharedKey: string,
): Headers {
  const upstreamHeaders = new Headers();
  const accept = requestHeaders.get("accept");
  const contentType = requestHeaders.get("content-type");
  const deviceId = requestHeaders.get("x-device-id");

  if (accept) {
    upstreamHeaders.set("accept", accept);
  }
  if (contentType) {
    upstreamHeaders.set("content-type", contentType);
  }
  if (deviceId) {
    upstreamHeaders.set("x-device-id", deviceId);
  }

  upstreamHeaders.set("x-api-key", apiSharedKey);
  return upstreamHeaders;
}

export function rewriteBrowserInfoPayload(
  payload: Record<string, unknown>,
): Record<string, unknown> {
  return {
    ...payload,
    api_key_required: false,
  };
}

const RESPONSE_HEADER_ALLOWLIST = [
  "cache-control",
  "content-location",
  "content-type",
  "x-accel-buffering",
] as const;

export function buildUpstreamResponseHeaders(
  upstreamHeaders: Headers,
): Headers {
  const responseHeaders = new Headers();

  for (const headerName of RESPONSE_HEADER_ALLOWLIST) {
    const value = upstreamHeaders.get(headerName);
    if (value) {
      responseHeaders.set(headerName, value);
    }
  }

  return responseHeaders;
}
