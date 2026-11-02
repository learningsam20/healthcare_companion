import { expect, test, type Page } from "@playwright/test";
import { copyFileSync, mkdirSync, readdirSync, statSync } from "node:fs";
import path from "node:path";

import { APP_URL, authFile, navigateTo, openApp, repoRoot } from "./support";

/**
 * Silent six-minute demo capture for G6.
 * Shows booking, cited answer (provenance sources), and signed note.
 * No narration — UI only. Video is retained and copied to docs/evidence/demo-recording/.
 */
test.describe.configure({ mode: "serial" });
test.use({
  video: "on",
  viewport: { width: 1440, height: 900 },
  storageState: { cookies: [], origins: [] },
});

const OUT_DIR = path.join(repoRoot, "docs/evidence/demo-recording");

async function titleCard(page: Page, lines: string[], holdMs: number): Promise<void> {
  const html = `<!doctype html><html><head><meta charset="utf-8"/>
<style>
html,body{margin:0;height:100%;background:#0b1f1c;color:#e7f3ef;
font-family:Georgia,"Times New Roman",serif;display:flex;align-items:center;justify-content:center}
.card{max-width:880px;padding:48px;text-align:center}
h1{font-size:42px;font-weight:600;margin:0 0 16px}
p{font-size:22px;line-height:1.45;margin:8px 0;opacity:.92}
.small{font-size:16px;opacity:.7;margin-top:28px}
</style></head><body><div class="card">
${lines.map((l, i) => (i === 0 ? `<h1>${l}</h1>` : `<p>${l}</p>`)).join("")}
<p class="small">Synthetic demo · not a medical device · no narration</p>
</div></body></html>`;
  await page.goto(`data:text/html,${encodeURIComponent(html)}`);
  await page.waitForTimeout(holdMs);
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

  const slotsResponse = page.waitForResponse(
    (response) =>
      /\/api\/v1\/doctors\/.+\/slots/.test(response.url()) && response.status() === 200,
    { timeout: 30_000 },
  );
  await page.getByTestId("appointments-doctor-input").fill("Dr. Ananya Rao");
  await slotsResponse;
  await page.waitForTimeout(800);

  const slots = page.getByTestId("appointments-slot");
  if ((await slots.count()) === 0) {
    await dialog.getByRole("button", { name: "Cancel" }).click();
    return null;
  }

  // When Rao maps to multiple specialities, force a catalogue code.
  const specialtyBox = page.getByRole("dialog").getByRole("combobox", { name: /Specialty/i });
  if (await specialtyBox.isVisible().catch(() => false)) {
    await specialtyBox.selectOption("general_medicine");
  }

  await page.locator(".slot-group").first().getByTestId("appointments-slot").first().click();

  const createResponsePromise = page.waitForResponse(
    (response) =>
      response.request().method() === "POST" &&
      /\/api\/v1\/appointments(?:\?|$)/.test(new URL(response.url()).pathname),
    { timeout: 30_000 },
  );
  await page.getByTestId("appointments-confirm-booking").click();
  const createResponse = await createResponsePromise;
  expect(
    createResponse.ok(),
    `booking POST failed: ${createResponse.status()} ${await createResponse.text()}`,
  ).toBeTruthy();
  const created = (await createResponse.json()) as { id: string };
  await expect(page.locator(".callout-success")).toContainText("Appointment booked successfully.");
  await page.waitForTimeout(2500);
  return { appointmentId: created.id };
}

