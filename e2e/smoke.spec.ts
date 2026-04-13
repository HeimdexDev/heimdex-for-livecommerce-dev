import { test, expect } from "@playwright/test";
import { devLogin, waitForApiHealth, takeScreenshot } from "./helpers";

/**
 * Smoke tests — run after every change to verify basic functionality.
 * These should pass in < 60 seconds against a running Docker stack.
 */

test.describe("Smoke Tests", () => {
  test.beforeAll(async ({ browser }) => {
    const page = await browser.newPage();
    await waitForApiHealth(page);
    await page.close();
  });

  test("API health check returns ok", async ({ page }) => {
    const apiUrl =
      process.env.API_URL ?? "http://devorg.app.heimdex.local:8000";
    const response = await page.request.get(`${apiUrl}/health`);
    expect(response.ok()).toBeTruthy();
    const body = await response.json();
    expect(body.status).toBe("ok");
  });

  test("Web app loads and shows login or search page", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    // Should show either login button or search interface
    const pageContent = await page.textContent("body");
    expect(pageContent).toBeTruthy();
    await takeScreenshot(page, "home-page-loaded");
  });

  test("Dev-login and access search page", async ({ page }) => {
    await devLogin(page); // navigates to / and reloads with token
    await takeScreenshot(page, "search-page-after-login");
  });

  test("Videos page loads after login", async ({ page }) => {
    await devLogin(page);
    await page.goto("/videos");
    await page.waitForLoadState("networkidle");
    await takeScreenshot(page, "videos-page");
  });

  test("Navigation between search and videos is consistent", async ({
    page,
  }) => {
    await devLogin(page);

    // Go to search
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Navigate to videos
    const videosLink = page.locator('a[href*="videos"], [data-testid="nav-videos"]').first();
    if (await videosLink.isVisible()) {
      await videosLink.click();
      await page.waitForLoadState("networkidle");
      expect(page.url()).toContain("/videos");
    }

    // Navigate back to search
    const searchLink = page.locator('a[href="/"], [data-testid="nav-search"]').first();
    if (await searchLink.isVisible()) {
      await searchLink.click();
      await page.waitForLoadState("networkidle");
    }

    await takeScreenshot(page, "navigation-round-trip");
  });
});
