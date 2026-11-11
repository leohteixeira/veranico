import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Development: the interface on 3500, the API role on 8500 behind the `/api` proxy.
// Production: `vite build` writes `dist/`, which the API role serves itself.
export default defineConfig({
  plugins: [react()],
  server: {
    host: "0.0.0.0",
    port: 3500,
    strictPort: true,
    proxy: {
      "/api": { target: "http://127.0.0.1:8500", changeOrigin: false },
    },
  },
  build: {
    outDir: "dist",
    emptyOutDir: true,
  },
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "node",
  },
});
