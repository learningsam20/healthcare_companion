import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page } from "@playwright/test";
import { mkdirSync, readFileSync, writeFileSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
export const e2eRoot = here;
/** apps/web/e2e -> repository root. */
export const repoRoot = path.resolve(here, "../../..");
export const APP_URL = process.env.PLAYWRIGHT_BASE_URL ?? "http://localhost:5705";
export const ARTIFACTS_DIR = path.join(here, "artifacts");
export const AUTH_DIR = path.join(here, ".auth");
/**
 * Per-scan axe records consumed by `scripts/wcag_report.py` (G-36). Lives under
 * Playwright's outputDir, so each run starts from a clean slate and the report
 * only ever describes the latest run.
 */
export const AXE_SCANS_DIR = path.join(here, "..", "test-results", "axe-scans");

export const DEMO_USERS = {
  patient: "patient.priya",
  doctor: "doctor.rao",
  front_desk: "frontdesk.imran",
  compliance: "compliance.auditor",
  admin: "admin.ops",
} as const;

export type DemoRole = keyof typeof DEMO_USERS;

export function authFile(role: DemoRole): string {
  return path.join(AUTH_DIR, `${role}.json`);
}

/** Reads SEED_DEMO_PASSWORD at test time; the value is never logged. */
export function demoPassword(): string {
  const fromEnvironment = process.env.SEED_DEMO_PASSWORD?.trim();
  if (fromEnvironment) return fromEnvironment;

  const envPath = path.join(repoRoot, ".env");
  const text = readFileSync(envPath, "utf8");
  for (const rawLine of text.split(/\r?\n/)) {
    const line = rawLine.trim();
    if (!line || line.startsWith("#")) continue;
    const separator = line.indexOf("=");
    if (separator === -1) continue;
    const key = line.slice(0, separator).trim().replace(/^export\s+/, "");
    if (key !== "SEED_DEMO_PASSWORD") continue;
    const value = line
      .slice(separator + 1)
      .trim()
      .replace(/^(['"])(.*)\1$/, "$2");
    if (!value) break;
    return value;
  }
  throw new Error(`SEED_DEMO_PASSWORD is missing from ${envPath}`);
}

/**
 * Real browser login against the local Keycloak realm. No token is injected and
 * no auth state is reused: the caller must start from a clean context.
 */
export async function signInThroughKeycloak(page: Page, username: string): Promise<void> {
  await page.goto(`${APP_URL}/`);
  await page.waitForURL(/\/realms\/sahyog\/protocol\/openid-connect\/auth/, {
    timeout: 30_000,
  });
  await expect(page.locator("#username")).toBeVisible();
  await page.locator("#username").fill(username);
  await page.locator("#password").fill(demoPassword());
  await page.locator("#kc-login").click();

  // Keycloak redirects through /auth/callback; the SPA then replaces it with "/".
  await page.getByTestId("app-shell").waitFor({ state: "visible", timeout: 45_000 });
  await page.waitForURL((url) => url.origin === APP_URL && url.pathname === "/", {
    timeout: 30_000,
  });
  await expect(page.locator(".topbar-title")).toHaveText("Dashboard");
}

/** Loads the app with the role's saved Keycloak session and waits for the shell. */
export async function openApp(page: Page): Promise<void> {
  await page.goto("/");
  await page.getByTestId("app-shell").waitFor({ state: "visible", timeout: 45_000 });
  await page.waitForURL((url) => url.origin === APP_URL && url.pathname === "/", {
    timeout: 30_000,
  });
  await expect(page.locator(".topbar-title")).toHaveText("Dashboard");
}

/** Navigates through the visible shell links; deep links re-run OIDC and land on "/". */
export async function navigateTo(page: Page, linkName: string, heading = linkName): Promise<void> {
  const link = page.getByTestId("shell-nav").getByRole("link", { name: linkName, exact: true });
  await expect(link).toBeVisible();
  await link.click();
  await expect(page.getByRole("heading", { level: 1, name: heading })).toBeVisible();
}

function recordAxeScan(
  url: string,
  label: string,
  results: Awaited<ReturnType<AxeBuilder["analyze"]>>,
  blockingCount: number,
): void {
  try {
    mkdirSync(AXE_SCANS_DIR, { recursive: true });
    const project = test.info().project.name;
    const safe = `${project}__${label}`.replace(/[^a-zA-Z0-9_.-]+/g, "_");
    const record = {
      label,
      project,
      url,
      scannedAt: new Date().toISOString(),
      axeVersion: results.testEngine?.version ?? null,
      tags: ["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"],
      seriousOrCriticalCount: blockingCount,
      violations: results.violations.map((violation) => ({
        id: violation.id,
        impact: violation.impact ?? null,
        help: violation.help,
        nodes: violation.nodes.length,
        tags: violation.tags.filter((tag) => tag.startsWith("wcag")),
      })),
      passes: results.passes.length,
      incomplete: results.incomplete.map((item) => item.id),
    };
    writeFileSync(path.join(AXE_SCANS_DIR, `${safe}.json`), JSON.stringify(record, null, 2));
  } catch {
    // Reporting must never change a test verdict.
  }
}

export interface AxeScanResult {
  seriousOrCritical: number;
  total: number;
}

/**
 * Runs axe with the WCAG A/AA tag set and fails on serious or critical impact.
 * Third-party iframes are not excluded; this app renders none. The local
 * Keycloak sign-in page is scanned as the actual authentication surface.
 */
export async function expectNoSeriousAxeViolations(
  page: Page,
  label: string,
): Promise<AxeScanResult> {
  await page.evaluate(async () => {
    await document.fonts.ready;
  });
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const blocking = results.violations.filter(
    (violation) => violation.impact === "serious" || violation.impact === "critical",
  );

  recordAxeScan(page.url(), label, results, blocking.length);

  await test.info().attach(`axe-${label}.json`, {
    body: JSON.stringify(
      {
        url: page.url(),
        seriousOrCritical: blocking.map((violation) => violation.id),
        violations: results.violations,
      },
      null,
      2,
    ),
    contentType: "application/json",
  });

  const summary = blocking
    .map(
      (violation) =>
        `- ${violation.id} [${violation.impact}] ${violation.nodes.length} node(s): ${violation.help}`,
    )
    .join("\n");
  expect(
    blocking,
    blocking.length
      ? `axe found serious/critical violations on ${label} (${page.url()}):\n${summary}`
      : "",
  ).toEqual([]);

  return { seriousOrCritical: blocking.length, total: results.violations.length };
}

export async function captureScreenshot(page: Page, filename: string): Promise<string> {
  mkdirSync(ARTIFACTS_DIR, { recursive: true });
  const target = path.join(ARTIFACTS_DIR, filename);
  await page.screenshot({ path: target, fullPage: true });
  await test.info().attach(filename, { path: target, contentType: "image/png" });
  return target;
}
