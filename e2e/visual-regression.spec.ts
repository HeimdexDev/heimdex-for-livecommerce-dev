import { test, expect } from "@playwright/test";
import { devLogin } from "./helpers";

/**
 * Visual regression tests — capture screenshots and compare against baselines.
 *
 * First run generates baseline screenshots in e2e/__screenshots__/
 * Subsequent runs compare against baselines and fail on differences > 1%.
 *
 * Usage:
 *   npx playwright test visual-regression.spec.ts              # Compare against baselines
 *   npx playwright test visual-regression.spec.ts --update-snapshots  # Update baselines
 */

test.describe("Visual Regression", () => {
  test.beforeEach(async ({ page }) => {
    await devLogin(page);
  });

  test("search page — desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    // Wait for any animations to settle
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("search-desktop.png", {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test("search page — laptop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("search-laptop.png", {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test("search page — tablet", async ({ page }) => {
    await page.setViewportSize({ width: 768, height: 1024 });
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("search-tablet.png", {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test("videos page — desktop", async ({ page }) => {
    await page.setViewportSize({ width: 1920, height: 1080 });
    await page.goto("/videos");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("videos-desktop.png", {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test("videos page — laptop", async ({ page }) => {
    await page.setViewportSize({ width: 1280, height: 720 });
    await page.goto("/videos");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("videos-laptop.png", {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
  });

  test("login page — desktop (unauthenticated)", async ({ browser }) => {
    // Fresh context with no auth
    const context = await browser.newContext({
      viewport: { width: 1920, height: 1080 },
    });
    const page = await context.newPage();
    await page.goto("/");
    await page.waitForLoadState("networkidle");
    await page.waitForTimeout(500);
    await expect(page).toHaveScreenshot("login-desktop.png", {
      fullPage: true,
      maxDiffPixelRatio: 0.01,
    });
    await context.close();
  });
});
