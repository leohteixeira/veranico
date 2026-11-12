import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

/** The environment variable that says where the development server proxies `/api` to. */
export const ENV_API_PROXY_TARGET = "VERANICO_API_PROXY_TARGET";
export const DEFAULT_API_PROXY_TARGET = "http://127.0.0.1:8500";

/**
 * Where `/api` goes in development: the API role on this machine unless the variable names
 * another address (inside Compose, the API service). It is read here, by the development server,
 * and is not a `VITE_` variable, so it never reaches the bundle.
 */
export function apiProxyTarget(env: Readonly<Record<string, string | undefined>>): string {
  const target = env[ENV_API_PROXY_TARGET]?.trim();
  return target === undefined || target === "" ? DEFAULT_API_PROXY_TARGET : target;
}

// Development: the interface on 3500, the API role behind the `/api` proxy.
// Production: `vite build` writes `dist/`, which the API role serves itself.
// The build starts from `index.html`, so `design-reference/` is never bundled.
// Tests are configured in `vitest.config.ts`.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3500,
    strictPort: true,
    proxy: {
      "/api": { target: apiProxyTarget(process.env), changeOrigin: false },
    },
  },
  preview: {
    host: "0.0.0.0",
    port: 3500,
    strictPort: true,
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
});
