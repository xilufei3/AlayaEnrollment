import { Client } from "@langchain/langgraph-sdk";
import { resolveApiUrl } from "@/lib/resolve-api-url";
import { getClientHeaders } from "@/lib/device-id";

export function createClient(apiUrl: string, apiKey: string | undefined) {
  return new Client({
    apiKey,
    apiUrl: resolveApiUrl(apiUrl),
    defaultHeaders: getClientHeaders(apiKey),
  });
}
