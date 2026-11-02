import { defineConfig } from "@playwright/test";

const baseURL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5705";
const crossBrowserProjects =
  process.env.PLAYWRIGHT_CROSS_BROWSER === "1"
    ? (["firefox", "webkit"] as const).map((browserName) => ({
        name: `${browserName}-desktop`,
        testMatch: /.*\.spec\.ts/,
        testIgnore: /auth\.setup\.ts/,
        use: {
          browserName,
          viewport: { width: 1440, height: 900 },
          colorScheme: "light" as const,
        },
        dependencies: ["setup"],
      }))
    : [];

/**
 * The suite runs against the already-running Compose stack. Authentication is a
 * real Keycloak browser login in the `setup` project; every flow project depends
 * on it and reads the per-role storage state written by `e2e/auth.setup.ts`.
 */
export default defineConfig({
  testDir: "./e2e",
  timeout: 90_000,
  expect: { timeout: 20_000 },
  fullyParallel: false,
  workers: 1,
  retries: 0,
  forbidOnly: Boolean(process.env.CI),
  reporter: [
    ["list"],
    ["html", { outputFolder: "playwright-report", open: "never" }],
  ],
  use: {
    baseURL,
    headless: true,
    trace: "retain-on-failure",
    screenshot: "only-on-failure",
    video: "off",
    actionTimeout: 20_000,
    navigationTimeout: 45_000,
  },
  projects: [
    {
      name: "setup",
      testMatch: /auth\.setup\.ts/,
    },
    {
      name: "chromium-desktop-light",
      testMatch: /.*\.spec\.ts/,
      testIgnore: [/theme\/.*\.spec\.ts/, /auth\.setup\.ts/],
      use: {
        browserName: "chromium",
        viewport: { width: 1440, height: 900 },
        colorScheme: "light",
      },
      dependencies: ["setup"],
    },
    {
      name: "chromium-desktop-dark",
      testMatch: /theme\/dark\.spec\.ts/,
      use: {
        browserName: "chromium",
        viewport: { width: 1440, height: 900 },
        colorScheme: "dark",
      },
      dependencies: ["setup"],
    },
    {
      name: "mobile-360",
      testMatch: /theme\/mobile\.spec\.ts/,
      use: {
        browserName: "chromium",
        viewport: { width: 360, height: 800 },
        screen: { width: 360, height: 800 },
        isMobile: true,
        hasTouch: true,
        deviceScaleFactor: 1,
        colorScheme: "light",
      },
      dependencies: ["setup"],
    },
    ...crossBrowserProjects,
  ],
});
