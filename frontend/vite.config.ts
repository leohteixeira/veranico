import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// Development: the interface on 3500, the API role on 8500 behind the `/api` proxy.
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
      "/api": { target: "http://127.0.0.1:8500", changeOrigin: false },
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
