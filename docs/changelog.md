# Build Change Log

| Field | Value |
|---|---|
| Product | Sahyog Care Companion |
| Document | `docs/changelog.md` — what changed during delivery, why, and where it differs from the original plan |
| Version | 1.0 |
| Date | 2026-10-27 |
| Related | [gaps.md](./gaps.md) · [plan.md](./plan.md) · [architecture.md](./architecture.md) · [design.md](./design.md) · [setup.md](./setup.md) · [AI-COLLABORATION.md](../AI-COLLABORATION.md) |

This log records changes made **after** the documents in §2 of [plan.md](./plan.md) were baselined. It is deliberately not a commit list: the repository was delivered without a git history, so work is grouped by date and work package, and every entry names the reason for the change. Where a change narrows a claim rather than adds a feature, it is recorded as a correction, because an over-claim is a defect in this product.

## 1. Summary

| Date | Theme | Result |
|---|---|---|
| 2026-11-01 | Wave F residuals | Auto-title + SLA handoff paging + guardrail persistence + HA soak harness; OPA explicitly not required (gaps v1.14) |
| 2026-11-01 | S3Proxy replaces MinIO | Local object store is `andrewgaul/s3proxy` filesystem + **aws-v4** (`S3_ACCESS_KEY`/`S3_SECRET_KEY`); MinIO images removed |
| 2026-11-01 | Host-app local run | `start.sh --local` / `dev.sh`: API+UI+agents+ARQ on host, deps in Docker; setup/README updated |
| 2026-10-24 | Specification before code | Seven documents, decision register and open questions |
| 2026-10-25 | Implementation baseline | Records/RAG, scheduling, scribe, notifications, analytics/FinOps, React app, Compose/K8s, scripts and CI |
| 2026-10-25 | Gap-closure pass | Malware scanning, agent tracing, browser E2E, scheduled analytics, reconciliation, evaluation suites |
| 2026-10-27 | Requirement review | New rows G-33–G-38 for consent, data rights, data estate, accessibility, CI and API delta |
| 2026-10-27 | Closure pass | G-33 and G-34 closed; G-38 and G-37 mitigated; document download; migration repair; accessibility fix |

## 2. Beyond the original plan

These are additions or changes that were not in the first baseline. Each has a stated reason; none replaces a required capability.

| Change | Why it was made | Where it lives |
|---|---|---|
| **Keycloak CLI client** (`KEYCLOAK_CLI_CLIENT_ID`/`SECRET`) for seeding and smoke tests | The demo needs reproducible role-accurate tokens without a development auth bypass, which the specification forbids | `docker/keycloak/`, `scripts/seed-users.sh`, `scripts/ops_client.py` |
| **gitleaks and a custom `.gitleaks.toml`** | A `.env` pilot is only acceptable if secrets cannot be committed; the scan is a gate, not advice | `.github/workflows/ci.yml`, `.gitleaks.toml` |
| **ClamAV malware scanning with `MALWARE_SCAN_MODE=required`** | Upload is untrusted input; a clean-upload demo without a scanner would be a false security claim (G-32) | `docker/`, `apps/api/app/core/malware.py`, `docs/evidence/malware-scan-20261025.json` |
| **Langfuse trace exporter with content capture off** | Per-request agent observability was a requirement, but patient content must not enter traces (G-23) | `packages/py-common/sahyog_common/tracing.py`, `docs/evidence/langfuse-trace-*.json` |
| **Load-test real-user abort guard** | Synthetic load must coexist with real users; the guard is the control even though the abort path is not yet exercised (G-17/G-22) | `scripts/load_test.py`, `apps/api/tests/test_load_guard.py` |
| **LiteLLM spend reconciliation importer** | FinOps needs gateway-vs-application comparison; unmatched calls are a finding, not an error to hide (G-31) | `apps/api/app/modules/analytics/`, `docs/evidence/finops-reconciliation-*.json` |
| **Scheduled analytics jobs on separated ARQ queues** | The worker was claiming scheduler functions; separate `sahyog:worker` and `sahyog:scheduler` queues make job ownership explicit (G-30) | `apps/api/app/worker.py`, `docs/evidence/analytics-jobs-20261025.json` |
| **RAGAS and DeepEval suites with per-case failures** | A single aggregate hides the weakest language slice; the harness keeps per-language and per-case results and labels the judge `unreviewed` (G-16) | `evals/`, `docs/evidence/eval-*.json` |
| **Playwright/axe suite incl. dark theme and 360 px** | Server tests cannot catch a broken sign-in redirect or an inaccessible icon button (G-26/G-36) | `apps/web/e2e/`, `docs/evidence/browser-e2e-*.txt` |
| **Consent lifecycle, patient data rights, document download** | The requirement review found these were enforced or catalogued but not delivered; G-33/G-34 were safety/legal rows | see §3 |
| **Live Postgres CI job and dependency audits** | The CI proved lint and unit behaviour but not the migration chain or dependency state (G-37) | `.github/workflows/ci.yml` |
| **`AI-COLLABORATION.md` and PR template** | `MC-27` requires an honest record of agent proposals and rejections, including rejected unsafe suggestions | repository root, `.github/pull_request_template.md` |

## 3. 2026-10-27 closure pass

### 3.1 Consent lifecycle (G-33 → Closed)

