import { expect, test } from "@playwright/test";

import {
  authFile,
  captureScreenshot,
  navigateTo,
  openApp,
} from "./support";

test.use({ storageState: authFile("patient") });

test("desktop light dashboard and chat", async ({ page }) => {
  await openApp(page);
  await expect(page.locator("html")).toHaveAttribute("data-theme", "light");
  await captureScreenshot(page, "desktop-light-dashboard.png");

  await navigateTo(page, "Assistant");
  await expect(page.getByTestId("chat-composer")).toBeVisible();
  await captureScreenshot(page, "desktop-light-chat.png");
});
