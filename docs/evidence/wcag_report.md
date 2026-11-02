# WCAG report

_Generated 2026-10-31T15:17:13Z by `scripts/wcag_report.py`. Inputs: axe scan records, manual checklist and optional sign-off. Nothing here is hand-written evidence._

## Conformance statement

**WCAG 2.2 AA conformance: NOT CLAIMED.** This app is **not AA certified**.

Blocking reasons:

- 28 of 28 checklist rows are not Pass/N/A
- no sign-off file

## Automated axe scans (Chromium, Playwright)

Tags scanned: `wcag2a`, `wcag2aa`, `wcag21a`, `wcag21aa`. axe detects only a subset of WCAG failures and does not cover the 2.2-only criteria (e.g. 2.4.11 focus appearance, 2.5.8 target size) - a clean scan is **not** conformance.

**No axe scan records found** in `/Users/sameer_j/Documents/coding/fde/agent_capstone/apps/web/test-results/axe-scans`. Run the e2e suite against the Compose stack (`scripts/test.sh --e2e`) and re-run this script. No scan results are reported or implied.

## Manual checklist status

| Status | Rows |
|---|---|
| (blank) | 13 |
| Eng only | 15 |

`Eng only` means automated coverage exists; it is **not** a manual pass. Source: `docs/evidence/a11y-manual-checklist.md`.

## Not covered

- Screen-reader and keyboard-only manual passes unless recorded in the checklist.
- Firefox/WebKit (only with `PLAYWRIGHT_CROSS_BROWSER=1`), real mobile devices.
- WCAG 2.2-specific criteria beyond what axe covers, and non-covered routes (scribe, records, grids, admin).

To make a sign-off claim possible: complete the checklist (Pass/N/A with evidence) and add `docs/evidence/wcag-signoff.json` with `tester, date, build, browser, screen_reader`.

