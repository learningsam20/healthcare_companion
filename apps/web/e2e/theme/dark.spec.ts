import { expect, test } from "@playwright/test";

import { authFile, captureScreenshot, openApp } from "../support";

test.use({ storageState: authFile("patient") });

test("desktop dark theme renders with the dark palette", async ({ page }) => {
  await openApp(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect(page.locator("body")).not.toHaveCSS("background-color", "rgb(243, 246, 248)");
  await captureScreenshot(page, "desktop-dark-dashboard.png");
});
