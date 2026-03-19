import { Client } from "@langchain/langgraph-sdk";
import { resolveApiUrl } from "@/lib/resolve-api-url";

export function createClient(apiUrl: string, apiKey: string | undefined) {
  return new Client({
    apiKey,
    apiUrl: resolveApiUrl(apiUrl),
  });
}
