const basePathFromEnv = process.env.NEXT_PUBLIC_BASE_PATH?.replace(/\/$/, "") ?? "";

export const DEFAULT_BASE_PATH = basePathFromEnv;
export const DEFAULT_API_URL = basePathFromEnv
  ? `${basePathFromEnv}/api`
  : "/api";
export const DEFAULT_ASSISTANT_ID = "agent";
