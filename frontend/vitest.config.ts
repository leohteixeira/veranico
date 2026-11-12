import react from "@vitejs/plugin-react";
import { defineConfig } from "vitest/config";

// Unit and component tests live beside their files under `src/`. `design-reference/` and
// `e2e/` (Playwright) are outside the include pattern on purpose.
export default defineConfig({
  plugins: [react()],
  test: {
    include: ["src/**/*.test.{ts,tsx}"],
    environment: "jsdom",
    setupFiles: ["src/test/setup.ts"],
    restoreMocks: true,
    // The JSON results feed `scripts/req-report.mjs` (requirement traceability).
    reporters: ["default", "json"],
    outputFile: { json: ".cache/vitest.json" },
  },
});
