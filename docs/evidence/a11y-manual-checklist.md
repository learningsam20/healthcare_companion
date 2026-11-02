# WCAG 2.2 AA manual QA checklist

This is a manual test worksheet, not a WCAG conformance statement or
certification. Leave **Status** blank until QA records `Pass`, `Fail`, or `N/A`
with evidence. Test at 100% and 200% zoom, with keyboard only, and with at least
one supported screen reader/browser combination.

**Engineering progress (not AA claim):** skip-link → `#main-content`, Modal focus
trap + restore focus, chat `aria-live`, Chromium axe suite, optional
`PLAYWRIGHT_CROSS_BROWSER=1`. Status `Eng only` means automated coverage exists;
QA must still record Pass/Fail before any AA statement.

| Area | Check | WCAG 2.2 AA focus | Status | Evidence / notes |
|---|---|---|---|---|
| Sign-in | Complete sign-in, validation, recovery, and sign-out with keyboard only; no trap | 2.1.1, 2.1.2 | Eng only | Playwright Keycloak flow; manual SR still required |
| Sign-in | Focus order is logical and focus remains visible, including errors and redirects | 2.4.3, 2.4.7, 2.4.11 |  |  |
| Sign-in | Inputs, buttons, errors, and status messages have accurate screen-reader names/announcements | 1.3.1, 3.3.1, 4.1.2, 4.1.3 | Eng only | axe names on covered routes |
| Sign-in | Text, controls, focus indicators, and error states meet contrast requirements | 1.4.3, 1.4.11 | Eng only | axe contrast (Chromium) |
| Chat | Reach history, composer, send controls, citations, and new messages by keyboard | 2.1.1, 2.4.3 | Eng only | Playwright chat |
| Chat | Focus is visible and is not unexpectedly moved when messages arrive | 2.4.7, 3.2.1 |  |  |
| Chat | Conversations, controls, sources, busy state, and message updates have meaningful names/announcements | 1.3.1, 4.1.2, 4.1.3 | Eng only | `aria-live` + axe |
| Chat | Message text, links, controls, and status indicators meet contrast requirements | 1.4.3, 1.4.11 | Eng only | axe |
| Booking | Select patient/clinic/doctor/date/slot and submit or cancel using keyboard only | 2.1.1, 2.1.2 | Eng only | Playwright booking |
| Booking | Dialog and validation focus is visible, ordered, and restored to the trigger on close | 2.4.3, 2.4.7 | Eng only | Modal focus trap |
| Booking | Required fields, formats, errors, slot state, and confirmation are named and announced | 3.3.1, 3.3.2, 4.1.2, 4.1.3 |  |  |
| Booking | Calendar/slot states, text, controls, and focus indicators meet contrast requirements | 1.4.3, 1.4.11 | Eng only | axe |
| Records | Navigate filters, document list, upload/view/download actions, and dialogs by keyboard | 2.1.1, 2.4.3 |  |  |
| Records | Focus is visible and remains predictable after filtering, upload, and dialog close | 2.4.7, 3.2.2 | Eng only | Modal restore |
| Records | Documents, metadata, actions, progress, errors, and success messages have clear names/announcements | 1.3.1, 4.1.2, 4.1.3 |  |  |
| Records | Text, file/status indicators, controls, and focus indicators meet contrast requirements | 1.4.3, 1.4.11 | Eng only | axe |
| Scribe | Operate recording, pause/stop, transcript editing, review, and save by keyboard | 2.1.1, 2.1.2 | Eng only | Playwright scribe |
| Scribe | Focus is visible and does not jump during recording/transcription updates | 2.4.3, 2.4.7 |  |  |
| Scribe | Recording state, elapsed/progress state, transcript regions, warnings, and controls are announced | 1.3.1, 4.1.2, 4.1.3 |  |  |
| Scribe | Waveform/status information is not color-only and all foreground/focus contrast passes | 1.4.1, 1.4.3, 1.4.11 | Eng only | axe (partial) |
| Grids | Reach headers, rows, pagination, sorting, filtering, and row actions using keyboard only | 2.1.1, 2.4.3 |  |  |
| Grids | Focus is visible and retained after sort, filter, pagination, and row updates | 2.4.7, 3.2.2 |  |  |
| Grids | Header associations, sort state, row labels, selection, empty/loading state, and counts are announced | 1.3.1, 4.1.2, 4.1.3 |  |  |
| Grids | Text, selected/hover/error states, controls, and focus indicators meet contrast requirements | 1.4.3, 1.4.11 | Eng only | axe where covered |
| Settings | Navigate language, theme, preferences, save/reset, and confirmation controls by keyboard | 2.1.1, 2.4.3 |  |  |
| Settings | Focus is visible and remains on the relevant control after save, reset, or error | 2.4.7, 3.2.2 |  |  |
| Settings | Groups, current values, help, validation, and save status have accurate names/announcements | 1.3.1, 3.3.2, 4.1.2, 4.1.3 |  |  |
| Settings | Light/dark themes, controls, disabled states, and focus indicators meet contrast requirements | 1.4.3, 1.4.11 | Eng only | dark theme Playwright + axe |

Record browser, OS, screen reader/version, viewport, build/commit, tester, and
date with the completed evidence. Automated checks may supplement but do not
replace this checklist.