test("silent demo: booking, cited answer, signed note", async ({ page, browser }, testInfo) => {
  test.setTimeout(420_000);
  testInfo.annotations.push({ type: "demo", description: "G6 silent six-minute capture" });

  await titleCard(
    page,
    [
      "Sahyog Care Companion",
      "Six-minute silent demo",
      "1 · Booking &nbsp;·&nbsp; 2 · Cited answer &nbsp;·&nbsp; 3 · Signed note",
    ],
    12_000,
  );

  // --- 1. Booking (front desk) ---
  await titleCard(page, ["1 · Booking", "Front desk books Priya with Dr. Ananya Rao"], 6_000);
  const desk = await browser.newContext({
    storageState: authFile("front_desk"),
    baseURL: APP_URL,
    recordVideo: { dir: testInfo.outputDir, size: { width: 1440, height: 900 } },
  });
  const deskPage = await desk.newPage();
  await openApp(deskPage);
  await navigateTo(deskPage, "Appointments");
  await deskPage.waitForTimeout(2000);
  const booking = await bookFirstAvailableSlot(deskPage);
  expect(booking, "demo requires a bookable slot").not.toBeNull();
  await deskPage.waitForTimeout(4000);
  await desk.close();

  // --- 2. Cited answer (patient chat with sources) ---
  await titleCard(page, ["2 · Cited answer", "Patient asks; assistant shows a source panel"], 6_000);
  const patient = await browser.newContext({
    storageState: authFile("patient"),
    baseURL: APP_URL,
    recordVideo: { dir: testInfo.outputDir, size: { width: 1440, height: 900 } },
  });
  const patientPage = await patient.newPage();
  await openApp(patientPage);
  await navigateTo(patientPage, "Assistant");
  await patientPage.getByTestId("chat-new-session").click();
  const dialog = patientPage.getByRole("dialog");
  await expect(dialog).toBeVisible();
  await dialog.locator("input").fill(`Demo cited ${Date.now()}`);
  await dialog.getByRole("button", { name: /^Create$/ }).click();
  await expect(dialog).toBeHidden();
  await patientPage.getByTestId("chat-composer").fill(
    "I have had a mild headache since this morning. What general steps should I take?",
  );
  await patientPage.getByTestId("chat-send").click();
  const assistant = patientPage.locator("article.message-assistant").last();
  await expect(assistant).toBeVisible({ timeout: 90_000 });
  const sources = assistant.getByTestId("chat-message-sources");
  await expect(sources).toBeVisible({ timeout: 30_000 });
  await sources.locator("summary").click();
  await expect(sources.locator(".source-card").first()).toBeVisible();
  await patientPage.waitForTimeout(8000);
  await patient.close();

  // --- 3. Signed note (doctor scribe) ---
  await titleCard(page, ["3 · Signed note", "Doctor drafts from transcript and signs"], 6_000);
  const doctor = await browser.newContext({
    storageState: authFile("doctor"),
    baseURL: APP_URL,
    recordVideo: { dir: testInfo.outputDir, size: { width: 1440, height: 900 } },
  });
  const doctorPage = await doctor.newPage();
  await openApp(doctorPage);
  await navigateTo(doctorPage, "Scribe");
  await doctorPage.getByTestId("scribe-new-encounter").click();
  const scribeDialog = doctorPage.getByRole("dialog");
  await expect(scribeDialog).toBeVisible();
  await scribeDialog.getByRole("button", { name: "Scheduled", exact: true }).click();
  const appointmentSelect = scribeDialog.locator("select");
  await expect
    .poll(async () => appointmentSelect.locator("option").count(), { timeout: 20_000 })
    .toBeGreaterThan(1);
  await expect
    .poll(
      () => appointmentSelect.locator(`option[value="${booking!.appointmentId}"]`).count(),
      { timeout: 20_000 },
    )
    .toBe(1);
  await appointmentSelect.selectOption(booking!.appointmentId);
  await doctorPage.getByTestId("scribe-start-encounter").click();
  await expect(scribeDialog).toBeHidden();
  await expect(doctorPage.locator(".scribe-workspace")).toBeVisible();
  const transcriptForm = doctorPage.getByTestId("scribe-transcript-editor");
  await expect(transcriptForm).toBeVisible({ timeout: 30_000 });
  await transcriptForm.getByRole("button", { name: /Add turn/i }).click();
  await transcriptForm.getByRole("button", { name: /Add turn/i }).click();
  const turns = transcriptForm.locator("textarea");
  await turns.nth(0).fill("The patient reports a mild headache for two days without fever.");
  await turns.nth(1).fill("It improves with rest and water, and there are no other symptoms.");
  await turns.nth(2).fill("Continue hydration and rest. Return if the headache worsens.");
  await doctorPage.getByTestId("scribe-submit-transcript").click();
  const generate = doctorPage.getByTestId("scribe-generate-draft");
  await expect(generate).toBeVisible({ timeout: 30_000 });
  await generate.click();
  // Draft generation can be slow on local 7B; allow up to three minutes.
  const acknowledge = doctorPage.getByRole("button", { name: /Acknowledge red flags/i });
  await acknowledge.click({ timeout: 180_000 }).catch(() => undefined);
  const openSign = doctorPage.getByTestId("scribe-open-sign");
  await expect(openSign).toBeVisible({ timeout: 180_000 });
  await openSign.click();
  await doctorPage.getByTestId("scribe-attestation").check();
  await doctorPage.getByTestId("scribe-confirm-sign").click();
  await expect(doctorPage.locator(".callout-success").first()).toContainText(
    /Note signed and locked/,
    { timeout: 60_000 },
  );
  await doctorPage.waitForTimeout(6000);
  await doctor.close();

  await titleCard(
    page,
    [
      "Demo complete",
      "Tier: pilot-shipable demo",
      "Gaps and caveats: docs/gaps.md · egress off",
    ],
    10_000,
  );

  // Ensure the default page video (title cards) is flushed.
  await page.goto(APP_URL + "/");
});

test.afterAll(async () => {
  // Copy the largest webm from this run's results into the evidence folder.
  mkdirSync(OUT_DIR, { recursive: true });
  const resultsRoot = path.join(repoRoot, "apps/web/test-results");
  const videos: string[] = [];
  const walk = (dir: string) => {
    let entries: string[] = [];
    try {
      entries = readdirSync(dir);
    } catch {
      return;
    }
    for (const name of entries) {
      const full = path.join(dir, name);
      const st = statSync(full);
      if (st.isDirectory()) walk(full);
      else if (name.endsWith(".webm")) videos.push(full);
    }
  };
  walk(resultsRoot);
  if (videos.length === 0) return;
  videos.sort((a, b) => statSync(b).size - statSync(a).size);
  const destWebm = path.join(OUT_DIR, "sahyog-demo-6min.webm");
  copyFileSync(videos[0], destWebm);
});
