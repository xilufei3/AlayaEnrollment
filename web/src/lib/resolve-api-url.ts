export function resolveApiUrl(apiUrl: string): string {
  const trimmed = apiUrl.trim();
  if (!trimmed) return trimmed;

  if (typeof window === "undefined") {
    return trimmed;
  }

  try {
    return new URL(trimmed).toString().replace(/\/$/, "");
  } catch {
    return new URL(trimmed, window.location.origin).toString().replace(/\/$/, "");
  }
}
