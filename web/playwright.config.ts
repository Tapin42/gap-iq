import { defineConfig } from "@playwright/test";

const WEB_PORT = 8478;

export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 60_000,
  retries: process.env.CI ? 1 : 0,
  use: {
    baseURL: `http://127.0.0.1:${WEB_PORT}`,
    trace: "on-first-retry",
  },
  webServer: {
    command: "npm run dev",
    url: `http://127.0.0.1:${WEB_PORT}`,
    reuseExistingServer: !process.env.CI,
    timeout: 120_000,
  },
});
