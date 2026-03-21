export type GraphConnectionInfo = {
  ok: boolean;
  apiKeyRequired: boolean;
};

export function shouldShowConnectionForm({
  finalApiUrl,
  finalAssistantId,
  connectionInfo: _connectionInfo,
}: {
  finalApiUrl: string;
  finalAssistantId: string;
  connectionInfo: GraphConnectionInfo | null;
}): boolean {
  return !finalApiUrl || !finalAssistantId;
}
