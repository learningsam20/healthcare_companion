import { expect, test, type Browser, type BrowserContext, type Page } from "@playwright/test";
import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  statSync,
  writeFileSync,
} from "node:fs";
import path from "node:path";
import { pathToFileURL } from "node:url";

import { APP_URL, authFile, navigateTo, openApp, repoRoot, type DemoRole } from "./support";

/**
 * Product walkthrough (docs/demo.md §8.2): intro slides, continuous E1–E6 takes,
 * NFR slide, telemetry (admin + Grafana), roadmap. No "demo" labels in UI text.
 * Assemble trims idle tails so narration and picture stay aligned.
 */
test.describe.configure({ mode: "serial" });
test.use({
  video: "off",
  viewport: { width: 1440, height: 900 },
  storageState: { cookies: [], origins: [] },
});

const OUT_DIR = path.join(repoRoot, "docs/evidence/demo-recording");
const CLIPS_DIR = path.join(OUT_DIR, "clips");
const SLIDES = path.join(OUT_DIR, "slides.html");
const SIZE = { width: 1440, height: 900 } as const;

type ClipKind = "slide" | "workflow";

interface ManifestChapter {
  id: string;
  kind: ClipKind;
  file: string;
  narration: string;
}

const MANIFEST: ManifestChapter[] = [
  {
    id: "01-overview",
    kind: "slide",
    file: "01-overview.webm",
    narration:
      "Sahyog Care Companion — triage, booking, cited records, and signed notes for Indian clinics. Synthetic data. Not a medical device. External egress stays off.",
  },
  {
    id: "02-architecture",
    kind: "slide",
    file: "02-architecture.webm",
    narration:
      "Technical architecture: web and Keycloak at the edge; FastAPI with LangGraph, ARQ workers, and the MCP broker; Postgres with pgvector, Redis, and object storage; red-flag rules and PII before any external model; Langfuse, Prometheus, and Grafana for observability. External models are de-identified only when egress is enabled.",
  },
  {
    id: "03-stack",
    kind: "slide",
    file: "03-stack.webm",
    narration:
      "Stack: Vite React and FastAPI, Keycloak and Postgres, LiteLLM and LangGraph through MCP, local Ollama models, and Compose with Kubernetes-ready manifests.",
  },
  {
    id: "04-flows",
    kind: "slide",
    file: "04-flows.webm",
    narration:
      "Six live workflows next, then non-functional targets and telemetry.",
  },
  {
    id: "05-e1",
    kind: "workflow",
    file: "05-e1.webm",
    narration:
      "E1 — Find my doctor. Priya lands on the patient dashboard, opens Assistant, creates a session, and describes a routine sore throat near Baner. Deterministic red-flag rules run before the model. Watch the reply, then Notifications for in-app updates.",
  },
  {
    id: "06-e2",
    kind: "workflow",
    file: "06-e2.webm",
    narration:
      "E2 — Book and manage. Front desk Imran opens Appointments, selects Priya Sharma and Doctor Ananya Rao, confirms a real clinic slot, then opens the Front desk workspace and Waitlist so desk tools sit beside the booking grid.",
  },
  {
    id: "07-e3",
    kind: "workflow",
    file: "07-e3.webm",
    narration:
      "E3 — My records. Priya opens Records, reviews the Documents list, then switches to Medications. Everything stays patient-scoped.",
  },
  {
    id: "08-e4",
    kind: "workflow",
    file: "08-e4.webm",
    narration:
      "E4 — Ask my record. Priya asks what problems and medicines appear in her visit summary. The assistant answers and we expand Sources — each card is her own document, never another patient's chunk.",
  },
  {
    id: "09-e5",
    kind: "workflow",
    file: "09-e5.webm",
    narration:
      "E5 — Scribe. Doctor Rao starts a walk-in for Priya, enters transcript turns, saves them, generates a local draft, acknowledges any flags, and signs with attestation. The note locks only after the human signature. We finish on Clinical notes.",
  },
  {
    id: "10-e6",
    kind: "workflow",
    file: "10-e6.webm",
    narration:
      "E6 — Platform safety. Compliance opens Analytics, reviews metric tiles, opens the Compliance tab, then Governance for the control surface — aggregate views only.",
  },
  {
    id: "11-nfr",
    kind: "slide",
    file: "11-nfr.webm",
    narration:
      "Non-functional summary: triage and ask latency targets, fourteen hundred requests per hour with burst headroom, identified scribe text stays local, red flags fail closed, FinOps attribution, and OTLP with Prometheus and Grafana for operations evidence.",
  },
  {
    id: "12-telemetry",
    kind: "workflow",
    file: "12-telemetry.webm",
    narration:
      "Observability. Admin opens FinOps tiles, checks Ops console readiness, then Prometheus scrape targets and Grafana dashboards. Traces and metrics carry metadata only — no clinical content.",
  },
  {
    id: "13-roadmap",
    kind: "slide",
    file: "13-roadmap.webm",
    narration:
      "Roadmap: core pilot, clinical depth, then scale. Post-handover work needs a change order.",
  },
  {
    id: "14-thanks",
    kind: "slide",
    file: "14-thanks.webm",
    narration:
      "Thank you. Gaps are listed in docs gaps. Architecture diagrams and the bill of materials are filed under docs.",
  },
];

