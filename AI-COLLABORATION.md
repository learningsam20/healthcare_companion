# AI Collaboration Log

| Field | Value |
|---|---|
| Purpose | Answer `MC-27`: one honest entry per change set stating what the agent proposed, what was accepted, what was rejected and why |
| Scope | Every change set delivered to this repository, grouped by work package because the build was not committed as one PR per file |
| Rule | An entry is written in the same change as the work. A claim without a verification command or evidence link is not an entry |

This log is not a marketing artefact. It records the places where the agent proposed something that was wrong, unsafe or over-claimed, and what replaced it. Anyone reviewing the build can use it to see which decisions were tested and which remain open.

## Entry format

```
### A-NNN — title (date, work package)
Proposed: what the agent suggested.
Accepted: what shipped.
Rejected: what was discarded and the reason.
Verified: the command or evidence that proves the accepted state.
Open: anything the entry does not close, linked to docs/gaps.md.
```

---

### A-001 — Documentation-first specification (2026-10-24, WP-00)

**Proposed.** Write `spec.md`, `design.md`, `architecture.md`, `plan.md`, `roadmap.md`, `setup.md` and `infra.md` before code, with open questions listed for the product owner.

**Accepted.** All seven documents, with `D-*`/`Q-*` decisions and an explicit "target vs as-built" distinction.

**Rejected.** Treating the endpoint catalogue as delivered. Every catalogue and route map is labelled target until a contract test exists.

**Verified.** Documents cross-checked for requirement IDs; `docs/gaps.md` records the delta.

### A-002 — Records and retrieval vertical slice (2026-10-24, WP-04/WP-09)

**Proposed.** Upload → extract → chunk → embed → answer with citations, using pgvector and a local embedding alias.

**Accepted.** The slice, plus a scope guard in SQL so retrieval cannot return another patient's chunk.

**Rejected.** Client-side filtering of results after retrieval; it would make a cross-patient leak a UI bug rather than an impossible query.

**Verified.** `apps/api/tests/test_privacy_integration.py`, provenance tests in `packages/py-common/tests/test_provenance.py`.

### A-003 — Notifications and scribe (2026-10-25, WP-06/WP-11)

**Proposed.** SMS, email, Slack and in-app notification dispatch, with in-app as the record.

**Accepted.** Provider adapters fail closed to `unconfigured`; in-app is always written; patient Slack requires a verified opt-in and workspace match; no clinical detail in any external message.

**Rejected.** A "demo mode" that pretends to send. It would make a delivery claim that no provider confirmed (`D-21`).

**Verified.** `apps/api/tests/test_notifications.py`; Mailpit delivery evidence.

### A-004 — React application shell (2026-10-25, WP-05)

**Proposed.** Vite/React/TypeScript app with a left menu, dark/light theme, icon buttons with hover text and server-driven grids.

**Accepted.** All of the above, with Keycloak sign-in, no dev bypass, and a server-side grid contract check.

**Rejected.** Browser-side filtering for grids; it would hide pagination bugs and leak full result sets to the client.

**Verified.** `npm run typecheck`, `npm run build`, `scripts/contract_check.py`, Playwright suite.

### A-005 — Containers and identity (2026-10-25, WP-02/WP-15)

**Proposed.** Compose profiles `minimal`/`core`/`full`/`melt`, Keycloak realm import, S3-compatible storage, ports from 5705.

**Accepted.** As proposed, with a realm that seeds demo roles and users through the Keycloak CLI client.

**Rejected.** A development auth bypass flag. It is forbidden by the specification and was never added.

**Verified.** `docker compose config` profile loop in CI, `scripts/smoke.sh`.

### A-006 — Operator scripts, K8s manifests and CI (2026-10-25, WP-15/WP-18)

**Proposed.** Scripts for start/stop/restart, data load, user add, load test, backup/restore, retention, audit and FinOps export; K8s overlays; a CI workflow.

**Accepted.** Scripts and manifests, plus CI for lint, types, import boundaries, tests, contract, locale coverage and secret scanning.

**Rejected.** Committing a `kind` cluster or a CI stack that cannot sign in. The manifests are schema-validated, not claimed as cluster-tested (G-11).

**Verified.** CI jobs in `.github/workflows/ci.yml`; `docs/gaps.md` G-11/G-37 record what is not proven.

### A-007 — PII gate correction (2026-10-26, WP-10)

**Proposed (earlier).** Route external calls when the PII service reports healthy, and treat the regex fallback as sufficient.

