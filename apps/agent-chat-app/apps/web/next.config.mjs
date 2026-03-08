import path from "node:path";
import dotenv from "dotenv";

// Keep a single source of truth for env values at repo root: D:/AlayaEnrollment/.env
dotenv.config({
  path: path.resolve(process.cwd(), "../../../../.env"),
});

/** @type {import('next').NextConfig} */
const nextConfig = {
  env: {
    NEXT_PUBLIC_API_URL: process.env.NEXT_PUBLIC_API_URL,
    NEXT_PUBLIC_ASSISTANT_ID: process.env.NEXT_PUBLIC_ASSISTANT_ID,
    NEXT_PUBLIC_LANGSMITH_API_KEY: process.env.NEXT_PUBLIC_LANGSMITH_API_KEY,
  },
};

export default nextConfig;