const SLIDE_HOLD_MS: Record<string, number> = {
  overview: 16_000,
  architecture: 26_000,
  stack: 16_000,
  flows: 10_000,
  nfr: 22_000,
  roadmap: 13_000,
  thanks: 11_000,
};

const SLICER_HOLD_MS = 2_800;

function newestWebm(dir: string): string | null {
  if (!existsSync(dir)) return null;
  const videos: string[] = [];
  const walk = (d: string) => {
    for (const name of readdirSync(d)) {
      const full = path.join(d, name);
      const st = statSync(full);
      if (st.isDirectory()) walk(full);
      else if (name.endsWith(".webm")) videos.push(full);
    }
  };
  walk(dir);
  if (videos.length === 0) return null;
  videos.sort((a, b) => statSync(b).mtimeMs - statSync(a).mtimeMs);
  return videos[0];
}

function clipReady(destName: string): boolean {
  const full = path.join(CLIPS_DIR, destName);
  if (!existsSync(full)) return false;
  return statSync(full).size > 40_000;
}

async function recordedContext(
  browser: Browser,
  role: DemoRole | null,
  rawDir: string,
): Promise<BrowserContext> {
  mkdirSync(rawDir, { recursive: true });
  return browser.newContext({
    storageState: role ? authFile(role) : { cookies: [], origins: [] },
    baseURL: APP_URL,
    viewport: SIZE,
    recordVideo: { dir: rawDir, size: SIZE },
  });
}

async function finalizeClip(context: BrowserContext, rawDir: string, destName: string): Promise<void> {
  for (const p of context.pages()) await p.close().catch(() => undefined);
  await context.close();
  await new Promise((r) => setTimeout(r, 900));
  const src = newestWebm(rawDir);
  if (!src) throw new Error(`No webm produced in ${rawDir}`);
  copyFileSync(src, path.join(CLIPS_DIR, destName));
  rmSync(rawDir, { recursive: true, force: true });
}

async function showSlicer(page: Page, slideId: string): Promise<void> {
  const url = `${pathToFileURL(SLIDES).href}?slide=${encodeURIComponent(slideId)}`;
  await page.goto(url);
  await page.waitForFunction(
    (id) => Boolean(document.querySelector(`.slide[data-slide="${id}"].active`)),
    slideId,
    { timeout: 15_000 },
  );
  await page.waitForTimeout(SLICER_HOLD_MS);
}

