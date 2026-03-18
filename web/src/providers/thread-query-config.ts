import { validate } from "uuid";

export function getThreadSearchMetadata(
  assistantId: string,
): { graph_id: string } | { assistant_id: string } {
  if (validate(assistantId)) {
    return { assistant_id: assistantId };
  }
  return { graph_id: assistantId };
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
