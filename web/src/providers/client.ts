import { Client } from "@langchain/langgraph-sdk";
import { resolveApiUrl } from "@/lib/resolve-api-url";
import { getClientHeaders } from "@/lib/device-id";

export function createClient(apiUrl: string, _apiKey?: string | undefined) {
  return new Client({
    apiUrl: resolveApiUrl(apiUrl),
    defaultHeaders: getClientHeaders(),
  });
}
