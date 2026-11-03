import { expect, test, type Page } from "@playwright/test";

import {
  APP_URL,
  DEMO_USERS,
  authFile,
  navigateTo,
  openApp,
  signInThroughKeycloak,
} from "./support";

interface BookingResult {
  appointmentId: string;
}

/**
 * Books Priya's first available slot with Dr. Ananya Rao through the real UI.
 * Returns null when the calendar has no free slots so callers can skip honestly.
 */
async function bookFirstAvailableSlot(page: Page): Promise<BookingResult | null> {
  await page.getByTestId("appointments-book").click();
  const panel = page.getByTestId("appointments-book-panel");
  await expect(panel).toBeVisible();

  await panel.getByTestId("patient-picker-trigger").click();
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
  await panel.getByTestId("appointments-doctor-input").fill("Dr. Ananya Rao");
  await slotsResponse;
  await page.waitForTimeout(500);

  const slots = panel.getByTestId("appointments-slot");
  if ((await slots.count()) === 0) {
    await panel.getByRole("button", { name: "Cancel" }).click();
    return null;
  }

  // Catalogue code (not British "paediatrics"); set when the specialty picker is shown.
  const specialtyBox = panel.getByRole("combobox", { name: /Specialty/i });
  if (await specialtyBox.isVisible().catch(() => false)) {
    await specialtyBox.selectOption("general_medicine");
  }

  const firstGroup = panel.locator(".slot-group").first();
  await firstGroup.getByTestId("appointments-slot").first().click();

  const createResponse = page.waitForResponse(
    (response) =>
      /\/api\/v1\/appointments$/.test(response.url()) &&
      response.request().method() === "POST" &&
      response.ok(),
  );
  await page.getByTestId("appointments-confirm-booking").click();
  const created = (await (await createResponse).json()) as { id: string };

  await expect(page.locator(".callout-success")).toContainText(
    "Appointment booked successfully.",
  );
  return { appointmentId: created.id };
}

test.describe("sign-in and shell navigation", () => {
  test.use({ storageState: { cookies: [], origins: [] } });

  test("patient signs in through Keycloak and navigates the shell", async ({ page }) => {
    await signInThroughKeycloak(page, DEMO_USERS.patient);

    await expect(page.locator(".user-trigger")).toContainText("Priya Sharma");
    await expect(page.getByTestId("shell-nav")).toBeVisible();

    await navigateTo(page, "Assistant");
    await expect(page.getByTestId("chat-composer")).toBeVisible();

    await navigateTo(page, "Appointments");
    await expect(page.getByTestId("appointment-timeline-item").first()).toBeVisible();

    await navigateTo(page, "Dashboard", "Welcome, Priya");
    await expect(page.getByTestId("app-shell")).toBeVisible();
  });
});

test.describe("chat", () => {
  test.use({ storageState: authFile("patient") });

  test("creates a session, sends a message and shows provenance", async ({ page }) => {
    test.setTimeout(120_000);
    await openApp(page);
    await navigateTo(page, "Assistant");

    await page.getByTestId("chat-new-session").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const title = `E2E chat ${Date.now()}`;
    await dialog.locator("input").fill(title);
    await dialog.getByRole("button", { name: /^Create$/ }).click();
    await expect(dialog).toBeHidden();
    await expect(page.locator(".chat-header h2")).toHaveText(title);

    await page.getByTestId("chat-composer").fill(
      "I have had a mild headache since this morning. What general steps should I take?",
    );
    await page.getByTestId("chat-send").click();

    const assistant = page.locator("article.message-assistant").last();
    await expect(assistant).toBeVisible({ timeout: 60_000 });
    await expect(assistant.locator(".message-body")).not.toBeEmpty();
    await expect(page.locator(".form-error")).toHaveCount(0);

    const sources = assistant.getByTestId("chat-message-sources");
    await expect(sources).toBeVisible();
    await expect(sources.locator("summary")).toContainText(/Sources \(\d+\)/);
    const summary = await sources.locator("summary").innerText();
    const count = Number(/\((\d+)\)/.exec(summary)?.[1] ?? 0);
    expect(count, "assistant reply must include at least one source").toBeGreaterThan(0);
    await sources.locator("summary").click();
    await expect(sources.locator(".source-card").first()).toBeVisible();
  });

  test("books a discrete slot via chat interrupt (G-39)", async ({ page }) => {
    test.setTimeout(180_000);
    await openApp(page);
    await navigateTo(page, "Assistant");

    await page.getByTestId("chat-new-session").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    const title = `E2E book ${Date.now()}`;
    await dialog.locator("input").fill(title);
    await dialog.getByRole("button", { name: /^Create$/ }).click();
    await expect(dialog).toBeHidden();

    await page.getByTestId("chat-composer").fill(
      "Please book an appointment today at 3 pm for a mild fever and cough, not an emergency.",
    );
    await page.getByTestId("chat-send").click();

    const interrupt = page.getByTestId("chat-booking-interrupt");
    await expect(interrupt).toBeVisible({ timeout: 90_000 });
    await expect(interrupt).toContainText(/specialty|slot/i);
    const firstSlot = page.getByTestId("chat-slot-choice-1");
    await expect(firstSlot).toBeVisible();
    await firstSlot.click();

    // Soft-hold then confirm (booking card + hold countdown).
    const holdCard = page.getByTestId("chat-booking-hold");
    await expect(holdCard).toBeVisible({ timeout: 60_000 });
    await expect(page.getByTestId("chat-hold-countdown")).toBeVisible();
    await page.getByTestId("chat-confirm-hold").click();

    await expect(page.getByText(/Booking confirmed|बुकिंग/i)).toBeVisible({ timeout: 30_000 });
    await expect(page.getByTestId("chat-booking-interrupt")).toHaveCount(0);
    await expect(page.getByTestId("chat-booking-hold")).toHaveCount(0);
  });
});

