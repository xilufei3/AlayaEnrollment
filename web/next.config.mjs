import path from "node:path";
import { fileURLToPath } from "node:url";
import dotenv from "dotenv";

const webDir = path.dirname(fileURLToPath(import.meta.url));

// Keep a single source of truth for env values at repo root: D:/AlayaEnrollment/.env
dotenv.config({
  path: path.resolve(webDir, "../.env"),
});

const BASE_PATH = "/zs-ai";

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
  basePath: BASE_PATH,
  env: {
    NEXT_PUBLIC_BASE_PATH: BASE_PATH,
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_ASSISTANT_ID: process.env.NEXT_PUBLIC_ASSISTANT_ID,
    NEXT_PUBLIC_LANGSMITH_API_KEY: process.env.NEXT_PUBLIC_LANGSMITH_API_KEY,
  },
};

export default nextConfig;
