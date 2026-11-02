import { expect, test } from "@playwright/test";

import { authFile, captureScreenshot, openApp } from "../support";

test.use({ storageState: authFile("patient") });

test("360px mobile shell, navigation and chat", async ({ page }) => {
  await openApp(page);
  expect(page.viewportSize()?.width).toBe(360);
  await expect(page.getByTestId("shell-menu")).toBeVisible();
  await expect(page.locator(".sidebar")).not.toHaveClass(/is-open/);
  await captureScreenshot(page, "mobile-360-dashboard.png");

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - window.innerWidth,
  );
  expect(overflow, "dashboard must not overflow horizontally at 360px").toBeLessThanOrEqual(1);

  await page.getByTestId("shell-menu").click();
  await expect(page.locator(".sidebar")).toHaveClass(/is-open/);
  await page.getByTestId("shell-nav").getByRole("link", { name: "Assistant", exact: true }).click();
  await expect(page.getByRole("heading", { level: 1, name: "Assistant" })).toBeVisible();
  await expect(page.getByTestId("chat-composer")).toBeVisible();
  await expect(page.locator(".sidebar")).not.toHaveClass(/is-open/);
  await captureScreenshot(page, "mobile-360-chat.png");
});