async function captureSlide(
  browser: Browser,
  slideId: string,
  destName: string,
  holdMs: number,
): Promise<void> {
  if (process.env.DEMO_REEL_RESUME === "1" && clipReady(destName)) return;
  const rawDir = path.join(CLIPS_DIR, `_raw_${destName}`);
  rmSync(rawDir, { recursive: true, force: true });
  const context = await recordedContext(browser, null, rawDir);
  const page = await context.newPage();
  await page.goto(`${pathToFileURL(SLIDES).href}?slide=${encodeURIComponent(slideId)}`);
  await page.waitForFunction(
    (id) => Boolean(document.querySelector(`.slide[data-slide="${id}"].active`)),
    slideId,
    { timeout: 15_000 },
  );
  if (slideId === "architecture") await page.waitForTimeout(3200);
  await page.waitForTimeout(holdMs);
  await finalizeClip(context, rawDir, destName);
}

async function bookFirstAvailableSlot(page: Page): Promise<{ appointmentId: string } | null> {
  await page.getByTestId("appointments-book").click();
  const dialog = page.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await page.getByTestId("patient-picker-trigger").click({ trial: true }).catch(() => undefined);
  await page.getByTestId("patient-picker-trigger").click();
  const patientOption = page
    .getByTestId("patient-picker-option")
    .filter({ hasText: "Priya Sharma" })
    .first();
  await expect(patientOption).toBeVisible();
  await patientOption.click();
  await page.waitForTimeout(600);

  const slotsResponse = page.waitForResponse(
    (response) =>
      /\/api\/v1\/doctors\/.+\/slots/.test(response.url()) && response.status() === 200,
    { timeout: 30_000 },
  );
  await page.getByTestId("appointments-doctor-input").fill("Dr. Ananya Rao");
  await slotsResponse;
  await page.waitForTimeout(800);

  if ((await page.getByTestId("appointments-slot").count()) === 0) {
    await dialog.getByRole("button", { name: "Cancel" }).click();
    return null;
  }
  const specialtyBox = page.getByRole("dialog").getByRole("combobox", { name: /Specialty/i });
  if (await specialtyBox.isVisible().catch(() => false)) {
    await specialtyBox.selectOption("general_medicine");
  }
  await page.locator(".slot-group").first().getByTestId("appointments-slot").first().click();
  await page.waitForTimeout(500);

  const createResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/appointments(?:\?|$)/.test(new URL(response.url()).pathname),
    { timeout: 30_000 },
  );
  await page.getByTestId("appointments-confirm-booking").click();
  const createResponse = await createResponsePromise;
  expect(createResponse.ok(), await createResponse.text()).toBeTruthy();
  const created = (await createResponse.json()) as { id: string };
  await expect(page.locator(".callout-success")).toContainText("Appointment booked successfully.");
  await page.waitForTimeout(2500);
  return { appointmentId: created.id };
}

