import { defineConfig, devices } from "@playwright/test";

/**
 * Heimdex Livecommerce — Playwright E2E Configuration
 *
 * Runs against a local Docker Compose stack or staging.
 *
 * Usage:
 *   npx playwright test                          # Run all tests
 *   npx playwright test --project=chromium        # Chrome only
 *   npx playwright test e2e/smoke.spec.ts         # Single file
 *   npx playwright test --headed                  # Watch mode
 *   BASE_URL=https://devorg.app.heimdexdemo.dev npx playwright test  # Staging
 */

const BASE_URL = process.env.BASE_URL ?? "http://devorg.app.heimdex.local:3000";
const API_URL = process.env.API_URL ?? "http://devorg.app.heimdex.local:8000";

export default defineConfig({
  testDir: __dirname,
  testMatch: "*.spec.ts",
  fullyParallel: false, // Sequential — tests may share state (logged-in session)
  retries: process.env.CI ? 1 : 0,
  workers: 1,
  timeout: 30_000,

  reporter: [
    ["html", { open: "never", outputFolder: "../artifacts/playwright-report" }],
    ["list"],
  ],

  outputDir: "../artifacts/playwright-results",

  use: {
    baseURL: BASE_URL,
    trace: "on-first-retry",
    screenshot: "only-on-failure",
    video: "retain-on-failure",
    actionTimeout: 10_000,
    navigationTimeout: 15_000,
  },

  projects: [
    {
      name: "chromium",
      use: { ...devices["Desktop Chrome"] },
    },
  ],

  // Expect local Docker stack to be running — don't auto-start
  // Run: docker compose up -d && make seed
  expect: {
    toHaveScreenshot: {
      maxDiffPixelRatio: 0.01, // 1% pixel diff tolerance for visual regression
    },
  },

  metadata: {
    apiUrl: API_URL,
  },
});
