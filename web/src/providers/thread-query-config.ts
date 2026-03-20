import { validate } from "uuid";

export function getThreadSearchMetadata(
  assistantId: string,
  deviceId: string,
): { graph_id: string; device_id: string } | { assistant_id: string; device_id: string } {
  if (validate(assistantId)) {
    return { assistant_id: assistantId, device_id: deviceId };
  }
  return { graph_id: assistantId, device_id: deviceId };
}

export function resolveThreadConnection({
  apiUrlFromQuery,
  assistantIdFromQuery,
  envApiUrl,
  envAssistantId,
}: {
  apiUrlFromQuery: string | null;
  assistantIdFromQuery: string | null;
  envApiUrl?: string;
  envAssistantId?: string;
}): {
  apiUrl: string | null;
  assistantId: string | null;
} {
  const resolvedApiUrl = firstNonEmpty(apiUrlFromQuery, envApiUrl);
  const resolvedAssistantId = firstNonEmpty(assistantIdFromQuery, envAssistantId);

  return {
    apiUrl: resolvedApiUrl,
    assistantId: resolvedAssistantId,
  };
}

function firstNonEmpty(...values: Array<string | null | undefined>): string | null {
  for (const value of values) {
    if (typeof value === "string" && value.trim()) {
      return value;
    }
  }
  return null;
}