**Rejected.** That would have been a safety misrepresentation: the fallback cannot find names, addresses or Hinglish identifiers, and the embedding path sent the original text.

**Accepted.** The gateway requires `engine=composite`, clinical-grade status and zero residual identifiers before an external call; otherwise it falls back locally or blocks. Embeddings now send redacted text and reject a batch whose de-identification changes the piece count.

**Verified.** `apps/api/tests/test_llm_gateway.py`; G-28 remains `Open` until the composite engine exists.

### A-008 — Evaluation harness and browser evidence (2026-10-26, WP-07/WP-14)

**Proposed.** RAGAS and DeepEval runs plus Playwright/axe as release evidence.

**Accepted.** Two 24-case suites, per-language slices, per-case failures retained, judge labelled `unreviewed`; Playwright/axe 20/20.

**Rejected.** Reporting an aggregate score as clinical validation, and hiding failed cases in a mean.

**Verified.** `docs/evidence/eval-ragas-w3-20261025T083908Z.json`, `docs/evidence/eval-deepeval-x01-20261025T095159Z.json`, `docs/evidence/browser-e2e-20261025T095550Z.txt`; G-16/G-26 record the residual.

### A-009 — Consent lifecycle (2026-10-27, WP-03)

**Proposed.** Keep using the Keycloak `patient_id` claim as the caregiver context and seed consents by script.

**Rejected.** A token claim is not a consent record: it cannot be revoked by the patient and leaves no grantor, purpose or revocation time. The product would have claimed a care circle it did not have.

**Accepted.** `consents` gains `grantor_subject`, `purpose`, `granted_at`, `revoked_at`; `/api/v1/consents` supports grant/list/revoke; `/api/v1/me/contexts` activates and clears an explicit caregiver context via `X-Consent-Id`; every patient-linked access records `consent_id`; the care-circle UI shows scope, expiry, status and a context banner.

**Rejected (implementation detail).** Calling a nonexistent `DELETE /me/context` to clear the selection, and auto-selecting the sole consent after a clear. Both would make "Stop using" a no-op. The client now persists a `__none__` sentinel so a deliberate clear survives reload.

**Verified.** `./scripts/test.sh --postgres` (17 tests), `apps/api/tests/test_consents_integration.py`, live caregiver/patient flows in the Compose stack.

**Open.** Consent-history view for compliance; RLS is still G-10.

### A-010 — Patient data rights (2026-10-27, WP-04/WP-10)

**Proposed.** Delete the document row and rely on retention to remove the object.

**Rejected.** Deleting the row alone leaves bytes, chunks, embeddings and citations, which is exactly the failure `FR-W2-13` names.

**Accepted.** `DELETE /api/v1/records/documents/{id}` deletes the S3 object (fail-closed if storage is unavailable), chunks and citation references, then audits counts; `GET /api/v1/me/export` returns metadata with explicit exclusions; `POST /api/v1/me/deletion-request` soft-deletes and the worker purges after the configured grace period, with an audit event per phase.

**Rejected (implementation detail).** An export that included document text or chat content; the export is metadata-only and says so.

**Verified.** Integration tests for delete, cross-patient delete refusal, export and purge; live export produced 25,891 bytes for the demo patient.

**Open.** No orphan scan; the purge is exercised in tests, not on a production schedule.

### A-011 — Document download and accessibility fix (2026-10-27, WP-04/WP-05)

**Proposed.** Return the document bytes through the API.

**Rejected.** Streaming larger files through the API adds memory pressure and a second authorization path; the API issues a short-lived presigned GET instead, signed against the public S3 host.

**Accepted.** `GET /api/v1/records/documents/{id}/download` returns a 300-second URL and audits `records.document_downloaded`; the record detail modal offers "Download original" and shows a storage-unavailable error rather than a broken link.

**Rejected (verification finding).** The notification badge lived inside its anchor, so its visible count conflicted with the accessible name (`label-content-name-mismatch`). The badge moved outside the link and became decorative.

**Verified.** `test_patient_downloads_original_via_presigned_url`; Playwright/axe 20/20 after the badge change.

### A-012 — Migration drift repair (2026-10-27, WP-03)

**Proposed.** Assume databases at revision 0007 already had the `granted_at` default.

**Rejected.** `0007` added the column and set `NOT NULL` without a server default, so a fresh insert without an explicit value failed. Rewriting history alone would not repair an existing database.

**Accepted.** `0007` now adds the column with `server_default=now()`; idempotent `0009_consent_granted_default` repairs databases that already ran the old migration; the integration test asserts head `0009`.