- Migration `0007_consent_lifecycle` adds `grantor_subject`, `purpose`, `granted_at` and `revoked_at`; `0009_consent_granted_default` repairs the `granted_at` server default for databases that already ran the earlier migration.
- `/api/v1/consents` provides a server-paginated grid, grant and revoke; `/api/v1/me/contexts` lists, activates and clears a caregiver context; the caregiver's choice travels as `X-Consent-Id` and the server resolves the patient from the active consent.
- `audit_events.consent_id` links each patient-linked access to the consent that authorized it; grant, activation, revocation and expiry each write an audit event.
- `/care-circle` lets a patient grant by caregiver subject with scope and expiry, see status, revoke, and switch context; a deliberate "stop using" persists instead of being auto-reselected.
- **Why:** a consent that only an operator can grant or revoke is not patient-controlled, and a token claim is not a consent record.

### 3.2 Patient data rights (G-34 → Closed)

- Document deletion removes the S3 object, chunks and citation references, and writes one audit event with counts; a storage outage returns `503` and leaves the record intact rather than orphaning metadata.
- `GET /api/v1/me/export` returns metadata only and names its exclusions; `POST`/`DELETE /api/v1/me/deletion-request` soft-delete and cancel; the worker purges after the grace period with a second audit event.
- `GET /api/v1/records/documents/{id}/download` issues a 300-second presigned GET and audits the download.
- The records detail modal and the care-circle page expose download, delete, export and deletion request to the roles allowed to use them.
- **Why:** an accidental upload that a patient cannot correct, or a data-subject request that only an operator can satisfy, is a product and DPDP failure.

### 3.3 API delta (G-38 → Mitigated)

- The as-built surface is 76 paths. Consent/context, export/deletion and download/delete are now implemented and tested.
- The remaining absent families are named explicitly in G-38 rather than implied; the catalogue stays labelled target.
- The contract check now validates the consent grid as a fifth server-grid path.

### 3.4 CI and release evidence (G-37 → Mitigated)

- A live Postgres job migrates an empty database from `0001` to `0009`, repeats the upgrade to prove idempotence and runs the 17 integration tests. The same sequence was executed locally against a fresh `sahyog_ci` database.
- `npm audit --omit=dev --audit-level=high` blocks the web job; the project reports zero production vulnerabilities.
- `pip-audit` runs as an advisory report. It is not blocking because several transitive advisories need major upgrades; the list is recorded in G-37.
- `AI-COLLABORATION.md` and `.github/pull_request_template.md` are part of the change.

### 3.5 Defects found and fixed during verification

| Defect | Cause | Fix |
|---|---|---|
| Fresh consent insert failed on `granted_at` | `0007` added the column and set `NOT NULL` without a server default | Add `server_default=now()` in `0007`; idempotent `0009` repair for existing databases |
| "Stop using" in the care-circle banner did nothing | The client called a nonexistent `DELETE /me/context` and an auto-select effect re-selected the only consent | Persist a `__none__` sentinel, derive the active context from it, and remove the bogus request |
| Axe `label-content-name-mismatch` on the notification bell | The unread count lived inside the anchor's accessible name | Move the badge outside the link, make it decorative, keep the count in `aria-label` |
| Purge test failed after cascade delete | The SQLAlchemy identity map still held the deleted row | Expunge the session before asserting absence; the database behaviour was correct |
| Records download missing from the deployed API | The image predated the route | Rebuild and redeploy; the live OpenAPI now lists 76 paths including the download |

## 4. Corrections to claims

These are changes to what the project says, not to what it does. They are listed separately because an overstated claim is itself a gap.

| Earlier claim | Corrected position | Reason |
|---|---|---|
| Endpoint catalogue read as delivered | Catalogue is a target; as-built surface is generated/checked separately | Coverage and path names differ (G-38) |
| "Composite PII detection" | Regex fallback only; external egress is fail-closed and cannot pass the gate | The composite engine is absent (G-28) |
| "External models via OpenRouter" as an active path | Egress is disabled by default and blocked until the composite gate exists | Safety constraint, not a config default |
| Load result described as capacity evidence | The committed run is a 29-request smoke at burst 1 on `r1` | It does not prove R3 capacity (G-17) |
| Kubernetes "deployed" | Manifests render and schema-validate; no cluster run in this build | G-11 |
| Judge scores as quality evidence | Scores are answer-quality signals from synthetic fixtures with an unreviewed judge | G-16 |
| Consent self-service implied by seeded rows | Seeded rows are demo data; the lifecycle is now real, but no consent-history view exists | G-33 residual |

## 5. Planned work not delivered

The authoritative list is [gaps.md](./gaps.md). The material items are:

- Read-only FHIR adapter (G-08) and ABDM (G-09).
- X-01 nursing summary (G-13) and external MCP (G-14).
- mem0 preference memory (G-24).
- Composite PII/Privacy Filter/Presidio/GLiNER (G-28).
- OpenDecider and local Whisper models (G-29).
- Prometheus rules, Alertmanager and recorded drills (G-25).
- Public-source data estate and signed G2 variance (G-35).
- Manual WCAG 2.2 AA and cross-browser conformance (G-36).
- The remaining CI stages and the clean-machine release record (G-37).
- The remaining API/UI families (G-38).

## 6. How to verify this log

```bash
./scripts/test.sh                     # unit suite
./scripts/test.sh --postgres          # 17 integration tests against the running stack
./scripts/test.sh --contracts --i18n  # 76 paths, five grid paths, locale coverage
./scripts/test.sh --e2e               # Playwright/axe against the running stack
docker compose build api && docker compose up -d api
curl -s http://localhost:5706/openapi.json | python3 -c "import json,sys; print(len(json.load(sys.stdin)['paths']))"
```

A change that alters behaviour should update this file, `docs/gaps.md` and `AI-COLLABORATION.md` in the same change.
