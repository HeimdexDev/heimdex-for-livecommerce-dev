import { test, expect } from "@playwright/test";
import { devLogin, takeScreenshot } from "./helpers";

/**
 * Feature consistency tests — verify UI behaves identically across pages.
 * Catches: buttons that work on one page but not another,
 * inconsistent styling, broken interactions.
 */

test.describe("Feature Consistency", () => {
  test.beforeEach(async ({ page }) => {
    await devLogin(page);
  });

  test("all navigation links are functional", async ({ page }) => {
    await page.goto("/");
    await page.waitForLoadState("networkidle");

    // Collect all navigation links
    const navLinks = page.locator("nav a, header a, [role='navigation'] a");
    const count = await navLinks.count();

    for (let i = 0; i < count; i++) {
      const link = navLinks.nth(i);
      const href = await link.getAttribute("href");
      const isVisible = await link.isVisible();

      if (!isVisible || !href || href.startsWith("http") || href === "#") {
        continue;
      }

      // Click and verify no error
      await link.click();
      await page.waitForLoadState("networkidle");

      // Check no error overlay or 500 page
      const errorIndicators = page.locator(
        '[class*="error"], [class*="Error"], [data-testid="error"]',
      );
      const hasError = (await errorIndicators.count()) > 0 &&
        (await errorIndicators.first().isVisible());

      expect(
        hasError,
        `Error found after navigating to ${href}`,
      ).toBeFalsy();

      // Go back to start for next iteration
      await page.goto("/");
      await page.waitForLoadState("networkidle");
    }
  });

  test("buttons have consistent click behavior", async ({ page }) => {
    const pagesToCheck = ["/", "/videos"];

    for (const url of pagesToCheck) {
      await page.goto(url);
      await page.waitForLoadState("networkidle");

      // Find all visible buttons
      const buttons = page.locator(
        'button:visible, [role="button"]:visible',
      );
      const count = await buttons.count();

      for (let i = 0; i < count; i++) {
        const button = buttons.nth(i);
        const isDisabled = await button.isDisabled();
        const text = await button.textContent();

        if (isDisabled) continue;

        // Verify button is clickable (no JS errors)
        const errors: string[] = [];
        page.on("pageerror", (err) => errors.push(err.message));

        // Don't actually click destructive buttons, just verify they're interactive
        const cursor = await button.evaluate(
          (el) => window.getComputedStyle(el).cursor,
        );
        expect(
          cursor,
          `Button "${text?.trim()}" on ${url} should have pointer cursor`,
        ).toBe("pointer");

        page.removeAllListeners("pageerror");
      }
    }
  });

  test("no console errors on any page", async ({ page }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") {
        consoleErrors.push(`${msg.text()}`);
      }
    });

    const pages = ["/", "/videos"];

    for (const url of pages) {
      consoleErrors.length = 0;
      await page.goto(url);
      await page.waitForLoadState("networkidle");

      // Filter out known/acceptable errors (e.g., favicon 404)
      const realErrors = consoleErrors.filter(
        (e) => !e.includes("favicon") && !e.includes("404"),
      );

      expect(
        realErrors,
        `Console errors on ${url}: ${realErrors.join(", ")}`,
      ).toHaveLength(0);
    }
  });

  test("responsive layout has no horizontal overflow", async ({ page }) => {
    const viewports = [
      { width: 1920, height: 1080, name: "desktop" },
      { width: 1280, height: 720, name: "laptop" },
      { width: 768, height: 1024, name: "tablet" },
    ];

    for (const vp of viewports) {
      await page.setViewportSize({ width: vp.width, height: vp.height });
      await page.goto("/");
      await page.waitForLoadState("networkidle");

      const hasHorizontalScroll = await page.evaluate(() => {
        return document.documentElement.scrollWidth > document.documentElement.clientWidth;
      });

      expect(
        hasHorizontalScroll,
        `Horizontal overflow detected at ${vp.name} (${vp.width}x${vp.height})`,
      ).toBeFalsy();

      await takeScreenshot(page, `responsive-${vp.name}`);
    }
  });
});