**Verified.** `uv run alembic upgrade head` on an empty database and on the existing pilot database; `test_postgres_integration.py` head assertion.

### A-013 — CI and release gates (2026-10-27, WP-18)

**Proposed.** Add every §8.4 stage at once, including Semgrep, Trivy, Playwright and nightly evals.

**Rejected.** Several stages need services this repository's CI cannot start honestly (a signed-in browser stack, an image registry, a nightly runner). Adding them as green no-ops would be worse than the gap.

**Accepted.** A live Postgres job that migrates an empty database twice and runs integration tests; a blocking production-only `npm audit --audit-level=high`; an advisory `pip-audit` report; this log and the PR template.

**Rejected (dependency audit).** Making `pip-audit` blocking while transitive advisories have no compatible fix (`diskcache`, `ragas`) and others require major upgrades (`langgraph` 1.x, `pypdf` 6.x, `pytest` 9.x). The advisory job records the state; G-37 names the upgrades as the closure condition.

**Verified.** `.github/workflows/ci.yml`; local `npm audit --omit=dev --audit-level=high` reports zero vulnerabilities; `pip-audit` output recorded in G-37.

### A-014 — Canonical discovery/handover pack filing (2026-11-02, WP-01/G6)

**Proposed.** Mark D1–D7 and handover artefacts “done” by pointing at scattered prose in `spec.md` / `architecture.md` without canonical paths.

**Rejected.** That would leave the discovery and handover acceptance lines unmet and over-claim completeness in `deliverables.md`.

**Accepted.** File canonical artefacts: `docs/d1-automation-ladder.md`, `d2-discovery.md`, `d3-assumptions.md`, `d5-sizing.md`, `threat-model.md`, `docs/adr/ADR-*` (tech stack + D6 hosting + ADR-41 change request), `docs/diagrams/`, `evals/report.md` with full §8.3 table, `memo/executive-memo.md`, `memo/demo-recording.md`, D4 compliance sign-off, red-team PDF cases. Keep measured misses as written variances; do not invent capacity or clinical sign-off.

**Verified.** Paths linked from `docs/deliverables.md`, `docs/spec.md` §9.1 and `README.md`.

**Open.** Cost sheet, gates, and `RELEASE.md` filed 2026-11-02. The demo recording is `docs/evidence/demo-recording/sahyog-demo-6min.mp4`.

### A-015 — Close operator leftovers (2026-11-02)

**Proposed.** Leave cost sheet / gates / RELEASE / demo MP4 as “operator later”.

**Rejected.** Those were handover gaps, not optional polish.

**Accepted.** Filed `docs/cost-sheet.md`, `docs/gates/G0–G7`, `RELEASE.md`; captured silent demo MP4 via Playwright against the live stack (`scripts/record-demo.sh`); fixed seed specialty codes `paediatrics`→`pediatrics` and scribe e2e for `scribe-transcript-editor`.

**Verified.** Paths linked from `docs/deliverables.md` and `README.md`; MP4 under `docs/evidence/demo-recording/`.

---

### A-016 — Chaptered product reel with live app footage (2026-11-02)

**Proposed.** Ship a slides-only narrated walkthrough for the six-minute demo.

**Rejected.** Reviewers need the running product on camera, not only title cards.

**Accepted.** Built `docs/evidence/demo-recording/slides.html` + `apps/web/e2e/demo-reel.spec.ts` as **continuous workflow takes** (brief slicer then live shell navigation in one recording per epic, per `docs/demo.md` §8.2). Narration is mixed over the live footage — not finished on the title card before the UI appears. Architecture + tech-stack slides retained. Long scribe waits condensed head+tail for a ~6–7 minute reel.

**Verified.** `sahyog-demo-6min.mp4` is about 7 minutes, with continuous E1–E6 footage.

---

## Change-set checklist

Before an entry is added, the change must satisfy:

- [ ] Acceptance criteria named and tested (or a named manual check).
- [ ] Authorization failure and validation failure covered, not only the happy path.
- [ ] No PHI, secret or patient identifier in logs, traces, analytics, exports or audit metadata.
- [ ] No direct provider SDK or tool call that bypasses LiteLLM/MCP.
- [ ] No safety flag or consent check weakened; a new flag is registered with owner, environments and expiry.
- [ ] Migration is forward-only and re-runnable; a new route or page has contract coverage.
- [ ] The honest status is recorded in `docs/gaps.md` if anything remains open.
