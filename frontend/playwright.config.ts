import { defineConfig, devices } from "@playwright/test";

// The flow runs against the production build served by `vite preview`. The preview for the
// end-to-end run has its own port, so it never collides with a development server on 3500.
const port = Number(process.env.E2E_PORT ?? "3511");
const baseURL = `http://127.0.0.1:${port}`;

export default defineConfig({
  testDir: "e2e",
  outputDir: "test-results",
  fullyParallel: false,
  workers: 1,
  forbidOnly: Boolean(process.env.CI),
  retries: 0,
  timeout: 60_000,
  reporter: [["list"], ["json", { outputFile: ".cache/playwright.json" }]],
  use: {
    baseURL,
    trace: "retain-on-failure",
    video: "on",
  },
  projects: [{ name: "chromium", use: { ...devices["Desktop Chrome"] } }],
  webServer: {
    command: `pnpm exec vite preview --host 127.0.0.1 --port ${port} --strictPort`,
    url: baseURL,
    reuseExistingServer: false,
    timeout: 60_000,
  },
});
