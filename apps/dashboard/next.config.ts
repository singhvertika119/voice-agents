import type { NextConfig } from "next";
import path from "node:path";
import { loadEnvConfig } from "@next/env";

// One .env at the repo root serves the worker and the dashboard.
loadEnvConfig(path.resolve(__dirname, "../.."), process.env.NODE_ENV !== "production", console, true); // forceReload: Next already cached this app dir

const nextConfig: NextConfig = {
  experimental: { serverActions: { bodySizeLimit: "16mb" } }, // knowledge uploads go through a server action
  env: {
    NEXT_PUBLIC_SUPABASE_URL: process.env.SUPABASE_URL,
    NEXT_PUBLIC_SUPABASE_ANON_KEY: process.env.SUPABASE_ANON_KEY,
  },
  turbopack: {
    root: path.resolve(__dirname, "../.."),
    rules: {
      "*.css": {
        loaders: ["@tailwindcss/turbopack"],
        as: "*.css",
      },
    },
  },
};

export default nextConfig;
