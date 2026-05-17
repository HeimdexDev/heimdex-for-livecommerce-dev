import { type Page, expect } from "@playwright/test";

/**
 * Shared helpers for Heimdex E2E tests.
 *
 * Dev-login flow: POST /api/auth/dev-login with email -> get JWT -> store in sessionStorage
 * The frontend reads `heimdex_dev_token` from sessionStorage and passes it as Authorization header.
 * This bypasses Auth0 for local/staging testing.
 */

const API_URL =
  process.env.API_URL ?? "http://devorg.app.heimdex.local:8000";
const DEV_EMAIL =
  process.env.DEV_EMAIL ?? "admin@devorg.example.com";

/**
 * Log in via dev-login endpoint.
 * Sets sessionStorage token so the frontend picks it up on page load.
 */
export async function devLogin(page: Page, email = DEV_EMAIL): Promise<void> {
  // Hit the dev-login API endpoint
  const response = await page.request.post(`${API_URL}/api/auth/dev-login`, {
    headers: {
      "Content-Type": "application/json",
      Host: "devorg.app.heimdex.local",
    },
    data: { email },
  });

  expect(response.ok(), `Dev-login failed: ${response.status()}`).toBeTruthy();

  const body = await response.json();
  const token = body.access_token ?? body.token;

  if (token) {
    // Navigate to the app first so we can set sessionStorage on the correct origin
    await page.goto("/");
    await page.evaluate((t) => {
      sessionStorage.setItem("heimdex_dev_token", t);
    }, token);
    // Reload so the app picks up the token from sessionStorage
    await page.reload();
    await page.waitForLoadState("networkidle");
  }
}

/**
 * Wait for the API to be healthy before running tests.
 */
export async function waitForApiHealth(
  page: Page,
  maxAttempts = 10,
): Promise<void> {
  for (let i = 0; i < maxAttempts; i++) {
    try {
      const response = await page.request.get(`${API_URL}/health`);
      if (response.ok()) return;
    } catch {
      // API not ready yet
    }
    await page.waitForTimeout(2000);
  }
  throw new Error(`API not healthy after ${maxAttempts} attempts`);
}

/**
 * Take a named screenshot and save to artifacts.
 */
export async function takeScreenshot(
  page: Page,
  name: string,
): Promise<void> {
  await page.screenshot({
    path: `artifacts/screenshots/${name}.png`,
    fullPage: true,
  });
}
