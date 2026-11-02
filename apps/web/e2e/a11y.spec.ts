import { expect, test } from "@playwright/test";

import {
  authFile,
  expectNoSeriousAxeViolations,
  navigateTo,
  openApp,
} from "./support";

test.describe("accessibility - sign-in", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("Keycloak sign-in page has no serious or critical axe violations", async ({ page }) => {
    // Sign-in is hosted by the local Keycloak realm, so the scan runs on the
    // actual IdP page rather than on an app-rendered placeholder.
    await page.goto("/");
    await page.waitForURL(/\/realms\/sahyog\/protocol\/openid-connect\/auth/);
    await expect(page.locator("#username")).toBeVisible();
    await expectNoSeriousAxeViolations(page, "sign-in");
  });
});

test.describe("accessibility - patient pages", () => {
  test.use({ storageState: authFile("patient") });

  test("dashboard", async ({ page }) => {
    await openApp(page);
    await expect(page.locator(".quick-actions")).toBeVisible();
    await expect(page.locator("a.skip-link")).toHaveAttribute("href", "#main-content");
    await expect(page.locator("#main-content")).toHaveCount(1);
    await expectNoSeriousAxeViolations(page, "dashboard");
  });

  test("chat", async ({ page }) => {
    await openApp(page);
    await navigateTo(page, "Assistant");
    await expect(page.getByTestId("chat-composer")).toBeVisible();
    await expectNoSeriousAxeViolations(page, "chat");
  });

  test("appointments", async ({ page }) => {
    await openApp(page);
    await navigateTo(page, "Appointments");
    await expect(page.locator("table tbody tr, .empty-state").first()).toBeVisible();
    await expectNoSeriousAxeViolations(page, "appointments");
  });

  test("settings", async ({ page }) => {
    await openApp(page);
    await navigateTo(page, "Settings");
    await expect(page.locator(".settings-grid").first()).toBeVisible();
    await expectNoSeriousAxeViolations(page, "settings");
  });
});

test.describe("accessibility - analytics", () => {
  test.use({ storageState: authFile("compliance") });

  test("analytics", async ({ page }) => {
    await openApp(page);
    await navigateTo(page, "Analytics");
    await expect(page.locator(".metric-tile").first()).toBeVisible();
    await expectNoSeriousAxeViolations(page, "analytics");
  });
});