test("product walkthrough: slides + workflows + NFR + telemetry", async ({ browser }, testInfo) => {
  test.skip(process.env.DEMO_REEL !== "1", "set DEMO_REEL=1 to capture the product reel");
  test.setTimeout(900_000);
  testInfo.annotations.push({ type: "demo", description: "product walkthrough reel" });

  mkdirSync(CLIPS_DIR, { recursive: true });
  for (const name of readdirSync(CLIPS_DIR)) {
    if (name.startsWith("_raw_")) rmSync(path.join(CLIPS_DIR, name), { recursive: true, force: true });
  }

  await captureSlide(browser, "overview", "01-overview.webm", SLIDE_HOLD_MS.overview);
  await captureSlide(browser, "architecture", "02-architecture.webm", SLIDE_HOLD_MS.architecture);
  await captureSlide(browser, "stack", "03-stack.webm", SLIDE_HOLD_MS.stack);
  await captureSlide(browser, "flows", "04-flows.webm", SLIDE_HOLD_MS.flows);

  // E1 patient: dashboard → assistant → notifications
  if (!(process.env.DEMO_REEL_RESUME === "1" && clipReady("05-e1.webm"))) {
    const rawDir = path.join(CLIPS_DIR, "_raw_05-e1.webm");
    rmSync(rawDir, { recursive: true, force: true });
    const context = await recordedContext(browser, "patient", rawDir);
    const page = await context.newPage();
    await showSlicer(page, "e1");
    await openApp(page);
    await page.waitForTimeout(2800);
    await navigateTo(page, "Assistant");
    await page.waitForTimeout(1800);
    await page.getByTestId("chat-new-session").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.locator("input").fill(`Priya Baner intake ${Date.now()}`);
    await dialog.getByRole("button", { name: /^Create$/ }).click();
    await expect(dialog).toBeHidden();
    await page.getByTestId("chat-composer").fill(
      "I have a sore throat and mild cough for 3 days. No fever. Looking for a doctor near Baner.",
    );
    await page.waitForTimeout(700);
    await page.getByTestId("chat-send").click();
    const assistant = page.locator("article.message-assistant").last();
    await expect(assistant).toBeVisible({ timeout: 90_000 });
    await expect(assistant.locator(".message-body")).not.toBeEmpty();
    await page.waitForTimeout(6000);
    await navigateTo(page, "Notifications");
    await page.waitForTimeout(8000);
    await finalizeClip(context, rawDir, "05-e1.webm");
  }

  // E2 front desk: appointments → front desk → waitlist
  if (!(process.env.DEMO_REEL_RESUME === "1" && clipReady("06-e2.webm"))) {
    const rawDir = path.join(CLIPS_DIR, "_raw_06-e2.webm");
    rmSync(rawDir, { recursive: true, force: true });
    const context = await recordedContext(browser, "front_desk", rawDir);
    const page = await context.newPage();
    await showSlicer(page, "e2");
    await openApp(page);
    await page.waitForTimeout(2000);
    await navigateTo(page, "Appointments");
    await page.waitForTimeout(2200);
    const booking = await bookFirstAvailableSlot(page);
    expect(booking, "bookable slot required").not.toBeNull();
    await page.waitForTimeout(3500);
    await navigateTo(page, "Front desk");
    await page.waitForTimeout(5500);
    await navigateTo(page, "Waitlist");
    await page.waitForTimeout(6000);
    await finalizeClip(context, rawDir, "06-e2.webm");
  }

  // E3 records: documents + medications
  if (!(process.env.DEMO_REEL_RESUME === "1" && clipReady("07-e3.webm"))) {
    const rawDir = path.join(CLIPS_DIR, "_raw_07-e3.webm");
    rmSync(rawDir, { recursive: true, force: true });
    const context = await recordedContext(browser, "patient", rawDir);
    const page = await context.newPage();
    await showSlicer(page, "e3");
    await openApp(page);
    await page.waitForTimeout(1800);
    await navigateTo(page, "Records");
    await page.waitForTimeout(2200);
    const docsTab = page.getByRole("tab", { name: /Documents/i });
    if (await docsTab.isVisible().catch(() => false)) {
      await docsTab.click();
      await page.waitForTimeout(4500);
    }
    const medsTab = page.getByRole("tab", { name: /Medications/i });
    if (await medsTab.isVisible().catch(() => false)) {
      await medsTab.click();
      await page.waitForTimeout(6000);
    }
    await page.waitForTimeout(4000);
    await finalizeClip(context, rawDir, "07-e3.webm");
  }

  // E4 cited ask
  if (!(process.env.DEMO_REEL_RESUME === "1" && clipReady("08-e4.webm"))) {
    const rawDir = path.join(CLIPS_DIR, "_raw_08-e4.webm");
    rmSync(rawDir, { recursive: true, force: true });
    const context = await recordedContext(browser, "patient", rawDir);
    const page = await context.newPage();
    await showSlicer(page, "e4");
    await openApp(page);
    await page.waitForTimeout(1600);
    await navigateTo(page, "Assistant");
    await page.waitForTimeout(1500);
    await page.getByTestId("chat-new-session").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.locator("input").fill(`Priya visit summary ask ${Date.now()}`);
    await dialog.getByRole("button", { name: /^Create$/ }).click();
    await expect(dialog).toBeHidden();
    await page.getByTestId("chat-composer").fill(
      "What problems and medicines are listed in my recent visit summary? Cite the document.",
    );
    await page.waitForTimeout(600);
    await page.getByTestId("chat-send").click();
    const assistant = page.locator("article.message-assistant").last();
    await expect(assistant).toBeVisible({ timeout: 90_000 });
    const sources = assistant.getByTestId("chat-message-sources");
    await expect(sources).toBeVisible({ timeout: 45_000 });
    await page.waitForTimeout(1200);
    await sources.locator("summary").click();
    await expect(sources.locator(".source-card").first()).toBeVisible();
    await page.waitForTimeout(9000);
    await finalizeClip(context, rawDir, "08-e4.webm");
  }

  // E5 scribe walk-in
  if (!(process.env.DEMO_REEL_RESUME === "1" && clipReady("09-e5.webm"))) {
    const rawDir = path.join(CLIPS_DIR, "_raw_09-e5.webm");
    rmSync(rawDir, { recursive: true, force: true });
    const context = await recordedContext(browser, "doctor", rawDir);
    const page = await context.newPage();
    await showSlicer(page, "e5");
    await openApp(page);
    await page.waitForTimeout(1500);
    await navigateTo(page, "Scribe");
    await page.waitForTimeout(1800);
    await page.getByTestId("scribe-new-encounter").click();
    const scribeDialog = page.getByRole("dialog");
    await expect(scribeDialog).toBeVisible();
    await scribeDialog.getByRole("button", { name: /Walk-?in/i }).click();
    await page.waitForTimeout(500);
    await page.getByTestId("patient-picker-trigger").click();
    await page
      .getByTestId("patient-picker-option")
      .filter({ hasText: "Priya Sharma" })
      .first()
      .click();
    await page.waitForTimeout(600);
    const createPromise = page.waitForResponse(
      (response) =>
        response.request().method() === "POST" &&
        /\/api\/v1\/scribe\/encounters(?:\?|$)/.test(new URL(response.url()).pathname),
      { timeout: 30_000 },
    );
    await page.getByTestId("scribe-start-encounter").click();
    const createResponse = await createPromise;
    expect(createResponse.ok(), await createResponse.text()).toBeTruthy();
    await expect(scribeDialog).toBeHidden({ timeout: 30_000 });
    const workspace = page.locator(".scribe-workspace");
    if (!(await workspace.isVisible().catch(() => false))) {
      await page.locator("table tbody tr").first().click();
    }
    await expect(workspace).toBeVisible({ timeout: 20_000 });
    const transcriptForm = page.getByTestId("scribe-transcript-editor");
    await expect(transcriptForm).toBeVisible({ timeout: 30_000 });
    await transcriptForm.getByRole("button", { name: /Add turn/i }).click();
    await transcriptForm.getByRole("button", { name: /Add turn/i }).click();
    const speakerSelects = transcriptForm.getByLabel(/Speaker/i);
    await speakerSelects.nth(0).selectOption("doctor");
    await speakerSelects.nth(1).selectOption("patient");
    await speakerSelects.nth(2).selectOption("doctor");
    const turns = transcriptForm.locator("textarea");
    await turns.nth(0).fill("Good morning. What brings you in today?");
    await turns
      .nth(1)
      .fill("Sore throat and mild cough for three days. No fever. Cetirizine at night for allergies.");
    await turns
      .nth(2)
      .fill(
        "Viral URI likely. Supportive care, warm fluids, continue cetirizine. Follow up in one week if worse.",
      );
    await page.getByTestId("scribe-submit-transcript").click();
    await page.waitForTimeout(1500);
    const generate = page.getByTestId("scribe-generate-draft");
    await expect(generate).toBeVisible({ timeout: 30_000 });
    const openSign = page.getByTestId("scribe-open-sign");
    let signed = false;
    for (let attempt = 0; attempt < 3 && !signed; attempt += 1) {
      await generate.click();
      await page
        .getByRole("button", { name: /Acknowledge red flags/i })
        .click({ timeout: 150_000 })
        .catch(() => undefined);
      signed = await openSign
        .waitFor({ state: "visible", timeout: 150_000 })
        .then(async () => {
          await openSign.click();
          await page.getByTestId("scribe-attestation").check();
          await page.getByTestId("scribe-confirm-sign").click();
          await expect(page.locator(".callout-success").first()).toContainText(/Note signed and locked/, {
            timeout: 60_000,
          });
          return true;
        })
        .catch(() => false);
      if (!signed) {
        await page.waitForTimeout(2500);
      }
    }
    expect(signed, "E5 must produce a signed note for a professional reel").toBeTruthy();
    await page.waitForTimeout(4000);
    const notesLink = page.getByTestId("shell-nav").getByRole("link", { name: /Clinical notes/i });
    if (await notesLink.isVisible().catch(() => false)) {
      await notesLink.click();
      await page.waitForTimeout(3500);
    }
    await finalizeClip(context, rawDir, "09-e5.webm");
  }

  // E6 compliance + admin FinOps/ops
  if (!(process.env.DEMO_REEL_RESUME === "1" && clipReady("10-e6.webm"))) {
    const rawDir = path.join(CLIPS_DIR, "_raw_10-e6.webm");
    rmSync(rawDir, { recursive: true, force: true });
    const context = await recordedContext(browser, "compliance", rawDir);
    const page = await context.newPage();
    await showSlicer(page, "e6");
    await openApp(page);
    await page.waitForTimeout(1600);
    await navigateTo(page, "Analytics");
    await expect(page.locator(".metric-tile").first()).toBeVisible();
    await page.waitForTimeout(2800);
    await page.getByRole("tab", { name: "Compliance" }).click();
    await page.waitForTimeout(4500);
    await navigateTo(page, "Governance");
    await page.waitForTimeout(7000);
    await finalizeClip(context, rawDir, "10-e6.webm");

    // Append admin FinOps/ops into a second context merged? Keep separate telemetry chapter.
  }

  await captureSlide(browser, "nfr", "11-nfr.webm", SLIDE_HOLD_MS.nfr);

  // Telemetry: admin FinOps + Ops + Prometheus + Grafana
  if (!(process.env.DEMO_REEL_RESUME === "1" && clipReady("12-telemetry.webm"))) {
    const rawDir = path.join(CLIPS_DIR, "_raw_12-telemetry.webm");
    rmSync(rawDir, { recursive: true, force: true });
    const context = await recordedContext(browser, "admin", rawDir);
    const page = await context.newPage();
    await showSlicer(page, "telemetry");
    await openApp(page);
    await page.waitForTimeout(1500);
    await navigateTo(page, "Analytics");
    await page.waitForTimeout(1500);
    const finops = page.getByRole("tab", { name: "FinOps" });
    if (await finops.isVisible().catch(() => false)) {
      await finops.click();
      await page.waitForTimeout(5500);
    }
    await navigateTo(page, "Ops console");
    await page.waitForTimeout(6000);
    await page.goto("http://127.0.0.1:5722/targets");
    await page.waitForTimeout(5000);
    await page.goto("http://127.0.0.1:5723/login");
    await page.waitForTimeout(1500);
    const user = page.locator('input[name="user"]');
    if (await user.isVisible().catch(() => false)) {
      await user.fill("admin");
      const pw = process.env.GRAFANA_ADMIN_PASSWORD?.trim() || "admin";
      await page.locator('input[name="password"]').fill(pw);
      await page.locator('button[type="submit"]').click().catch(() => undefined);
      await page.waitForTimeout(3000);
    }
    await page.goto("http://127.0.0.1:5723/dashboards").catch(() => undefined);
    await page.waitForTimeout(7000);
    await finalizeClip(context, rawDir, "12-telemetry.webm");
  }

  await captureSlide(browser, "roadmap", "13-roadmap.webm", SLIDE_HOLD_MS.roadmap);
  await captureSlide(browser, "thanks", "14-thanks.webm", SLIDE_HOLD_MS.thanks);

  writeFileSync(path.join(OUT_DIR, "manifest.json"), JSON.stringify({ chapters: MANIFEST }, null, 2));
  for (const chapter of MANIFEST) {
    const full = path.join(CLIPS_DIR, chapter.file);
    expect(existsSync(full), `missing ${chapter.file}`).toBeTruthy();
    expect(statSync(full).size).toBeGreaterThan(20_000);
  }
});