test.describe("appointments", () => {
  test.use({ storageState: authFile("front_desk") });

  test("lists appointments and books an available slot", async ({ page }) => {
    await openApp(page);
    await navigateTo(page, "Appointments");

    const rows = page.getByTestId("appointment-timeline-item");
    expect(await rows.count(), "seeded appointments should be visible to the front desk").toBeGreaterThan(0);

    const booking = await bookFirstAvailableSlot(page);
    if (!booking) {
      test.skip(
        true,
        "No bookable slots for Dr. Ananya Rao in the next seven days; nothing to book.",
      );
    }
  });
});

test.describe("scribe", () => {
  test.use({ storageState: authFile("doctor") });

  test("creates an encounter, drafts from a transcript and signs the note", async ({
    page,
    browser,
  }) => {
    test.setTimeout(180_000);

    // No encounter is seeded in the demo data, and the walk-in form does not
    // collect the treating doctor (the API rejects it). Book a fresh confirmed
    // appointment through the real front-desk UI, then attach a scheduled
    // encounter as the doctor. This keeps the transcript -> draft -> sign path
    // repeatable without reusing an already signed encounter.
    const deskContext = await browser.newContext({
      storageState: authFile("front_desk"),
      baseURL: APP_URL,
    });
    const deskPage = await deskContext.newPage();
    await openApp(deskPage);
    await navigateTo(deskPage, "Appointments");
    const booking = await bookFirstAvailableSlot(deskPage);
    await deskContext.close();
    if (!booking) {
      test.skip(true, "No bookable slot was available to create a scheduled encounter.");
      return;
    }

    await openApp(page);
    await navigateTo(page, "Scribe");
    await page.getByTestId("scribe-new-encounter").click();
    const dialog = page.getByRole("dialog");
    await expect(dialog).toBeVisible();
    await dialog.getByRole("button", { name: "Scheduled", exact: true }).click();

    const appointmentSelect = dialog.locator("select");
    await expect
      .poll(async () => appointmentSelect.locator("option").count(), { timeout: 20_000 })
      .toBeGreaterThan(1);
    // Select the exact appointment we just booked. Older runs leave bookings at
    // the same day/time, so label matching could attach to a used encounter.
    await expect
      .poll(
        () => appointmentSelect.locator(`option[value="${booking.appointmentId}"]`).count(),
        { timeout: 20_000 },
      )
      .toBe(1);
    await appointmentSelect.selectOption(booking.appointmentId);
    await page.getByTestId("scribe-start-encounter").click();
    await expect(dialog).toBeHidden();

    await expect(page.locator(".scribe-workspace")).toBeVisible();
    const transcriptForm = page.getByTestId("scribe-transcript-editor");
    await expect(transcriptForm).toBeVisible({ timeout: 30_000 });
    await transcriptForm.getByRole("button", { name: /Add turn/i }).click();
    await transcriptForm.getByRole("button", { name: /Add turn/i }).click();
    const turns = transcriptForm.locator("textarea");
    await turns.nth(0).fill("The patient reports a mild headache for two days without fever.");
    await turns.nth(1).fill("It improves with rest and water, and there are no other symptoms.");
    await turns.nth(2).fill("Continue hydration and rest. Return if the headache worsens.");
    await page.getByTestId("scribe-submit-transcript").click();

    const generate = page.getByTestId("scribe-generate-draft");
    await expect(generate).toBeVisible({ timeout: 30_000 });
    await generate.click();

    const acknowledge = page.getByRole("button", { name: /Acknowledge red flags/i });
    await acknowledge.click({ timeout: 120_000 }).catch(() => undefined);

    const openSign = page.getByTestId("scribe-open-sign");
    await expect(openSign).toBeVisible({ timeout: 180_000 });
    await openSign.click();
    await page.getByTestId("scribe-attestation").check();
    await page.getByTestId("scribe-confirm-sign").click();

    await expect(page.locator(".callout-success").first()).toContainText(
      /Note signed and locked/,
      { timeout: 30_000 },
    );
  });
});

test.describe("analytics", () => {
  test.describe("compliance", () => {
    test.use({ storageState: authFile("compliance") });

    test("compliance user sees metrics and the compliance tab", async ({ page }) => {
      await openApp(page);
      await navigateTo(page, "Analytics");
      await expect(page.locator(".metric-tile").first()).toBeVisible();

      const complianceTab = page.getByRole("tab", { name: "Compliance" });
      await complianceTab.click();
      await expect(complianceTab).toHaveAttribute("aria-selected", "true");
      await expect(page.locator(".metric-tile").first()).toBeVisible();
    });
  });

  test.describe("admin", () => {
    test.use({ storageState: authFile("admin") });

    test("admin user can open analytics cost and insight views", async ({ page }) => {
      await openApp(page);
      await navigateTo(page, "Analytics");
      await expect(page.locator(".metric-tile").first()).toBeVisible();

      await expect(page.getByRole("tab", { name: "FinOps" })).toBeVisible();
      await expect(page.getByRole("tab", { name: "AI insights" })).toBeVisible();
      await page.getByRole("tab", { name: "FinOps" }).click();
      await expect(page.getByRole("tab", { name: "FinOps" })).toHaveAttribute(
        "aria-selected",
        "true",
      );
    });
  });
});
