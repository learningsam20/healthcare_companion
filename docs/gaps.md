# Care Companion — Known Gaps and Mitigations

| Field | Value |
|---|---|
| Product | Sahyog Care Companion |
| Document | `docs/gaps.md` — known capability gaps, residual risk, interim controls and closure plans |
| Version | 1.16 — 2026-11-01 pilot ship pass (email/Slack, vault, residual closes) |
| Date | 2026-11-01 |
| Status | Living register. A gap is not an excuse: it has an owner, an interim control, a closure trigger and a visible UI/ops state. Closing a gap requires evidence linked from this document. |
| Owner | engineering lead; each gap has a named functional owner |
| Related documents | [spec.md](./spec.md) · [design.md](./design.md) · [architecture.md](./architecture.md) · [plan.md](./plan.md) · [setup.md](./setup.md) · [roadmap.md](./roadmap.md) · [infra.md](./infra.md) |
| Why this exists | The product-owner decision `D-10`/`Q-14` requires English, Hindi and Marathi and mixed-language input from R1, with any remaining gaps documented with potential solutions. `C-06` in [plan.md](./plan.md) extends the same honesty rule to every capability. |

> **2026-11-01 pilot ship pass (v1.16).** Email + Slack staff delivery proven ([notify-channels-probe-20261101T064929Z.json](./evidence/notify-channels-probe-20261101T064929Z.json)); `staff_handoff` includes email; staff Slack contacts use allowlisted channels; `NOTIFY_OPS_SUBJECT` wired; `SECRETS_BACKEND=env|file|vault`; MTTA documented ([mtta-and-paging.md](./runbooks/mtta-and-paging.md)); short caveat list ([ship-caveats.md](./evidence/ship-caveats.md)). SMS optional. **Do not** claim medical-device clearance, clinical i18n sign-off, egress-on, or production MTTA.

> **2026-11-01 UX polish (v1.15).** Chat doctor/slot cards + choice/hold countdowns; soft-hold then `POST /appointments/{id}/confirm`; grounded-ask SSE via `W2AskGraph.stream`; denser `/front-desk` live handoffs + assistant bookings; en/hi/mr strings.

> **2026-11-01 Wave F (v1.14).** Titles on sync+stream with `title_source` + one system refine; sidebar Today/Yesterday grouping; handoff `sla_due_at` (2 min) + staff_handoff notify + `handoff_sla_job` + `SahyogHandoffOverdue`; message `safety` JSON for red-flag reload; stream audit parity; appointment-help ordinal/name (no UUID required); document indexed notify + in-thread system notice; `scripts/chat-interrupt-ha-soak.sh`. **OPA not required for R1** (Keycloak RBAC + consent + repo predicates + MCP allowlists + PII gate). Residual: real on-call MTTA (G-25), soak evidence in target HA env (ask-path drip closed in v1.15).

> **2026-11-01 Wave E (v1.13).** **G-46–G-48 Mitigated in-repo:** W1 uses LangGraph `interrupt()` + checkpointer resume with stable `thread_id` (`w1:{run_id}`) and chat_runs registry; `POST .../messages/stream` SSE token stream after intent/safety (conversation intents); staff `/escalations` + `/front-desk` + appointment `source` assistant|front_desk. Residual narrowed in v1.14 (SLA + soak script).

> **2026-11-01 spec honesty pass (v1.12) + implementation wave.** Spec/design vs as-built audit registered **G-39–G-50**. Implementation wave mitigated in-repo: G-39–G-45, G-49, G-50 (assistant `slot_choice` + MCP hold/confirm + notify + idempotency migration, specialty clarify, red-flag handoff ticket, `appointment_help` graph, Ollama memory cap script, chat→Records attach). **v1.13** mitigated G-46–G-48 (see above). **G-26** Closed claim narrowed: Playwright proves front-desk Appointments booking + chat provenance; chat slot e2e case added but evidence run not yet attached. Do not treat MCP allowlists or design tables as delivery proof.

> **2026-10-31 residual implementation pass (v1.11).** In-repo residuals shipped without false Closes: **G-08** FHIR SPA (`/patients/:id/fhir`); **G-03** live recall@k ([recall-at-k-live-20261031T174820Z.json](./evidence/recall-at-k-live-20261031T174820Z.json)); **G-24** Mem0 API put/purge e2e ([mem0-forget-e2e-20261031T180949Z.json](./evidence/mem0-forget-e2e-20261031T180949Z.json)); **G-13** nursing live draft probe; **G-25** Mailpit demo email paging; **G-30** age-encrypted backup ([encrypted-backup-20261031T174501Z.json](./evidence/encrypted-backup-20261031T174501Z.json)) + job metrics; **G-31** `SahyogFinopsVariance` alert; HA graph `thread_id` fix; smoke 21/22 (provenance sources on red-flag path still 0). User-facing “what is not implemented”: [README.md](../README.md). External blockers: [external-closure-blockers.md](./evidence/external-closure-blockers.md).

> **2026-10-31 in-repo residual pass (v1.10).** At the time: no Open rows among then-registered IDs (30 Mitigated / 7 Closed / 1 Deferred). **That completeness claim is superseded by v1.12** for unregistered W1/chat verticals. **G-05** → **Mitigated**: live EN LibriSpeech WER mean 0.0 ([stt-wer-score-aggregate-20261031T170248Z.json](./evidence/stt-wer-score-aggregate-20261031T170248Z.json)); residual hi/mr + OCR. **G-22** live `LOAD_TEST_KILL` drill [load_test_kill_drill_20261031T170411Z.json](./evidence/load_test_kill_drill_20261031T170411Z.json). **G-25** Alertmanager drills recorded (`133523Z`, `170000Z`, `170003Z`, `174825Z`); residual real paging. **G-30** `/metrics` + `SahyogJobStale`/`SahyogJobFailures` scraped ([g30-job-alerts-20261031T170745Z.json](./evidence/g30-job-alerts-20261031T170745Z.json)); residual encrypted backup (closed in v1.11). External blockers refreshed in [external-closure-blockers.md](./evidence/external-closure-blockers.md). Do not false-close owner-gated rows.

> **2026-10-31 G-35 inventory Closed.** Kaggle download of all five public sources + measured inventory [public-source-inventory-20261031T165720Z.json](./evidence/public-source-inventory-20261031T165720Z.json) (`status=passed`). Residual: human licence review for four `check_and_record` sources.

> **2026-10-31 multi-gap plan land (v1.9).** In-repo controls from the multi-gap closure plan shipped without false Closes. **G-12** attestation gate (upload+checkbox → MinIO + `compliance_attestations`; `/meta` `clinically_validated`; [clinical-validation-status.json](./evidence/clinical-validation-status.json)) — still **Mitigated** (not regulatory clearance). **G-19** DPDP register + stop-processing middleware + [dpdp-audit-report.md](./evidence/dpdp-audit-report.md) — still **Mitigated** (no signed DPA). **G-28** Governance PII health + egress fail-closed validation before admin toggle — still **Mitigated**. **G-05** STT contract fix + non-PHI TTS fixture — still **Open** (no measured WER). **G-35** Closed via inventory (see v1.9.1 note above). **G-17** `load_test_report.md` writer; **G-22** `LOAD_TEST_KILL` drill hook; **G-36** `wcag_report.py` — stay Mitigated. WP-C/F: Slack coverage tile, memory purge/retention job, nursing live harness, MCP quotas/CI, catalogue diff — stay Mitigated. Do not claim Closed for G-05/G-09/G-12/G-15/G-16/G-17/G-36.

> **2026-10-31 composite PII prove (v1.8).** G-28 composite runtime **proven**: image `sahyog-api:local` (CPU torch 2.5.1 + `en_core_web_sm` + GLiNER), `mcp-pii` recreated; [mcp-pii-detect-probe.json](./evidence/mcp-pii-detect-probe.json) shows `engine=composite`, `not_clinical_grade=false`, count=3 (person/email/phone); write-up [pii-composite-prove-20261031.md](./evidence/pii-composite-prove-20261031.md). G-28 stays **Mitigated** (closure still requires security sign-off before egress; `EXTERNAL_EGRESS` remains false). G-19 interim control updated: composite PII gate proven (no longer regex_fallback-only); still **Mitigated** for DPA/subprocessor review. Prior residual-honesty residuals unchanged (G-07/14/22/25/13/24/30/27/38 Mitigated; G-05/G-35 Open). Do not false-close G-05/G-09/G-12/G-15/G-16/G-17/G-35/G-36. External blockers: [external-closure-blockers.md](./evidence/external-closure-blockers.md) (G-28 not an external blocker; egress security sign-off under G-19).

> **2026-10-31 residual-honesty pass (v1.7).** In-repo residual controls verified and reflected; no false Closes. Status unchanged for listed residuals (all remain **Mitigated** unless noted): G-07 contact re-verification job + scan/`--database` + unit tests (closure still 100% verified opted-in coverage); G-14 signed-context conformance suite (partner productisation open); G-22 `decide_guard_abort` unit proof (live shared-env abort open); G-25 Alertmanager drill port 5736 + `/-/ready` (no HTTP 200 drill JSON); G-13 nursing set + shape runner (clinical-graded live drafts open); G-24 memory preferences + purge unit tests (live Mem0 e2e open); G-30 backup/stock stubs + runbook (encrypted backup success / job-failure alerting open); G-27 digests + supply-chain advisory status; G-38 OpenAPI 138/157 + §7.5 SoT aligned but leftovers still need explicit out-of-scope mark → stay Mitigated. G-05 Open (no WER). G-35 Open (no Kaggle creds). G-28/G-19 left as-is (rebuild elsewhere). External blockers: [external-closure-blockers.md](./evidence/external-closure-blockers.md).

> **2026-10-27 requirement review.** The register was re-audited against spec §5–§8 and the as-built OpenAPI surface. Rows G-33–G-38 record findings that were previously implicit rather than recorded: consent lifecycle, patient data rights, the public data estate, accessibility/browser conformance, CI/release evidence and the difference between the catalogued and as-built API. No previously open gap was closed by this review.

> **2026-10-27 closure pass.** The gaps identified by that review were then worked in severity order. G-33 (consent lifecycle) and G-34 (patient data rights) are **Closed** with implementation and tests linked below. G-38 moved to `Mitigated`: document download and the consent/context families are implemented, and the remaining families are explicitly re-scoped rather than implied. G-37 moved to `Mitigated`: CI now migrates and tests a disposable Postgres database, audits production npm dependencies, reports Python advisories, and the repository carries `AI-COLLABORATION.md` and a PR template. G-25 is unchanged (`Mitigated`): alerts still have no rules, routing or recorded drill. Nothing else changed status in this pass; rows not named here remain at their recorded status.

> **2026-10-31 deferred-track scaffolding.** Code-complete readiness for previously deferred/open tracks without false claims: G-09 ABDM sandbox seam (`patient_external_ids`, `/api/v1/abdm/*`, `certified:false`); G-11 HA overlay + checkpointer-required readiness + `scripts/k8s-ha-smoke.sh` (app multi-replica only); G-36 skip-link + manual WCAG checklist + optional Firefox/WebKit Playwright; G-17 `--host-profile` / `scripts/load_test_ml.sh` (capacity not accepted on P/S); G-16 `scripts/calibrate-judge.sh` + provisional calibration README (still pending human attestation); cloud STT OpenAI-compatible adapter behind `ALLOW_CLOUD_STT`/`STT_ADAPTER=cloud` with fail-closed startup and mcp-stt tests. Certification, multi-region HA, AA sign-off, M/L measured evidence and human judge grades remain closure triggers.
>
> **2026-10-31 follow-through.** Official-path ABDM stub (`services/abdm-stub`, equality matrix `docs/abdm-stub-equality.md`) + hospital seam; Compose HA via `docker-compose.ha.yml` + nginx `api-lb` + `CHECKPOINTER_REQUIRED`; egress refuses startup without composite PII; LLM judge label producer + κ≥0.6 / attested human gate for `status=calibrated`; Modal focus-trap WCAG practice; X-01 accept/edit/reject versioning; Prometheus `alerts.yml`; red-team corpus + recall@k harness. Load-test scripts exist (`load_test_smoke.sh` / `load_test_ml.sh`); committed evidence remains r1 smoke on P (G-17). National ABDM cert, signed AA, and human-attested reviewer file remain external.
>
> **2026-10-31 close-all pass (v1.6).** In-repo controls pushed to maximum. External blockers listed in [external-closure-blockers.md](./evidence/external-closure-blockers.md) stay Mitigated/Deferred/Open — not falsely Closed. Actual-data policy unchanged (seed/sample only offline synthetic path). G-28 rebuild uses CPU torch install (no CUDA nvidia wheels). Decider prefers host Ollama OpenDecider; Strands optional.
>
> Feature YAML defaults remain `false` for `abdm_link`, `memory_preferences`, `x01_nursing_summary`, `external_mcp`; enable via `FEATURE_*` / `.env` and recreate API.

## 1. Rules of this register

1. **A gap is a known limitation, not a silent omission.** If the product cannot do something the requirements imply, it is here with its consequence.
2. **Safety gaps cannot be accepted by silence.** A gap affecting red flags, consent, scope, PII egress, signature or emergency copy is a release blocker unless the clinical/security owner signs a written variance with an expiry.
3. **Every gap has an interim control.** "Not implemented" is not a control. The control is what the product does instead: a visible fallback, a disabled action, a human hand-off, a restricted scope or a documented manual step.
4. **Every gap has a closure trigger.** A date, a gate, a piece of evidence or a client decision. A gap with no trigger is scope debt.
5. **The UI and operations must tell the truth.** An `unconfigured` integration, a stale analytics tile or an absent capability is visible; it never renders as success or as zero. A missing translation falls back to English and is recorded in G-01, not presented as a complete locale.
6. **Closing evidence lives outside this file.** Link the eval report, test, screenshot, runbook or signed decision. Editing this table is not evidence.

### 1.1 Severity

| Severity | Meaning | Release rule |
|---|---|---|
| **S1 — Safety/legal** | Could cause harm, a privacy breach, an unauthorised clinical act or a false compliance claim | Blocks the affected workflow and gate until closed or a written variance is approved |
| **S2 — Material** | A core persona cannot complete a promised task, or a claim is weaker than stated | Must have an accepted interim control and a dated closure plan |
| **S3 — Minor** | Reduced quality, coverage or convenience; no safety or legal impact | Track, schedule, and disclose in known limitations |

### 1.2 Status

`Open` · `Mitigated` (control in place, gap remains) · `Closed` (evidence linked) · `Deferred` (approved post-handover; roadmap item named) · `Not a gap` (intentional non-scope, documented).

## 2. Gap register

| ID | Area | Gap | Sev. | Interim control | Closure / target | Owner | Status |
|---|---|---|---|---|---|---|---|
| G-01 | i18n UI | A reviewed Hindi/Marathi translation may lag newly added non-safety strings; key coverage is CI-gated but translation quality is not | S3 | English fallback; `i18n_check.py` + [i18n-safety-key-audit.json](./evidence/i18n-safety-key-audit.json); sign-off file [i18n-clinical-signoff.json](./evidence/i18n-clinical-signoff.json); status appears in [clinical-i18n-report.md](./evidence/clinical-i18n-report.md) and eval reports via `eval_report.py` | Clinical reviewer sets `review_status=approved` in sign-off JSON; re-run audit so reports show approver + `signed_at` | Design + clinical reviewer | Mitigated |
| G-02 | Clinical language | Machine-translated clinical text is not clinically validated; translated output can change nuance | S1 if used clinically | Never presented as validated clinical advice; same sign-off SoT as G-01 — **visible when approved** in clinical + eval reports; currently `unreviewed` | Human clinical review of hi/mr safety catalogue recorded in sign-off JSON (approver name + timestamp) | Clinical reviewer | Mitigated |
| G-03 | Retrieval | Mixed-script recall still unproven in production evidence | S2 | Hybrid search + query expand; live `--live` recall@k ([recall-at-k-live-20261031T174820Z.json](./evidence/recall-at-k-live-20261031T174820Z.json), mean term-recall 0.17); citation-first refusal on weak evidence | Improve live term-recall / seed mixed-script docs; no safety regression | E1 + analytics | Mitigated |
| G-04 | Model quality | 7–8B local models may be weaker in Marathi/Hinglish than English; external models may vary by language | S2 | Purpose routing + `language_routing`; [language-eval-slice.json](./evidence/language-eval-slice.json) aggregates **actual** RAGAS/DeepEval run scores by language | Re-measure after alias/model change; keep residual quality note | E1/E4 | Mitigated |
| G-05 | STT/OCR | Code-mixed Hindi/Marathi/English speech and Devanagari OCR can have higher word-error/character-error rates | S2 | Whisper on disk; live EN LibriSpeech WER `mean=0.0` ([stt-wer-score-aggregate-20261031T170248Z.json](./evidence/stt-wer-score-aggregate-20261031T170248Z.json)); [g05-stt-wer-status.md](./evidence/g05-stt-wer-status.md); `wer_cer.py` refuses `synthetic:true` | Measure hi/mr + clinical speech WER and Devanagari OCR CER; keep doctor-edit before sign | E4 | Mitigated |
| G-06 | Notifications | Email + Slack staff delivery proven for pilot; SMS remains optional/off by default | S2 | [notify-channels-probe-20261101T064929Z.json](./evidence/notify-channels-probe-20261101T064929Z.json) direct+queued `sent`; staff Slack uses allowlisted channel; `staff_handoff` → in-app+email+slack_staff; SMS feature default false | SMS DLT/provider when client enables `notifications_sms` | E4 + client ops | Closed |
| G-07 | Patient Slack | A patient may opt in without a verified Slack ID, or the ID may become stale | S2 | Delivery suppressed until verified/opt-in/workspace match; ARQ `contact_reverification_job` + `scripts/contact_reverification_scan.py` (180d, job_runs/audit); `GET /api/v1/notifications/slack-coverage` + admin Settings tile (empty population = no evidence); daily job raises `ops_alert` when opted-in coverage <100%; patient self-registration `POST /api/v1/me/contacts` (unverified until coded) | 100% verified coverage for opted-in patients (ops evidence) | E4 | Mitigated |
| G-08 | FHIR | Read-only FHIR R4 adapter + clinician SPA panel; no write-back, no appointment/note write, no ABDM linking | S2 | API + crosswalk; SPA `/patients/:id/fhir` demographics/encounters (honest empty states for missing link / unconfigured); `/meta` status; writes never called | HIS-specific mapping; write-back/ABDM remain post-handover | E4 + client | Mitigated |
| G-09 | ABDM | National ABDM certification is not delivered; local official-path stub + hospital seam exist | S2 | `services/abdm-stub` + `docs/abdm-stub-equality.md`; `/api/v1/abdm/*` and `/meta` `adapters.abdm_sandbox` always `certified:false` (unit-tested for every config; Settings shows "Not certified"); YAML default off (enable via `FEATURE_ABDM_LINK`); HTC sandbox still human | NHA sandbox credentials + certification programme; replace stub with certified connector | Product owner | Mitigated |
| G-10 | Access control | RLS / field encryption / break-glass absent; live IDOR probe incomplete | S1 if predicate bug | Repository predicates + cross-patient tests; [red-team-offline.json](./evidence/red-team-offline.json) shape pass; `red_team_runner.py --live` when token set | Live refusal evidence + security review; RLS/column encryption post-pilot | E2 + security | Mitigated |
| G-11 | Availability | Multi-region/automatic failover not delivered; app-tier HA overlay + checkpointer readiness exist | S2 | `overlays/ha`, `HA_MODE`/`CHECKPOINTER_REQUIRED` readiness, Postgres checkpointer, `scripts/k8s-ha-smoke.sh`; data plane still single Postgres/Redis/MinIO; no DR drill | Cluster smoke + restore drill + RPO/RTO record before production HA claim | E2 | Mitigated |
| G-12 | Clinical validation | The product is a demonstration, not a validated medical device; no clinical trial or regulatory clearance | S1 if misrepresented | Attestation gate (Admin Governance): report upload + named approver checkbox → `not_attested`/`attested`/`revoked`; `/meta` `clinically_validated`; [clinical-validation-status.json](./evidence/clinical-validation-status.json); disclaimer; HITL; no diagnosis/dose | Product owner accepts gate **or** commissions regulatory plan; never auto-claim device clearance | Product + clinical | Mitigated |
| G-13 | X-01 summary | Nursing draft + accept/edit/reject versioning exist; clinical quality eval incomplete | S2 | Flag on in pilot; API + UI; live draft probe [nursing-x01-probe-20261031T181116Z.json](./evidence/nursing-x01-probe-20261031T181116Z.json); harness + grade CSV (`closes_gap:false`); no attested clinician grades | Clinical-graded 20-case acceptance from **live** drafts | E1 + clinical | Mitigated |
| G-14 | External MCP | Demo listener exists; partner productisation incomplete | S2 | `mcp-external` + kill-switch + expanded signed-context conformance suite (`services/mcp-external/tests/test_conformance.py`); flag/`EXTERNAL_MCP_ENABLED` default off; read-only tools only; `config/external_mcp.yaml` versioning (`X-Sahyog-Api-Version`) + per-actor in-process quota (429/`Retry-After`); `/meta` `adapters.external_mcp` kill-switch visibility; named CI step; [runbook](./runbooks/mcp-external.md) (Compose only — **no K8s manifest**) | Per-consumer credentials, shared quota store, X-03 post-handover; named consumer | E2 + security | Mitigated |
| G-15 | FinOps history | Forecast calibration, chargeback and price book need real operating history; R1–R3 provide showback and configurable what-if | S3 | Label forecasts/estimates; Admin Governance retention panel sets `finops_history_days`; no false precision; chargeback disabled | 8–12 weeks of usage history; finance approval; post-R3 roadmap | Analytics + finance | Deferred |
| G-16 | Eval realism | Eval sets are synthetic; judge lacks attested human calibration | S2 | Safety gate authoritative; Admin Governance `judge_min_kappa` + `judge_require_attested_human`; `scripts/calibrate-judge.sh` + harness; provisional smoke stays `pending` without attested human file | Human-grade stratified sample; κ≥0.6; re-calibrate after model/prompt changes | E1 + clinical | Mitigated |
| G-17 | Load realism | P-host smoke + short r3 recorded; M/L `capacity_accepted` not claimed | S2 | JSON + [load_test_report.md](./evidence/load_test_report.md); [R1 matched](./evidence/load_test_r1_matched_20261102T004206Z.json) + [R3 matched](./evidence/load_test_r3_matched_20261102T004206Z.json); `capacity_accepted=false` on P | Run r3/burst-4 on **M/L** host; commit labelled evidence with `capacity_accepted=true` | E2/E4 | Mitigated |
| G-18 | Secrets | `.env` still OK locally; vault/file backends ship for shared/prod | S1 if real credentials | `SECRETS_BACKEND=env\|file\|vault` (`app/core/vault.py`); process env wins; gitleaks; rotation runbook | Prefer vault in shared envs; rotate before real PHI credentials | E2 + security | Closed |
| G-19 | Residency | OpenRouter and external channels are outside the boundary; only de-identified text may leave, but subprocessor review is not complete | S1 if misconfigured | DPDP audit register + stop-processing middleware ([dpdp-audit-report.md](./evidence/dpdp-audit-report.md)); egress disabled by default; composite PII **proven** (G-28); admin egress toggle requires composite+DPDP attested+env; W3 local; allowlists | Signed DPA + security sign-off before enabling egress | Security + client | Mitigated |
| G-20 | Formatting | Date/number/currency/name formatting and address conventions may not cover every Indian locale/script edge case | S3 | `Intl` en-IN/hi-IN/mr-IN; unit harness for formatter helpers; English fallback | Native locale QA on real UI screenshots per release | E3 | Mitigated |
| G-21 | Analytics privacy | Small-cell suppression reduces precision for very small clinics; suppressed values are not shown as zero | S3 | Suppression/aggregation; default minimum 5; [analytics-small-cell-threshold.md](./evidence/analytics-small-cell-threshold.md); no patient-level export | Privacy review only if threshold changes | Analytics + compliance | Closed |
| G-22 | Real-user load coexistence | A shared-environment load run can still affect real users if the guard thresholds are wrong or the host saturates | S1 if unapproved | Approval window; dedicated cohort; abort guard unit-proven; live `LOAD_TEST_KILL=1` drill [load_test_kill_drill_20261031T170411Z.json](./evidence/load_test_kill_drill_20261031T170411Z.json) (`kill_drill_passed` / `budget_guard`); outbound notifications off; incident runbook | Production-window threshold review + on-call sign-off before shared-env capacity runs | E2 + on-call | Mitigated |
| G-23 | Agent tracing | Closed. Graph/node/tool/model calls emit spans with identifiers, counts, hashes and durations only; a per-request collector exports to Langfuse with content capture off. The trace ID is stored on chat messages, scribe runs and audit events and shown in the run view | S2 | Structured logs, audit events, LiteLLM usage records and eval provenance corroborate; no prompt/completion content in trace input/output | Re-verify after instrumentation or exporter changes; keep content capture off | E2 + platform | Closed |
| G-24 | Preference memory | API/UI/Mem0 sync exist; provenance UI confirmation incomplete | S2 | Flag on in pilot; allowlist + clinical reject; Settings Forget/purge; API e2e [mem0-forget-e2e-20261031T180949Z.json](./evidence/mem0-forget-e2e-20261031T180949Z.json) (`closes_gap:false`); Mem0 Compose `core` profile up | Operator confirms Settings provenance vs live Mem0 store | E1 + product | Mitigated |
| G-25 | Operations | Staff email/Slack + 2‑min SLA ship; **production MTTA not claimed** | S2 if an alert fires | [mtta-and-paging.md](./runbooks/mtta-and-paging.md); Alertmanager drills; live email/Slack probe; `NOTIFY_OPS_SUBJECT` | Record MTTA on real on-call rota before SLO claim | E2 + on-call | Mitigated |
| G-26 | Browser quality | Closed for **browser automation coverage of the flows it asserts** only. Playwright covers Keycloak sign-in, chat/provenance, **front-desk Appointments** booking, scribe and analytics, plus axe/dark/360 px (20/20 on 2026-10-25). It does **not** prove assistant `slot_choice` / chat interrupt booking (G-39) | S2 | Typechecked React build and server-side contract tests remain; screenshots recorded; residual assistant booking tracked in G-39 | Add chat slot-interrupt e2e with G-39 closure; keep axe in CI | E3 | Closed |
| G-27 | Image supply chain | Tag pins; CI Semgrep/Trivy/SBOM jobs advisory (not yet digest-pinned blocking) | S2 | Digest capture [image-digests-20261031T124646Z.txt](./evidence/image-digests-20261031T124646Z.txt); [supply-chain-status.md](./evidence/supply-chain-status.md) — Semgrep/Trivy/SBOM remain `continue-on-error: true` | Digest overlay default + make Trivy/SBOM/Semgrep blocking after green advisory run; pod-security exceptions recorded | E2 + security | Mitigated |
| G-28 | PII and de-identification | Composite runtime proven (`engine=composite`); egress still off pending security sign-off | S1 | Fail-closed gateway + `EXTERNAL_EGRESS=false`; Governance shows PII health + egress may_enable; image `sahyog-api:local` (CPU torch + spaCy + GLiNER); [mcp-pii-detect-probe.json](./evidence/mcp-pii-detect-probe.json); [prove](./evidence/pii-composite-prove-20261031.md) | Security sign-off before enabling egress; keep composite healthy on recreate | Security + clinical | Mitigated |
| G-29 | Local decision and speech models | OpenDecider via host Ollama proven; EN STT WER measured (G-05 residual hi/mr) | S2 | Parses `message.reasoning`/`thinking`; [venv](./evidence/opendecider-ollama-classify-20261031T134008Z.json) + [mcp-decider](./evidence/opendecider-mcp-decider-classify-20261031T135627Z.json) both `engine=opendecider_openai_compatible`; keyword fallback only when unreachable; Whisper on disk + EN WER evidence | Multilingual WER (G-05); keep cold-start timeout tuned | E1 + E4 | Mitigated |
| G-30 | Async analytics jobs | Core analytics jobs scheduled; `ops.backup` + `ops.stock_import` registered and fail visibly when unconfigured | S2 | `job_runs` + `/metrics` `sahyog_job_*`; alerts loaded; age-encrypted backup proven ([encrypted-backup-20261031T174501Z.json](./evidence/encrypted-backup-20261031T174501Z.json)); [backup-and-stock.md](./runbooks/backup-and-stock.md) | Wire `BACKUP_OUT_DIR` for scheduled Compose backup; keep age identity offline | Analytics + platform | Mitigated |
| G-31 | FinOps reconciliation | Reconciliation exercised; billing-grade month review incomplete | S2 | Read-only importer; `/analytics/finops`; `/metrics` `sahyog_finops_variance_*` + alert `SahyogFinopsVariance`; `partial` never shown as matched | Pinned price/FX per period + representative paid month review (G-15) | Finance + analytics | Mitigated |
| G-32 | Upload malware scanning | Closed. Documents and completed audio are scanned before acceptance via ClamAV INSTREAM; infected objects are quarantined with status, engine version and audit event; `MALWARE_SCAN_MODE=required` fails uploads closed when the scanner is unavailable. EICAR document/audio, clean-file and outage cases were exercised | S1 if untrusted uploads | Multi-arch ClamAV with persisted signatures; no file content in logs; private buckets; scanner settings are profile-aware | Re-run EICAR and outage checks after image/scanner changes; keep `required` for patient uploads | Security + platform | Closed |
| G-33 | Consent lifecycle | Closed. Consent is now a lifecycle, not only a predicate: `consents` carries grantor, purpose, scope, `granted_at`, `expires_at` and `revoked_at`; `/api/v1/consents` lists, grants and revokes; `/api/v1/me/contexts` activates and clears an explicit caregiver context carried by `X-Consent-Id`; the `/care-circle` page grants scope/expiry, revokes, shows status and offers the context switch; every patient-linked access records `consent_id` | S1 if revocation is unavailable | Active-consent predicate on every caregiver read, scheduled expiry, audit of grant/activate/revoke/expiry and of patient-linked access; a deliberate context clear persists instead of being auto-reselected | Tests: consent CRUD, revocation, expiry, cross-patient refusal and context activation in `apps/api/tests/test_consents_integration.py`; live caregiver and patient flows in Compose. Residual: no consent-history view; RLS remains G-10 | Security + product | Closed |
| G-34 | Patient data rights | Closed. A patient can delete a document (object, chunks, citation references and audit event in one request), download the original through a short-lived presigned URL, export record metadata and request or cancel deletion; the worker purges after the configured grace period with an audit event per phase | S2 | Storage failure fails a delete closed rather than leaving orphaned metadata; export is metadata-only and states its exclusions; deletion is two-phase and audited | Tests: document delete and cross-patient refusal, metadata export, purge and presigned download in `apps/api/tests/test_privacy_integration.py`; live export for the demo patient. Residual: no orphan scan; no scheduled production purge evidence | Product + security | Closed |
| G-35 | Public data estate | Five public sources inventoried from actual Kaggle downloads | S2 | [public-source-inventory-20261031T165720Z.json](./evidence/public-source-inventory-20261031T165720Z.json) `status=passed` (all five `inventoried` with row_count+sha256); contracts updated; raw under `data/raw/` (gitignored); 4 licences still `check_and_record` | Human licence review for notes/symptoms/medicines/patients before redistribute; keep inventory fresh after re-download | Data owner | Closed |
| G-36 | Accessibility and browser conformance | No signed WCAG 2.2 AA or full cross-browser matrix yet | S2 if a core flow is inaccessible | Axe smoke; `scripts/wcag_report.py` → [wcag_report.md](./evidence/wcag_report.md) (honest NOT CLAIMED); [a11y-manual-checklist.md](./evidence/a11y-manual-checklist.md); optional Firefox/WebKit; no AA claim | Complete checklist + SR pass + sign-off JSON; fix findings | Design + QA | Mitigated |
| G-37 | CI and release evidence | Mitigated. Live Postgres migrate/test, npm audit (blocking), pip-audit (advisory), plus advisory Semgrep/Trivy/SBOM/`red_team_runner` in `supply-chain` job. Still lacks Vitest/RTL/coverage, dependency-cruiser, Playwright/axe in CI, nightly RAGAS/DeepEval, budgets, flag-mutation tests and a clean-machine acceptance log | S2 | New gates exist but Semgrep/Trivy/SBOM are continue-on-error until green; Python audit remains advisory | Make supply-chain blocking; add remaining §8.4 stages; clean-checkout release log | Platform + security | Mitigated |
| G-38 | As-built API/UI delta | OpenAPI catalogue regenerator exists; design-table leftovers not yet product-signed out of scope | S2 | Regen 2026-10-31: **144 paths / 165 ops**; `scripts/diff_api_catalogue.py` classifies all 114 design rows (57 matched, 45 renamed, 7 proposed out-of-scope, 5 deferred, 0 unresolved) → [api-catalogue-diff.md](./evidence/api-catalogue-diff.md); [product note](./evidence/api-leftovers-product-note.md) is **unsigned**; design tables remain target map | Keep regenerating each release; **product marks leftovers out of scope** (sign-off) | Product + E1/E2 | Mitigated |
| G-39 | Assistant booking slots | Chat slot/specialty/doctor cards + resume path | S2 | UI + W1 + e2e case; soak [chat-interrupt-ha-soak-20261101T064947Z.json](./evidence/chat-interrupt-ha-soak-20261101T064947Z.json) | Keep Playwright green in CI when feasible | E1 + E3 | Closed |
| G-40 | Specialty clarify | Confidence gate + `specialty_choice` interrupt before slots (`clarify_specialty_below=0.6`) | S2 | Low confidence forces specialty confirm; cancel available | Optional clarify-rate dashboard | E1 | Closed |
| G-41 | Chat booking via MCP | Chat resume calls MCP `hold_slot` → `confirm_booking` (no direct agent repo create) | S2 | Tool provenance on confirmation message | Keep broker allowlist under load | E1 + E2 | Closed |
| G-42 | Chat booking notify | `booking_confirmed` via NotificationService; email/Slack channels proven (G-06) | S2 | In-app always; external when configured | Optional SMS when enabled | E1 + E4 | Closed |
| G-43 | Booking idempotency | Migration `0019_booking_idempotency` + resume key lookup; partial unique active slot index | S2 | Retries return same appointment when key repeats | Soak showed idempotent resume 409 | E2 | Closed |
| G-44 | Red-flag handoff | Chat emergency creates handoff + SLA + staff email/Slack notify | S1 | Guidance + ticket + 2-min SLA; `NOTIFY_OPS_SUBJECT` | MTTA measurement stays G-25 | E1 + platform | Closed |
| G-45 | appointment_help + hold UX | Help graph + soft-hold countdown + `POST /appointments/{id}/confirm` | S2 | Cards/hold UI; `test_chat_hold_confirm.py` | Attach Playwright hold→confirm run when convenient | E1 | Closed |
| G-46 | Durable interrupt | W1 `interrupt()` + checkpointer; soak harness | S2 | [chat-interrupt-ha-soak-20261101T064947Z.json](./evidence/chat-interrupt-ha-soak-20261101T064947Z.json) (`same_base=true`) | Re-run with `API_A`≠`API_B` for multi-replica claim | E1 + E2 | Mitigated |
| G-47 | Chat streaming | Conversation + grounded-ask token drip after retrieve; foreign citation replaces draft | S2 | Stream router + `test_w2_ask_stream.py` | Optional drip-fail rate dashboard | E1 + E3 | Closed |
| G-48 | Staff escalation UX | Escalations SLA + denser `/front-desk` live handoffs/assistant bookings | S2 | Ops console + i18n | MTTA under G-25 | E3 + product | Closed |
| G-49 | Ollama memory | Host cap script/LaunchAgent: context 8192, max loaded 1 | S2 | `scripts/ollama-memory-cap.sh` | Re-verify after Ollama upgrades | E4 + platform | Closed |
| G-50 | Chat attach → records | Chat paperclip → Records ingest; `document_ready` notify + in-thread system notice on index | S2 | Malware path + indexed notice when session matches uploader/patient | Keep notice if user switched sessions mid-ingest | E1 + E3 | Mitigated |

## 3. Detailed gaps and plans

### G-01 — Translation coverage and visible fallback

**What is true.** The R1 baseline commits to English, Hindi and Marathi UI strings, validation, safety copy and notification templates (`FR-I18N-05`). Every key, including safety copy, must exist in all three locales for `scripts/i18n_check.py` to pass; that check enforces coverage and placeholders, not translation quality or reviewer sign-off. Secondary copy added late in a slice may not have a reviewed translation at the same moment.

**Why it matters.** A missing emergency instruction is a safety defect; a missing settings label is a quality defect. Treating both the same either blocks every release or hides a safety hole.

**Control.** Every user-facing string is externalized. `scripts/i18n_check.py` runs in CI and fails on any hi-IN/mr-IN key missing against English, any extra key, or any placeholder mismatch, so a new safety key cannot ship absent from a locale. `scripts/i18n_safety_key_audit.py` inventories safety keys, reads `docs/evidence/i18n-clinical-signoff.json`, and writes both the audit JSON and [clinical-i18n-report.md](./evidence/clinical-i18n-report.md). `scripts/eval_report.py` embeds the same sign-off block in the evaluation/handover report so an approval is visible there too. Until `review_status=approved` with `approver.name` and `signed_at`, reports must show **unreviewed**. At runtime `t()` falls back to English silently. Coverage is gated; linguistic quality is not.

**Closure.** Clinical reviewer completes `i18n-clinical-signoff.json` (see example); re-run the audit; clinical + eval reports show approver and timestamp; screenshots of all three locales on critical routes. Until then this stays `Mitigated`.

### G-02 — Machine translation is not clinical validation

**What is true.** The app may translate content for convenience, but translation can change clinical meaning. No machine-translated output is a validated clinical instruction or a substitute for the source note.

**Control.** Preserve the source text and language metadata; label translated content; keep clinical decisions with a human; never auto-sign or auto-send a translated clinical instruction. Safety copy is translated and must be human-reviewed before release. Sign-off is recorded only via `i18n-clinical-signoff.json` and is rendered in the clinical i18n report and eval report — never inferred from a green i18n CI check.

**Closure.** Clinical reviewer approves the hi/mr safety and patient-facing catalogue in the sign-off JSON; reports show **approved** with named approver and `signed_at`. Remains `Mitigated` until that review exists.

### G-03 — Mixed-script retrieval

**What is true.** A patient may type "sugar" in Latin script, "मधुमेह" in Devanagari, or a Hinglish sentence. Lexical search can miss transliterated drug names, and embeddings can cluster mixed-language text imperfectly. The 2026-10-25 RAGAS W3 slice measured answer relevancy 0.616 for `en-IN`, 0.433 for `hi-IN`, 0.338 for `mixed-script` and 0.429 for `mr-IN`; that is an answer-quality signal, not a recall measurement, but it shows the mixed-script path is the weakest.

**Control.** Multilingual `bge-m3` embeddings, cosine vector retrieval, `ILIKE` lexical matching for titles and medication names, language metadata, citation-first answering and a refusal when evidence is weak. `pg_trgm` is installed by migration but the retrieval query does not use trigram similarity, and no transliteration or query-expansion candidate generator is implemented. The scope guard remains SQL-side, so a retrieval miss cannot become a cross-patient citation.

**Plan.** The deterministic W1/W2 suite proves red-flag and provenance behaviour but does not measure retrieval recall. Use the six mixed-script cases in each of the W3/X-01 suites to measure retrieval recall@k by language/script; add a transliteration dictionary for common drug/specialty terms and wire trigram/expansion candidates into the query; review the lowest-scoring mixed-script answers. Closure is a measured recall improvement with no safety regression, not a claim that all transliterations are solved.

### G-04 — Language quality by model and purpose

**What is true.** A 7–8B local model that is good enough for English W3 drafting may be weaker in Marathi; an external model may be stronger but only receives de-identified text. One model for every purpose is explicitly rejected (`Q-10`, `D-24`). The 2026-10-25 synthetic slices confirm the pattern: RAGAS W3 answer relevancy was 0.616 (`en-IN`), 0.433 (`hi-IN`), 0.338 (`mixed-script`) and 0.429 (`mr-IN`); DeepEval X-01 answer relevancy was 0.792, 0.622, 0.672 and 0.500 for the same order. Marathi and mixed-script are the weakest slices.

**Control.** Purpose-based routing (`config/models.yaml`) plus optional `language_routing` overrides (hi/mr conversation/summarize/triage → `local_main`). `evals/harness/language_eval_slice.py` aggregates **actual** committed RAGAS/DeepEval run scores by language. Human hand-off on weak grounding remains. W3 identified text stays local regardless of quality pressure.

**Plan.** Re-measure quality/latency/memory per language on Mac and M/L; keep overrides only where evidence supports them; record residual quality. A stronger local model may require M/L; that is a capacity decision, not a reason to send identified text out.

### G-05 — Speech and OCR in mixed language

**What is true.** Code-mixed Hindi/Marathi/English speech and Devanagari OCR can have higher word-error/character-error rates. faster-whisper weights are present; live mcp-stt against three public LibriSpeech English clips produced measured WER **mean 0.0** after standard case/punctuation normalisation ([stt-wer-score-aggregate-20261031T170248Z.json](./evidence/stt-wer-score-aggregate-20261031T170248Z.json); status note [g05-stt-wer-status.md](./evidence/g05-stt-wer-status.md)). Hindi/Marathi/code-mixed clinical speech and Devanagari OCR CER are **not** measured. Silent or invented WAV/hypotheses are refused (`synthetic:true`).

**Control.** Manual transcript entry/upload, transcript status and language shown, doctor edit before signature, no auto-sign, and page/section preservation for OCR citations. Audio-only upload fails with `stt_unavailable` when STT is down rather than showing fabricated confidence.

**Residual / plan.** Stay `Mitigated` until hi/mr (+ clinical) WER and OCR CER are measured with public/human references. Re-run `scripts/stt_wer_live.sh` + `wer_cer.py` after STT model changes. Do not present automated transcription as a validated clinical record.

### G-06 — Notification providers and policy

**What is true.** Email (SMTP) and Slack staff delivery are configured and proven for this pilot ([notify-channels-probe-20261101T064929Z.json](./evidence/notify-channels-probe-20261101T064929Z.json): direct + queued `sent`). Staff Slack posts to an allowlisted **channel** (user DMs fail with `channel_not_found` unless the bot has an open conversation). SMS remains **optional** (`notifications_sms` default false; channel disabled in `notifications.yaml`).

**Control.** Channels show `unconfigured` until settings validate; in-app is source of truth; no clinical detail externally; `NOTIFY_OPS_SUBJECT` + verified contacts required for staff_handoff email/Slack; delivery records carry status/attempts.

**Closure.** Email + Slack staff closed for pilot ship. SMS stays an optional residual until a client enables DLT/provider credentials. Re-run `scripts/probe_notify_channels.py --write-evidence` after credential rotation. **Closed** (v1.16; SMS caveat documented).

### G-07 — Patient Slack identity

**What is true.** Patient Slack is opt-in and requires a verified Slack ID captured at onboarding or in settings. A stale ID can send to the wrong person or fail silently.

**Control.** Separate staff and patient workspaces; delivery requires an existing verified contact, explicit opt-in for patient Slack and the expected workspace ID. A missing, unverified, non-opted-in or wrong-workspace contact is suppressed with `recipient_missing`, `recipient_unverified`, `opt_in_required` or `workspace_mismatch`; there is no channel-wide mention and in-app notification remains. The patient cannot be placed in the staff workspace through the normal admin path. ARQ scheduler job `contact_reverification_job` (daily) queries `ContactChannel.verified_at` older than 180 days and writes `job_runs` + audit; `scripts/contact_reverification_scan.py` supports `--database` for cron-callable read-only scans.

**Plan.** Surface the suppression reason in the patient's settings; audit every mapping change. Unit proof: `apps/api/tests/test_contact_reverification_job.py`. Closure is **100% verified coverage for every opted-in patient** (ops evidence), not merely the scan job — stay `Mitigated` until that coverage evidence exists.

### G-08 / G-09 — FHIR and ABDM boundary

**What is true.** The read-only FHIR R4 adapter required by `FR-DATA-09` is implemented: `HttpFhirAdapter` with optional OAuth client-credentials, `fhir_patient_links` crosswalk, audited `GET /api/v1/fhir/patients/{id}` and `.../encounters`, and admin `PUT .../link`. A clinician SPA panel exists at `/patients/:id/fhir` with honest empty states when unlinked/unconfigured. There is still no write-back, no ABDM linking and no certification. The write/ABDM boundary remains intentional (G-09).

**Control.** `/meta` reports `configured` / `unconfigured` / `disabled`; missing crosswalk or FHIR errors fail visibly; no runtime mock adapter; ABDM UI always shows `certified:false`.

**Follow-on.** HIS-specific identifier mapping and contract tests against the client test server. FHIR write-back and ABDM certification remain roadmap items ([roadmap.md](./roadmap.md)).

### G-10 — RLS, column encryption and break-glass

**What is true.** R1–R3 enforce authorization with repository predicates, server-derived context, IDOR/scope tests and audit. They do not implement Postgres row-level security, field/column encryption for direct identifiers or break-glass access. Direct identifiers are stored in Postgres and protected by database access control and scope predicates, not by application-level field encryption.

**Why it is not silently accepted.** A predicate bug could expose another patient's row. The control is defense in depth: SQL-side scope filters, repository-owned patient-record queries (the only raw SQL outside repositories is the `SELECT 1` health probe and the read-only LiteLLM spend import), foreign-key ownership checks on citations, audit of every patient-linked read/write, cross-patient provenance tests and broker scope tests. Break-glass is absent, so there is no bypass path to abuse. The missing field encryption means a database-level compromise is out of scope for application controls; that is recorded, not glossed over.

**Plan.** Independent security review and a predicate/IDOR test report; RLS and broader encryption are post-pilot hardening. Any scope failure is a safety defect and a stop-the-line event, not a backlog item.

### G-11 — Single-site pilot and HA

**What is true.** Compose and the pilot K8s overlay are single-site. Kubernetes manifests for HA are delivered and validated by rendering and schema checks, but this build has not run them on kind, a managed cluster or a pilot cluster. The pilot does not prove failover, multi-AZ or cross-region DR. The Mac pilot has no redundant power/storage/network.

**Control.** No HA and no "Kubernetes-verified" claim; backup/restore scripts and a runbook exist, but no restore drill is recorded (G-25); readiness is truthful; K8s production topology is documented; no production patient use on the pilot. `Q-30` sets RPO 24 h baseline/15 min target and RTO 4 h for production.

**Plan.** Run the manifests on a disposable cluster (kind or a client-approved cluster), then a restore/failover exercise on the M/L profile before a production claim; record measured RPO/RTO and any image/security-context exceptions (for example third-party images that cannot satisfy the restricted profile). HA is a procurement/architecture step, not a code flag.

### G-12 — Clinical validation and regulatory status

**What is true.** This is a demonstration and pilot system, not a validated medical device. It does not diagnose, prescribe or calculate doses, and it does not replace a clinician's judgement. An in-product **attestation gate** now records whether a named clinical/regulatory owner uploaded a validation report and attested it; that is product posture only.

**Control.** Admin Governance → Compliance: upload report (MinIO) + required checkbox + approver name/role → `compliance_attestations` (`not_attested`/`attested`/`revoked`); `/meta.capabilities.clinically_validated`; [clinical-validation-status.json](./evidence/clinical-validation-status.json); visible disclaimer; red-flag rules fail-closed; HITL; W3 signature; X-01 clinician acceptance (G-13); no diagnosis/dose in patient chat. Attestation never equates to CDSCO/FDA/MDR clearance.

**Plan.** Product owner may accept the attestation gate as the in-repo closure for this build (status stays Mitigated unless they explicitly Close), or commission a regulatory plan before any clinical-use marketing claim. Engineering cannot Close this as “compliant device.”

### G-13 — X-01 nursing summary clinical quality incomplete

**What is true.** Bounded X-01 is implemented behind `x01_nursing_summary` (default `false`): `/api/v1/nursing` draft + accept/edit/reject versioning, API/UI gated by flag/`/meta`. Eval fixtures `evals/sets/nursing_x01.jsonl` (20 intent cases) plus `evals/harness/nursing_x01_runner.py` / `evals/tests/test_nursing_x01_runner.py` cover intent/citation **shape** only — no authored draft scores and no clinical-graded live drafts.

**Why it matters.** A committed R3 slice must not be treated as clinically accepted because the API and fixture shape exist. Shape checks prove structure, not nursing quality.

**Control.** Flag default off and reported off when disabled. Shape runner labels itself as intent/citation only (`clinical quality not scored`). No clinical acceptance claim without graded live drafts.

**Plan.** Produce clinical-graded acceptance over 20 **live** drafts (not fixture IDs alone); keep citation/acceptance audit. Live EHR ingestion and ward-level summaries remain post-handover. Stay `Mitigated` until that clinical evidence exists.

### G-14 — External MCP productisation

**What is true.** A read-only demo listener exists (`services/mcp-external`) behind `EXTERNAL_MCP_ENABLED` (default false). Expanded signed-context conformance suite is in-repo (`services/mcp-external/tests/test_conformance.py`: kill-switch, missing/forged context refusal, valid context reaches ping). There is still no third-party consumer credential, per-consumer quota/versioning, support model or certification. The internal broker continues to use signed context between the API and internal MCP servers.

**Control.** Flag default off; empty catalogue when disabled; tool invoke refuses missing/forged `X-Sahyog-Context`; read-only tools only. Internal MCP remains the production path.

**Plan.** X-03 partner productisation post-handover: per-consumer credentials, quotas, versioning, onboarding, developer contract and a named consumer. Signed-context suite is interim control only — stay `Mitigated` until productisation closes.

### G-15 — FinOps history and chargeback

**What is true.** R1–R3 include showback, budgets, unit economics, a configurable price book and a what-if/growth model. Forecast calibration, chargeback and an approved tenant/clinic price book need real operating history and finance approval.

**Control.** Forecasts are labelled estimates with method/window; showback is aggregate-only and audited; no chargeback invoices; AI recommendations are advisory; `config/finops_model.yaml` version is visible.

**Plan.** Eight to twelve weeks of usage history, forecast calibration, finance approval and a chargeback decision. This is post-R3 roadmap work, not a missing R1 feature.

### G-16 — Eval realism and judge calibration

**What is true.** Every eval fixture is synthetic. The deterministic safety gate covers 60 W1/W2 cases and passed 60/60 on 2026-10-25. Two 24-case answer-bearing suites are now populated, six cases per language slice (`en-IN`, `hi-IN`, `mr-IN`, `mixed-script`): `rag_w3` scored by RAGAS 0.4.3 and `qa_x01` scored by DeepEval 3.9.9, both through LiteLLM with `local_main` as judge. RAGAS W3 overall: answer relevancy 0.454, context precision 0.958, context recall 0.958, faithfulness 0.801. DeepEval X-01 overall: answer relevancy 0.647, contextual precision 0.958, contextual recall 0.938, faithfulness 0.728; 10 of 24 cases fall below the metric's default threshold, mostly answer relevancy in Hindi/Marathi, and the failures are recorded per case rather than hidden in the mean. The judge has not been calibrated against a human-reviewed sample: the 20-item calibration artefact is `unreviewed`, `human_review_performed` is false and Cohen's kappa is null. No answer comes from a live chat/scribe pipeline and no clinician has reviewed the fixtures.

**Why it matters.** A deterministic safety suite proves rule and resolver behaviour; it does not prove answer quality, faithfulness or judge agreement. A judge that has never been compared with a human reviewer can be lenient or harsh in ways the score cannot show. Treating a synthetic benchmark or an unreviewed judge as clinical evidence would be a false quality claim.

**Control.** The deterministic safety checks are the only release gate and pass 60/60 in this build; framework scores cannot override them (`framework_scores_can_override: false`). The harness records framework/version, dataset hash, prompt/graph version, judge alias, git SHA, per-case results and per-language slices, and exits non-zero when a framework is unavailable. Per-case failures are retained; the report labels the judge `unreviewed` and the fixtures synthetic. No aggregate score is displayed as clinical validation.

**Plan.** Human-grade a stratified sample of the 20 calibration pairs, compute observed agreement and Cohen's kappa, and re-calibrate after model/prompt changes. Add a live-pipeline runner so chat/scribe answers are scored rather than only authored fixtures; obtain clinical review of hi/mr and mixed-script answers. The residual gap is stated in the G5 report; it is not hidden by an aggregate score.

### G-17 — Load realism

**What is true.** The committed P-host runs are the 2026-11-02 matched profiles: R1 at 509.6 req/h for 10 minutes (p95 57.9 ms, 0% errors) and R3 at 1,833.5 req/h for 5 minutes with 4× burst (p95 50.9 ms, 0% errors). Both keep `capacity_accepted=false`. That is a latency and error check on the pilot host, not an M/L capacity proof. The load test uses synthetic traffic and a dedicated Keycloak cohort; it cannot reproduce every real clinical behaviour.

**Control.** Separate `traffic_class=synthetic`; real-user abort guard; outbound notifications disabled for capacity runs; report test vs real separately; no capacity claim on P; the R3 capacity claim stays tied to an M/L host. Evidence: [load_test_report.md](./evidence/load_test_report.md).

**Plan.** Run the R3 profile on the M/L profile with 1,400 req/h and 4× burst, compare with real-user telemetry, and re-run the sizing model. If the measured result misses, record a variance and resize; do not relabel the Mac smoke as a capacity result.

### G-18 — Secrets and vault

**What is true.** The local pilot reads secrets from `.env`; production requires a secret manager. `.env` is gitignored, but a local file is weaker than a vault with rotation and access control.

**Control.** Synthetic data only on the pilot; no real patient credentials; `.env` excluded from git; gitleaks runs in CI; rotation runbook; production rejects default passwords. No custom PHI scanner is implemented in this build, so PHI hygiene relies on synthetic fixtures and review rather than an automated scan (the runtime PII gate is G-28). The app never sends secrets to the browser or logs.

**Closure.** `SECRETS_BACKEND=env|file|vault` loads into process env before Settings (`app/core/vault.py`); existing env wins. Local `.env` remains valid for pilot. Prefer vault/CSI in shared environments; rotate before real PHI credentials. **Closed** (v1.16).

### G-19 — Residency and subprocessors

**What is true.** The application and data stores run in-boundary; OpenRouter receives only de-identified text; SMTP/SMS/Slack are external channels with minimal templates. Subprocessor/DPA review is not complete in this build. The composite PII gate that must sit in front of any egress is now runtime-proven (G-28); that does not satisfy DPA/subprocessor closure.

**Control.** DPDP audit register (upload/attest findings) + `DpdpStopProcessingMiddleware` when `disapproved` or when `dpdp_enforce` without `attested` ([dpdp-audit-report.md](./evidence/dpdp-audit-report.md)); egress disabled by default (`EXTERNAL_EGRESS` remains false); admin egress toggle refuses unless composite healthy + DPDP attested + env flag; fail-closed PII gate (G-28); W3 local; channel allowlists; no clinical detail in notifications; audit. Residual honesty: register ≠ signed DPA.

**Plan.** Complete the DPDP/subprocessor review and signed DPAs before production; record the approved destinations and egress evidence. Do not enable an external route because a demo would look better. Stay `Mitigated` until DPA/security sign-off.

### G-20 — Locale formatting

**What is true.** `Intl` covers the common `en-IN`/`hi-IN`/`mr-IN` formats, but names, addresses, phone formats and mixed-script text have edge cases that a small fixture set will not cover.

**Control.** Unicode-safe storage, no English-only validation, English fallback for missing strings, fixtures for common Indian names/addresses/numbers. Formatting never changes a clinical value or a dose; those are strings from the source with no locale transformation.

**Plan.** `evals/fixtures/locale_format.json` + harness cover currency/date/number smoke cases. Locale QA pass with native reviewers; expand fixtures per reported edge case; close per release. Low severity unless a formatting bug changes clinical meaning, which would be reclassified.

### G-21 — Small-cell suppression

**What is true.** Analytics suppresses or aggregates patient-level counts below the configured minimum (default 5) to reduce re-identification risk. Small clinics see less precise numbers.

**Control.** The tile states suppression, never displays zero; exports are aggregate-only; compliance sees posture, not content. A user cannot drill down to a patient from analytics.

**Plan.** Document the threshold and rationale for compliance; revisit only with a privacy review. Precision is not restored by lowering the threshold without approval.

### G-22 — Real-user-safe load

**What is true.** A synthetic load test can affect real users on a shared host if the guard thresholds are wrong or the host saturates.

**Control.** Approval window; dedicated test cohort; `LOAD_TEST_ALLOW_REAL_USERS` guard; abort on real-user p95/error or budget; outbound notifications off; synthetic traffic excluded from showback; incident runbook. `decide_guard_abort` is unit/integration tested (`apps/api/tests/test_load_abort_guard.py`). Live deliberate abort: `LOAD_TEST_KILL=1` against the Compose stack produced [load_test_kill_drill_20261031T170411Z.json](./evidence/load_test_kill_drill_20261031T170411Z.json) with `status=kill_drill_passed`, injected `budget_guard`, and `capacity_accepted=false` (drill never counts as capacity).

**Residual / plan.** Production-window threshold review and on-call sign-off before shared-environment capacity runs. A guard trip is a safety stop, not a failed benchmark to retry with the guard off.

### G-23 — Trace export and agent spans

**What is true.** Graph nodes, safety/PII gates, model calls, tool/MCP calls and retrieval steps emit spans with identifiers, counts, hashes and durations only. A per-request `TraceCollector` exports the span tree to the Langfuse ingestion API; the exporter refuses to run if content capture is enabled. The trace ID is stored on chat messages, scribe runs and audit events and is shown in the run and governance views. A real scribe request produced Langfuse trace `aee895d79abd43c291da2b7cde2c1456` with `scribe.safety`, `pii.pregate`, `llm.complete`, `scribe.draft` and `scribe.ground`; the generation names alias `local_main`, reports 361 prompt + 119 completion = 480 total tokens and the gateway request ID `chatcmpl-906d416f-978b-49ff-b7b2-042c9f0929a8`. The trace and its observations carry `input`/`output` as null. The originating app scribe run is `84ca076e-ea94-4794-a48d-53c6a3949b0c`, whose usage record carries the same gateway ID; a chat trace `8fdd55bdced746b5acefae4b52042cd5` and audit trace IDs were verified the same way.

**Why it matters.** Per-run observability is a product claim: an operator must be able to move from an audit event to the node/model/tool that produced a slow or failed answer without reading patient content.

**Control.** Content never enters trace input/output or span attributes. The exporter is best-effort with a 3-second timeout: a Langfuse outage or a sampled-out trace does not fail the clinical request. Export sampling is controlled by `TRACE_EXPORT_SAMPLE_RATIO` (default `0.1`; the pilot `.env` sets `1.0`). HTTP OTel spans and metrics remain configured for platform monitoring.

**Residual.** The exporter posts metadata-only events to the Langfuse v2 ingestion API rather than exporting OTLP natively, so instrumentation and exporter changes need the trace re-verified. Export failure is logged and dropped, not retried. Keep content capture off and re-run the no-PHI trace check after any agent or exporter change.

### G-24 — Preference memory with mem0

**What is true.** API/UI preference memory exists behind `memory_preferences` (default `false`): `/api/v1/me/memory`, Settings Forget/opt-out, allowlist + clinical reject, purge audits `not_clinical_evidence`, orchestrator wiring when enabled. Unit coverage in `apps/api/tests/test_memory_preferences.py`. **Live Mem0 Forget/opt-out e2e** and agent provenance UI check against a real Mem0 store remain incomplete.

**Why it matters.** Memory is a named requirement: a user should be able to say "I prefer the Baner clinic" and have that preference inform a later session without becoming clinical evidence. Unit mocks are not a substitute for live store behaviour.

**Control.** Flag default off and reported off. Allowlist + clinical reject; Forget audits non-clinical evidence. Source panel may render `memory` only from a real store resolution. Chat continues without memory when the flag is off or Mem0 is unavailable.

**Plan.** Run live Mem0 e2e (Forget/opt-out + provenance UI) and keep the "not clinical evidence" label. Stay `Mitigated` until that live evidence is linked.

### G-25 — Runbook coverage

**What is true.** Fifteen runbooks are delivered under [docs/runbooks/](./runbooks/) with an index that maps symptoms, diagnosis commands, mitigation, rollback and escalation. Prometheus `rule_files` + `alerting.alertmanagers` and a Compose `alertmanager` service (full profile) exist. `scripts/alertmanager-drill.sh` recorded successful live drills ([133523Z](./evidence/alertmanager-drill-20261031T133523Z.json), [170000Z](./evidence/alertmanager-drill-20261031T170000Z.json), [170003Z](./evidence/alertmanager-drill-20261031T170003Z.json), [174825Z](./evidence/alertmanager-drill-20261031T174825Z.json)); earlier unreachable attempt [095704Z](./evidence/alertmanager-drill-20261031T095704Z.json).

**Why it matters.** A runbook that no alert invokes is documentation, not an operational control. Without paging, response time under pressure is unproven.

**Control.** Alert rules carry `runbook_url` annotations; Alertmanager currently routes to a local webhook sink (not production paging). The drill script checks `/-/ready` and never invents a pass.

**Residual.** No real on-call page, no measured MTTA. Stay `Mitigated` until paging replaces the webhook sink.

**Plan.** Replace the webhook with Slack/email for on-call; keep repeating drills after routing changes. Scenario drills (restore, PII-gate, audit-chain, misdelivery, incident response) remain operator-run before a production gate.

### G-26 — Browser end-to-end and accessibility automation

**What is true.** A Playwright suite in `apps/web/e2e` runs against the Compose stack with real Keycloak sign-in. It covers chat with provenance, **front-desk Appointments** booking (not assistant chat `slot_choice`), scribe and analytics, runs axe checks on the main routes, verifies the dark theme and a 360 px viewport, and on 2026-10-25 completed 20/20 tests in 46.6 seconds. The suite is runnable through `scripts/test.sh --e2e`; evidence: [browser-e2e-20261025T095550Z.txt](./evidence/browser-e2e-20261025T095550Z.txt), [browser-e2e-20261025T095550Z.json](./evidence/browser-e2e-20261025T095550Z.json).

**Why it matters.** Server-side tests cannot catch a broken sign-in redirect, an inaccessible icon button, a mobile layout that hides a safety action or a theme that renders unreadable text. Closing “booking” automation without chat interrupt coverage overstates W1 UX (G-39).

**Control.** The suite is runnable with `scripts/test.sh --e2e` against a disposable local stack; failure blocks the release checklist. The axe run is a smoke check, not a WCAG conformance audit; no conformance claim is made. Screenshots are retained as evidence.

**Residual.** Not in CI (no disposable Compose/Keycloak). Assistant slot-interrupt e2e is **G-39**, not covered by the 2026-10-25 Closed evidence.

**Plan.** Add chat `slot_choice` flow with G-39; keep axe on every route; CI disposable stack remains a platform item (G-37).

### G-27 — Image supply chain and pod security

**What is true.** The MinIO image comes from the `bitnamilegacy` mirror. Compose images are pinned by tag in the default stack; digest capture evidence exists ([image-digests-20261031T124646Z.txt](./evidence/image-digests-20261031T124646Z.txt)) with an example overlay (`docker-compose.digests.example.yml`). CI job `supply-chain` runs Semgrep, Trivy FS and CycloneDX SBOM with **`continue-on-error: true`** (advisory) — see [supply-chain-status.md](./evidence/supply-chain-status.md). Those steps were not flipped to blocking because this pass had no green CI history to rely on. The K8s overlays set a restricted security context, but third-party images have not been run under that profile on a cluster.

**Control.** Image tags are pinned per release and documented registries are used; digest pins are optional via overlay; the repository's own images run non-root; no cluster-security claim is made; G-11 records the missing runtime validation.

**Plan.** Make digest overlay the operator default after remaining images pull; flip Semgrep/Trivy/SBOM to blocking only after a recorded green advisory run; record pod-security exceptions for third-party images. This is a release gate for a production claim, not a blocker for the Compose pilot.

### G-28 — Composite PII detection and de-identification

**What is true.** Composite runtime is **proven** on image `sahyog-api:local` (CPU torch 2.5.1, no CUDA; spaCy `en_core_web_sm`; GLiNER) with `mcp-pii` recreated. Signed detect probe [mcp-pii-detect-probe.json](./evidence/mcp-pii-detect-probe.json) reports `engine=composite`, `not_clinical_grade=false`, `count=3` (person / email_address / phone_number); write-up [pii-composite-prove-20261031.md](./evidence/pii-composite-prove-20261031.md). The earlier [blocker note](./evidence/pii-composite-blocker-20261031.md) (image missing Presidio/GLiNER/spaCy → `regex_fallback`) is superseded by that prove. The API `PiiGate` / `LlmGateway` still require `engine=composite`, `not_clinical_grade=false` and zero residual identifiers before any external chat/embedding route; with egress disabled the path uses a local fallback. Embedding redaction and batch-shape refusal remain covered by `test_llm_gateway.py`. The LiteLLM proxy still has no independent de-identification guard.

**Why it matters.** Names, addresses, dates of birth, free-text clinical identifiers and Hinglish variants are cases a regex alone cannot reliably find. A working composite gate is necessary but not sufficient for enabling egress: security must sign the evidence first. Treating the gate as production-approved without that sign-off would be a safety misrepresentation.

**Control.** `EXTERNAL_EGRESS` remains **false** until security sign-off; the application gateway's fail-closed gate stays the enforcement point; no PHI in logs or traces; no screen claims clinical-grade de-identification beyond the measured probe. Any caller that bypasses `LlmGateway` would not be stopped by LiteLLM.

**Residual / status.** `Mitigated` — composite path proven in-repo; Closure column still requires security sign-off before egress, so this is not Closed. Re-prove after image or model changes.

**Plan.** Obtain security sign-off on the prove evidence before enabling egress; add proxy-level guard as defence in depth; keep Hinglish/PHI fixtures and red-team refusal corpus green; re-verify `engine=composite` after every `mcp-pii` recreate. This remains a release blocker for external egress until that sign-off exists.

### G-29 — OpenDecider via Ollama and local STT

**What is true.** Host Ollama has `hf.co/manjunathshiva/opendecider-small-GGUF:Q8_0`. OpenDecider often returns empty `content` and puts JSON in `message.reasoning` (chat) or `thinking` (generate); `mcp-decider` now parses those fields. With `DECIDER_BACKEND=ollama`, Compose no longer shadows Ollama with `DECIDER_LLAMA_URL`→LiteLLM. Measured proves: host module [opendecider-ollama-classify-20261031T134008Z.json](./evidence/opendecider-ollama-classify-20261031T134008Z.json) and live `mcp-decider` [opendecider-mcp-decider-classify-20261031T135627Z.json](./evidence/opendecider-mcp-decider-classify-20261031T135627Z.json) both report `engine=opendecider_openai_compatible`. Keyword fallback remains labelled when the model is unreachable. Whisper weights exist; WER is G-05. Strands remains an optional labelled fallback. Cold Docker→host calls may need `DECIDER_HTTP_TIMEOUT_SECONDS` ≥ 240.

**Why it matters.** The spec names OpenDecider for intent/decisions. The named model path is now exercised; speech quality remains a separate gap.

**Control.** Decider responses state the classifier engine; red-flag safety never depends on the decider; no silent OpenDecider claim on keyword results.

**Plan.** EN WER is measured under G-05; residual multilingual/OCR WER stays there. Keep timeout/health checks honest after image or model changes. Residual status **Mitigated**.

### G-30 — Scheduled analytics, insights and operational jobs

**What is true.** In the `core`/`full` profiles the ARQ scheduler registers retention, consent expiry, metric snapshot (`minute=5`), FinOps reconciliation (`minute=10`), staleness (`minute=20`), insight generation (`03:10`), audit anchor (`02:45`) and audio/chat retention jobs; notification dispatch stays on the always-on worker. Every execution writes a `job_runs` row with status, timing and a JSON detail. The scheduler and worker poll separate ARQ queues (`sahyog:scheduler` / `sahyog:worker`) so one process cannot claim a function it does not register; after the separation was deployed, the worker ran `cron:dispatch_pending_notifications` and the scheduler ran manual job `78a76852662d4519b47721b680aa623e` (`finops.reconcile`) without a "function not found" error. Verified runs: `analytics.snapshot` wrote snapshot `1d21d7ff-6931-424b-96a7-cce810f2eea5` with `suppression_applied`; `analytics.insights` created/updated three `insights` rows with `generator=local_model`, `model_alias=local_main`, `ai_generated=true`, `status=proposed` and evidence; `analytics.audit_anchor` wrote anchor `anchors/20261025T075644Z.json` over 315 events with digest `7929d6eb...`; `analytics.staleness` reported snapshot/reconciliation age and an empty alert list when fresh; `finops.reconcile` completed with a populated `job_runs.detail` (`partial`, variance 0, app/gateway/matched counts) after the queue fix. `/analytics/insights` lists persisted insights and `POST /analytics/insights/{id}/decision` records accept/reject. Deterministic rules remain the fallback and no insight changes configuration.

**Why it matters.** Scheduled jobs are part of the analytics claim. A pilot may run some operations manually, but it must not imply a scheduler that does not exist or hide stale data.

**Control.** Jobs are observable in `job_runs`; the analytics response carries `as_of`/freshness; staleness is computed and surfaced; insights are advisory and audited; no scheduler run edits a usage row or applies configuration.

**Residual.** `ops.backup` and `ops.stock_import` are registered and write `job_runs` (fail visibly when unconfigured); runbook [backup-and-stock.md](./runbooks/backup-and-stock.md) documents operator steps. Age-encrypted backup is **proven** ([encrypted-backup-20261031T174501Z.json](./evidence/encrypted-backup-20261031T174501Z.json)); scheduled Compose backup still needs `BACKUP_OUT_DIR` wired for routine runs. Stock drop import depends on `config/stock.yaml` `drop_dir` and CSV drops. Prometheus scrapes API `/metrics` and loads `SahyogJobStale` / `SahyogJobFailures` ([g30-job-alerts-20261031T170745Z.json](./evidence/g30-job-alerts-20261031T170745Z.json)). The scheduler is a single process with no HA (G-11).

**Plan.** Keep `BACKUP_OUT_DIR` configured for scheduled encrypted backups; stay `Mitigated` for ops hygiene (not missing first proof).

### G-31 — LiteLLM spend reconciliation

**What is true.** A read-only importer copies `LiteLLM_SpendLogs` into `gateway_spend_logs` by gateway request ID, and the scheduled `finops.reconcile` job compares those rows with application `usage_record` rows over a 24-hour window under a declared price version, FX rate and tolerance. `/analytics/finops` reports the reconciliation status, matched/unmatched counts, match rate and variance; unmatched request IDs stay visible. A real gateway run produced `partial`: 19 app calls, 32 gateway calls, 12 matched, 7 unmatched app calls, 20 unmatched gateway calls, 0 variance on matched calls, match rate 37.5%, tolerance 2%, `price_version=1`, `fx_usd_inr=88`, `price_basis_date=2026-10-25` and 0 import errors. A second run immediately after the RAGAS/DeepEval suites produced `partial` with 21 app calls, 477 gateway calls, 14 matched, 463 unmatched gateway calls, 0 variance on matched calls and match rate 2.935%; the extra gateway rows are eval judge and embedding calls, which deliberately have no application usage row. The gap between gateway and app calls is itself the finding, not rounded away. No usage row is edited to force a match.

**Why it matters.** FinOps is a core claim. App records can diverge from gateway billing through retries, failed calls, price changes, evaluation traffic or traffic that bypasses the app. Without reconciliation, showback is a labelled estimate, not a billing-grade figure.

**Control.** Showback stays labelled; `partial` is never rendered as fully matched; unmatched calls remain visible; the importer never writes to LiteLLM or usage tables; the scheduled run and its `job_runs` record make the outcome auditable. The post-eval run also verified that the scheduler queue executes `finops.reconcile` and writes status, variance, app/gateway/matched counts into `job_runs.detail` instead of an empty object.

**Residual.** The current sample is small and locally priced at zero, so it proves the comparison path rather than a billing-grade variance. Automated variance alerting and price/FX-version pinning evidence are still missing (G-25, G-15). Unmatched gateway calls must be reviewed before any billing claim.

**Status.** `Mitigated`: the comparison path is delivered and exercised, but the closure conditions above are not met.

**Plan.** Add a variance alert with a runbook, pin price/FX versions per accounting period, and reconcile a representative month with real paid traffic before chargeback (G-15).

### G-32 — Upload malware scanning

**What is true.** Documents and completed audio uploads are scanned with ClamAV INSTREAM before acceptance. The verdict is stored on the record (status, engine and signature version, detail), a positive is moved to a quarantine key and audited, and `MALWARE_SCAN_MODE=required` rejects the upload when the scanner is unavailable. The `full` profile sets `CLAMAV_HOST=clamav` and `required` by default; `advisory` exists for development only and labels the verdict. Verified with ClamAV 1.4.6/28164: EICAR document `70d8800f-f344-4932-b2ff-bb4640abfc3d` was quarantined as infected with audit event `records.document_quarantined`; a clean document `2c50d868-df4f-4f51-86e6-0b4405ce00b9` was accepted and queued clean; EICAR audio `dc369076-d114-4947-88f7-e7e9afc27c68` was rejected with `malware_detected` and audit event `records.upload_blocked`; a clean audio `1a4a2be9-25df-4728-ba5c-7e5b1acc43d4` passed the scan and then failed honestly with `stt_unavailable` (G-29). No file content appears in logs or audit metadata.

**Why it matters.** A patient or staff upload is an untrusted file. A ClamAV container without wiring is a false sense of security; scanning before acceptance is the control that prevents infected content from entering the record store.

**Control.** Private buckets and short-lived presigned URLs; fail-closed by default in `full`; infected objects quarantined and never served; engine/version recorded; signature database persisted in a named volume; settings are profile-aware and documented in `.env.example`.

**Residual.** Detection depends on signature freshness and the ClamAV updater; `advisory` mode must never be used with patient uploads. Re-run the EICAR, clean-file and scanner-outage checks after image or scanner changes.

**Plan.** Keep `required` for patient uploads, alert on stale signatures/scanner unavailability (G-25), and re-run the three-case check at each release.

### G-33 — Consent lifecycle (closed)

**What was true.** The original build had enforcement without a lifecycle: a `consents` row gated caregiver access and the scheduler expired overdue rows, but a consent could only be created by seeding and withdrawn by an operator. The table had no grantor, purpose or `revoked_at`, so a withdrawal could not record who acted, why the consent existed or when it ended. Caregiver scope came from the Keycloak `patient_id` claim, not from an explicit context selection.

**What changed.** Migration `0007_consent_lifecycle` adds `grantor_subject`, `purpose`, `granted_at` and `revoked_at`; `0009_consent_granted_default` repairs the server default for databases that ran the earlier form of `0007`. `/api/v1/consents` supports a server-paginated grid, grant and revoke; `/api/v1/me/contexts` lists available consents, activates one and clears it; the caregiver's selection travels as `X-Consent-Id` and the server derives the patient from that active consent. `audit_events.consent_id` records the consent that authorized each patient-linked access, and grant/activate/revoke/expiry each write an audit event. The `/care-circle` page grants a caregiver by subject with scope and expiry, lists active/expired/revoked consents, revokes with confirmation, and shows the active-context banner. "Stop using" persists a cleared state instead of silently re-selecting the only consent.

**Verification.** `apps/api/tests/test_consents_integration.py` covers grant, grid scope, activate, cross-patient refusal, revoke and expiry against live Postgres; `./scripts/test.sh --postgres` passes 17 integration tests. The caregiver and patient flows were exercised in the Compose stack, including clearing and re-activating context, and the audit row for each act was inspected.

**Residual.** There is no consent-history view for compliance beyond the audit trail, and row-level security is still G-10. A pre-existing token that carries a `patient_id` claim cannot outlive revocation for a linked read because the server re-checks the active consent, but the claim is still decoded.

### G-34 — Patient data rights (closed)

**What was true.** The original build could upload a document, ask a question and rely on retention, but could not delete a document, download the original, export record metadata or request deletion. Bytes, chunks, embeddings and citations survived until an operator ran retention, so an accidental upload could not be corrected by the patient.

**What changed.** `DELETE /api/v1/records/documents/{id}` removes the object from S3, deletes chunks, scrubs citation references and writes one audit event with object/chunk/citation counts; a storage failure returns `503` and does not delete the database row, so the record never points at missing bytes. `GET /api/v1/records/documents/{id}/download` returns a 300-second presigned GET signed against the public S3 host and audits `records.document_downloaded`. `GET /api/v1/me/export` returns metadata for the patient's documents, appointments, consents, scribe runs, notifications and deletion requests, and names its exclusions (no document text, no chat content, no embeddings). `POST /api/v1/me/deletion-request` soft-deletes and starts the grace period; `DELETE /api/v1/me/deletion-request` cancels it; the worker purges after the configured grace and writes a second audit event with row counts. The `/care-circle` page exposes export and deletion request/cancel to a patient, and the document detail modal exposes download and delete.

**Verification.** `apps/api/tests/test_privacy_integration.py` covers document delete with derived-artifact counts, a cross-patient delete refusal, metadata export, the purge and the presigned download (including `503` when storage is unconfigured). A live export for the demo patient produced a 25,891-byte archive containing three documents and 22 appointments.

**Residual.** There is no orphan scan that compares object keys with document rows, and the purge is exercised in tests rather than on a production schedule. Deletion requests are self-service for a patient; an administrator acts through the same audited route.

### G-35 — Public data estate

**What is true.** All five public sources were downloaded via Kaggle and inventoried with measured `row_count` and `sha256` on 2026-10-31: [public-source-inventory-20261031T165720Z.json](./evidence/public-source-inventory-20261031T165720Z.json) (`status=passed`). Counts: appointments 110527, notes 4999, symptoms 4920, medicines 253973, patients 55500. Seed/sample remains the separate offline demo path. Four sources still carry licence `check_and_record` (human review before redistribution).

**Why it matters.** `FR-DATA-01` / DATA-AC-01 / G2 require the five public sources with exact counts and licences. Inventory closes the count/hash gate; licence attestation is the residual.

**Control.** Inventory evidence committed; contracts updated from the loader; raw files stay gitignored; no invented counts.

**Residual.** Licence review for notes/symptoms/medicines/patients (`check_and_record`). Re-inventory after any re-download.

**Plan.** Complete licence review notes in contracts; keep download+inventory scripts as the refresh path.

### G-36 — Accessibility and browser conformance

**What is true.** Playwright runs on Chromium only (`setup`, `chromium-desktop-light`, `chromium-desktop-dark`, `mobile-360`) with `@axe-core/playwright` checks on covered routes; G-26 records 20/20 passing on 2026-10-25. There is no manual WCAG 2.2 AA audit, no screen-reader or keyboard-only checklist, no skip-to-content/focus-order evidence and no Firefox, WebKit, Edge, iOS Safari or Android Chrome run. The automated axe scan covers rendered states and cannot prove full conformance.

**Why it matters.** `NFR-A11Y-01` requires WCAG 2.2 AA for core flows, `NFR-A11Y-02` requires keyboard operation and screen-reader names, and `NFR-UX-03` requires the latest two versions of Chrome, Edge, Firefox and Safari plus iOS Safari and Android Chrome for patient flows. G-26 closes test automation, not conformance.

**Control.** Automated axe checks catch a class of critical/serious issues; components use semantic elements and labelled icon buttons; the 360 px project exercises the mobile layout; dark/light contrast is checked in the covered screens. The register makes no WCAG or cross-browser claim.

**Residual.** Keyboard traps, focus loss in dialogs, screen-reader announcements for streaming content and Safari-specific behaviour are not covered by an automated Chromium run.

**Plan.** Run a manual WCAG 2.2 AA checklist and a screen-reader pass over sign-in, chat/sources, booking, upload/ask, note review/sign, grids and admin; add Firefox/WebKit Playwright projects and a device matrix; fix and retest findings; link the report here. Keep the axe run in CI (G-37).

### G-37 — CI and release evidence

**What is true.** CI now has eight jobs:

1. **Python** — Ruff check/format, strict mypy, import boundaries, the unit suite, the OpenAPI contract, locale coverage, shell syntax and feature-registry load.
2. **Web** — `npm ci`, typecheck, production build and a blocking `npm audit --omit=dev --audit-level=high`.
3. **Live Postgres** — a `pgvector/pgvector:pg16` service; `alembic upgrade head` on an empty database; a second run to prove idempotence; `pytest -m integration`. The same sequence was executed locally against a fresh `sahyog_ci` database: nine migrations applied from `0001` to `0009`, the second run was a no-op, and 17 integration tests passed.
4. **Compose profiles** — every cumulative profile validates.
5. **Kubernetes manifests** — overlays render and pass kubeconform; the seed component renders.
6. **gitleaks** — secret scan.
7. **Dependency audit** — `pip-audit` over the resolved environment, currently advisory (`continue-on-error`) because several transitive advisories have no compatible fix and others need major upgrades.
8. **AI-collaboration log and PR template** — both files exist and the template requires an entry.

**Why it matters.** Spec §8.4 names these stages and the definition of done requires a reproducible clean-checkout run. The live Postgres job is the first CI stage that proves the migration chain rather than only the Python unit layer.

**Control.** The new gates pass on the committed build. The advisory audit is explicitly not a gate; the repository does not claim that a green build proves dependency safety.

**Residual.** Still absent from CI: Vitest/React Testing Library and coverage, dependency-cruiser, Semgrep for direct provider SDK/tool calls, Trivy/SBOM/signature/licence checks, Playwright/axe, nightly RAGAS/DeepEval, bundle and performance budgets, flag-mutation tests, and a clean-machine acceptance log. `pip-audit` reports: `aiosmtplib 3.0.2` (fix 5.1.2), `filelock 3.32.7` (fix 4.2.1), `langchain 0.3.30`/`langchain-core 0.3.86`/`langchain-openai 0.3.35`/`langchain-text-splitters 0.3.11` and `langgraph*` (fixes are 1.x), `pypdf 5.9.0` (fixes are 6.x), `pytest 8.4.2` (fix 9.0.3), plus `diskcache 5.6.3` and `ragas 0.4.3` with no published fix. The major upgrades are a planned dependency change, not a silent override.

**Plan.** Add the remaining stages in risk order: Semgrep and Trivy first, then coverage/bundle budgets and flag-mutation tests, then Playwright and nightly evals once the runner can host a signed-in stack. Upgrade the Python dependency set, re-run `pip-audit`, and only then make it blocking. Record a clean-checkout release run with every applicable gate. G-37 moves to `Closed` only when that run is linked.

### G-38 — As-built API and UI delta

**What is true.** [architecture.md §7.5](./architecture.md#75-endpoint-catalogue) now treats the regenerated OpenAPI evidence as authoritative (**138 paths / 157 ops**, [openapi-catalogue.md](./evidence/openapi-catalogue.md)) and embeds a family summary; the long §7.5 tables remain a design/target role map. Naming still differs in places (e.g. `/api/v1/auth/me` vs design `/api/v1/me`, `/api/v1/notifications/contacts` vs design `/api/v1/me/contacts`).

**What changed in this pass.** Catalogue regenerated (`scripts/regen_architecture_catalogue.py` → 138 paths / 157 ops). §7.5 links the evidence files as SoT and embeds an as-built family summary. Earlier: consent/context, patient export/deletion, document download/delete, and many chat/admin/FinOps/pharmacy/handoff/incident routes are now on the as-built surface (see evidence catalogue).

**Still residual vs design tables.** Some design paths use different names (`/me` vs `/auth/me`, `/me/contacts` vs `/notifications/contacts`). Keycloak user administration remains an operator script. Preference memory closure is still G-24 (live Mem0). Regen + §7.5 SoT alignment is **not** sufficient to Close: leftovers still require an explicit product out-of-scope mark.

**Why it matters.** A design table read as delivered overstates the product. The contract check validates implemented paths; the evidence catalogue is what clients should trust for path truth.

**Control.** §7.5 labels the long tables as design/target and points to OpenAPI evidence; contract check covers implemented paths; script-only operations stay documented as script-only.

**Plan.** Regenerate the catalogue each release; **Close only when** every design-listed leftover is implemented **or** product-signed out of scope. Until that sign-off, status stays `Mitigated`.

### G-39 — Assistant slot_choice E2E (`FR-W1-08/09/10/17`)

**What is true.** Design §11.2 / §13.3 require tool-backed slots, `slot_picker` / `slot_choice` interrupt, then hold/confirm. W1 can call `search_doctors` and (partially) `get_availability` and rank near a parsed preference ([booking_prefs.py](../apps/api/app/agents/booking_prefs.py)). Chat UI historically offered doctor buttons with `next_slot`; resume booked that first free tick.

**Control.** Front-desk Appointments books discrete 30-minute slots. Chat must not present a full clinic-day window as the booked time.

**Closure.** Interrupt type `slot_choice`, candidates with `starts_at`+label, UI + resume wired, Playwright patient path, linked evidence. Status **Open** until then.

### G-40 — Specialty confidence clarify (`FR-W1-07`)

**What is true.** Specialty match prompts for `confidence` but the graph does not gate; low confidence still shortlists; model failure falls through to `general_medicine`.

**Control.** Reply states “suggested specialty”; cancel is available; no claim that the patient confirmed specialty until clarify exists.

**Closure.** `clarify_below≈0.6`, one clarify, second low-confidence → front desk. **Open**.

### G-41 — Chat booking must use MCP hold/confirm

**What is true.** MCP scheduling exposes `hold_slot` / `confirm_booking`. Chat resume historically wrote via `AppointmentRepository` directly.

**Control.** Desk path uses internal scheduling APIs; agent path must not invent a second write model.

**Closure.** Resume only books through MCP tools with tool provenance. **Open**.

### G-42 — Chat booking notifications (`FR-W1-13`)

**What is true.** Desk confirm calls `_notify_patient`; chat resume did not enqueue channel copies.

**Control.** In-app assistant confirmation remains; channel adapters may be `unconfigured` (G-06).

**Closure.** Same notify/outbox semantics as desk after confirm. **Open**.

### G-43 — Booking idempotency and slot uniqueness (`FR-W1-11/12`)

**What is true.** `idempotency_key` accepted on resume and stored in checkpoint; no durable idempotency table; conflict is application `has_conflict` only.

**Control.** Best-effort conflict check; dual confirmed bookings under race remain possible.

**Closure.** Migration + enforce key; active-slot uniqueness. **Open**.

### G-44 — Red-flag emergency handoff ticket (`FR-W1-04`) — S1

**What is true.** Deterministic red flags fail closed with guidance + audit. Handoffs API exists but chat/W1 does not create emergency tickets or queue notifies.

**Control.** Guidance must not claim a staff callback if ticket creation failed; SLA notify uses `NOTIFY_OPS_SUBJECT`.

**Closure.** Handoff + 2-min SLA + staff notify in-repo. **Mitigated** (Wave F); production MTTA under G-25.

### G-45 — `appointment_help` routing (`FR-CHAT-11`)

**What is true.** Dedicated `AppointmentHelpGraph` lists upcoming appointments and cancels/reschedules via MCP using ordinal (`cancel 1`), doctor name, or UUID; reschedule accepts relative times (`tomorrow 3 pm`).

**Control.** Patients can also manage appointments in the Appointments UI.

**Closure.** Natural-language manage without UUID paste; booking path uses doctor/slot cards + soft-hold countdown. **Mitigated** (v1.15).

### G-46 — Durable LangGraph interrupt

**What is true.** W1 graph calls LangGraph `interrupt()` when a checkpointer is present; chat allocates a run first and passes `thread_id=w1:{run_id}`; resume invokes `Command(resume=…)` then MCP hold/confirm. `chat_runs` remains the product interrupt registry for UI buttons. Soak harness: [scripts/chat-interrupt-ha-soak.sh](../scripts/chat-interrupt-ha-soak.sh).

**Control.** Shared Postgres checkpointer makes cross-replica resume work in principle; registry path continues if graph resume fails.

**Closure.** Attach soak JSON from a dual-API HA env. **Mitigated** (Wave F).

### G-47 — Chat token streaming

**What is true.** `POST /api/v1/chat/sessions/{id}/messages/stream` emits SSE `user` / `token` / `final` / `interrupt` / `error`. PII/intent safety runs before tokens. Conversation/clarify drip tokens; `records_question` / `medication_question` use `W2AskGraph.stream` (retrieve + cite gate, then token drip, then validate — citation failure replaces the draft). Blocked/egress failures persist an assistant notice. Auto-title runs on stream.

**Control.** Booking and emergency paths still emit a single final/interrupt after the full turn.

**Closure.** Measure how often citation validation fails after tokens already dripped. **Mitigated** (UX polish).

### G-48 — Staff escalation / booking source UX

**What is true.** `/escalations` shows priority, SLA countdown/overdue, delivery status, rule IDs; emergency create sets `sla_due_at=+2m` and queues `staff_handoff`; cron + `SahyogHandoffOverdue` alert; `/front-desk` ops console with live open/assigned handoffs and today’s assistant bookings; appointment `source` badge. Runbook: [escalations-handoff.md](./runbooks/escalations-handoff.md).

**Control.** Configure `NOTIFY_OPS_SUBJECT` for live notify; without it tickets still appear with `delivery_status=skipped`.

**Closure.** Production on-call MTTA remains G-25. **Mitigated** (UX polish).

### Policy engines (OPA)

**What is true.** Specs do **not** require Open Policy Agent. R1 authorization is Keycloak JWT/RBAC, consent predicates, repository row scope, MCP tool allowlists, feature flags, and the composite PII egress gate.

**Control.** Do not introduce OPA unless a later ADR names a central policy engine; it would duplicate existing controls without closing a registered gap.

### G-49 — Host Ollama memory / context cap

**What is true.** Host Ollama has been observed with `OLLAMA_CONTEXT_LENGTH=262144` and multi-GiB KV predictions; models.yaml pins `context_window: 8192` for app routes but the daemon default was unbound.

**Control.** Under memory pressure Ollama evicts; local specialty/triage may stall.

**Closure.** Cap daemon context to 8192, `OLLAMA_MAX_LOADED_MODELS=1`, document + script/LaunchAgent; verify RSS. **Open**.

### G-50 — Chat attach → typed Records ingest

**What is true.** Design composer paperclip opens record upload. Records UI/API accept `kind` + file → S3 → ingest → W2 RAG. Chat composer is text-only.

**Control.** User uploads on Records; after index, chat W2 can retrieve.

**Closure.** Chat attach reuses `POST /api/v1/records/documents` (malware scan unchanged). **Open**.

## 4. Traceability

| Gap | Requirements / decisions | Delivery / gate | Evidence |
|---|---|---|---|
| G-01, G-02 | `FR-I18N-01`–`05`, `I18N-AC-01`, `D-10`, Q-14 | WP-05/06/14, G4-R1/G5-R2 | String catalogue, locale screenshots, clinical sign-off |
| G-03, G-04 | `FR-W2`, `FR-I18N`, `FR-OBS-08`, Q-10 | WP-09/14, G5-R2 | [RAGAS language slices](./evidence/eval-ragas-w3-20261025T083908Z.json), [DeepEval language slices](./evidence/eval-deepeval-x01-20261025T095159Z.json), retrieval recall report |
| G-05 | `FR-W3`, `FR-W2-04`, Q-10 | WP-11/13, G4-R2 | [g05-stt-wer-status.md](./evidence/g05-stt-wer-status.md) + [stt-wer-score-aggregate-20261031T170248Z.json](./evidence/stt-wer-score-aggregate-20261031T170248Z.json) (EN WER measured; hi/mr+OCR residual) |
| G-06, G-07 | `FR-PLT-18`, `FR-ADM`, Q-31, D-16 | WP-06/14, G4-R1 | Delivery records, workspace allowlists, opt-in mapping; ARQ contact re-verification job (G-07) |
| G-08, G-09 | Q-11, `FR-PLT`, `FR-DATA-09`, roadmap Y-20 | WP-14, G6 | `/meta` unconfigured status and settings; read adapter, contract test, write-back and ABDM still open |
| G-10 | `FR-AUTH`, `FR-ADM`, MC-07/08/10/12 | WP-02/07/10, G3/G4 | Cross-patient provenance/scope tests, audit events, live Postgres schema/append-only-trigger tests (`apps/api/tests/test_postgres_integration.py`); independent security review, IDOR matrix and audit chaining remain open |
| G-11 | `NFR-AVAIL-01`, Q-30, `ADR-16` | WP-15/17, G4-R3/G6 | K8s render/schema check, cluster smoke, restore drill, RPO/RTO record |
| G-12 | `D-11`, spec §1.3–1.4 | All gates | Disclaimer, safety tests, clinical review |
| G-13 | Roadmap X-01 R3 slice, `X01-R3-AC-01`–`06` | WP-16, G4-R3/G5-R3 | Nursing API + `nursing_x01.jsonl` shape runner; clinical-graded **live** drafts still open |
| G-14 | Roadmap X-03, `ADR-19`, spec §4 R3 | WP-16, G4-R3 | Disabled-by-default flag/`/meta`; `mcp-external` + kill-switch + signed-context conformance tests; quotas/X-03 still open |
| G-15 | `FR-ANL`, `FR-FIN`, ANL-AC-06, MC-31/33 | WP-14/16, G5 | Showback export, model hash, finance variance |
| G-16 | `FR-OBS-08`, MC-25, D-15 | WP-07/15, G5 | [RAGAS report](./evidence/eval-ragas-w3-20261025T083908Z.json), [DeepEval report](./evidence/eval-deepeval-x01-20261025T095159Z.json), [RAGAS judge calibration](./evidence/judge-calibration-20261025T083908Z.json), [DeepEval judge calibration](./evidence/judge-calibration-deepeval-20261025T095159Z.json), per-case failures and per-language slices |
| G-17 | `FR-OPS-15`, MC-18, NFR-SCALE-01 | WP-15/17, G5-R3 | [P-host matched load report](./evidence/load_test_report.md); 1,400 req/h with 4× burst on M/L still open |
| G-18, G-19 | `NFR-PRIV-01`, MC-07/12/24, Q-02/Q-11 | WP-02/10/17, G3/G6 | PII egress tests, secret scan, DPA/security review |
| G-20, G-21 | `FR-I18N`, `FR-ANL`, I18N-AC-01, MC-29/31 | WP-06/14, G5 | Locale QA, suppression tests, analytics privacy check |
| G-22 | `FR-OPS-15`, MC-18 | WP-15, G5/G5-R3 | Abort-path unit proof (`test_load_abort_guard.py`); live approved abort + threshold review still open |
| G-23 | `FR-OBS-01`–`07`, `ADR-15`, `ADR-40` | WP-15, G5-R2/G5-R3 | [Scribe trace](./evidence/langfuse-trace-scribe-20261025.json), [chat trace](./evidence/langfuse-trace-chat-20261025.json): agent spans, null content, usage/token metadata |
| G-24 | `FR-CHAT-12`, `FR-CHAT-21`, `FR-CHAT-22`, `ADR-06` | WP-09/14, G4-R2 | API/UI + `test_memory_preferences.py` unit; live Mem0 Forget/opt-out e2e still open |
| G-25 | `FR-OPS`, `MC-18`, `NFR-AVAIL-01` | WP-15, all gates | Runbook index, `alerts.yml`, Compose Alertmanager, [actual unreachable drill](./evidence/alertmanager-drill-20261031T095704Z.json); live paging/five drills still open |
| G-26 | `FR-UI`, `I18N-AC-01`, MC-31 | WP-06/14, G4/G5 | [Playwright/axe run, 20/20](./evidence/browser-e2e-20261025T095550Z.txt), [summary](./evidence/browser-e2e-20261025T095550Z.json), mobile/theme screenshots |
| G-27 | `NFR-SEC`, `ADR-16` | WP-15, G6 | [image-digests-20261031T124646Z.txt](./evidence/image-digests-20261031T124646Z.txt), [supply-chain-status.md](./evidence/supply-chain-status.md) (advisory continue-on-error) |
| G-28 | `FR-PII-01`–`08`, `NFR-PRIV-01`, MC-07/12/24, Q-03 | WP-02/10, G3/G6 | [mcp-pii-detect-probe.json](./evidence/mcp-pii-detect-probe.json) + [pii-composite-prove-20261031.md](./evidence/pii-composite-prove-20261031.md) (`engine=composite`); [gateway fail-closed egress tests](../apps/api/tests/test_llm_gateway.py); proxy guard and security sign-off before egress still open |
| G-29 | `FR-W2`, `FR-W3`, `FR-GW`, Q-04/Q-10, `ADR-09` | WP-11, G4/G5 | OpenDecider adapter, Whisper WER report, absent-model failure tests |
| G-30 | `FR-ANL-11`, `FR-OBS-08`, `MC-25/31`, `ADR-28` | WP-14/15, G5 | [Job runs, insights and snapshots](./evidence/analytics-jobs-20261025.json); [backup-and-stock.md](./runbooks/backup-and-stock.md) stubs; encrypted backup proof + job-failure alerting still open |
| G-31 | `FR-FIN`, `ANL-AC-06`, `MC-33` | WP-14/16, G5 | [Spend-log reconciliation](./evidence/finops-reconciliation-20261025.json), [post-eval run with populated job detail](./evidence/finops-reconciliation-post-eval-20261025.json); variance alert and finance review still open (G-25/G-15) |
| G-32 | `NFR-SEC`, `FR-REC`, `ADR-16` | WP-10/15, G3/G6 | [Scan verdicts, engine version and audit events](./evidence/malware-scan-20261025.json); EICAR/clean/outage checks recorded |
| G-33 | `FR-PLT-01`–`03`, `FR-AUTH-05`, `FR-CHAT-10`, `PLT-AC-02`, MC-08 | WP-03/06, G3/G4 | [Consent lifecycle migration](../apps/api/migrations/versions/0007_consent_lifecycle.py), [default repair](../apps/api/migrations/versions/0009_consent_granted_default.py), [consent/context tests](../apps/api/tests/test_consents_integration.py); live caregiver/patient care-circle flows |
| G-34 | `FR-W2-13`, `FR-PLT-09`, `MC-28` | WP-04/10, G5 | [Delete, export, purge and presigned-download tests](../apps/api/tests/test_privacy_integration.py); live metadata export (25,891 bytes) |
| G-35 | `FR-DATA-01`–`13`, `DATA-AC-01`, MC-20 | WP-04, G2 | [public-source-inventory-20261031T165720Z.json](./evidence/public-source-inventory-20261031T165720Z.json); licence `check_and_record` residual |
| G-36 | `NFR-A11Y-01/02`, `NFR-UX-03`, `UI-AC-01`–`06`, MC-23 | WP-06/15, G4/G5 | Axe/Playwright evidence (G-26); manual WCAG 2.2 AA, keyboard/screen-reader and cross-browser/device evidence still open |
| G-37 | `MAINT-AC-01`, MC-21/23/26/27/32, spec §8.4 | WP-15/18, G1/G5/G6 | [CI workflow](../.github/workflows/ci.yml), [AI collaboration log](../AI-COLLABORATION.md), [PR template](../.github/pull_request_template.md), local fresh-database migration and 17-test integration run; Semgrep/Trivy/E2E/nightly/coverage/budget/flag-mutation stages and the clean-machine log still open |
| G-38 | `FR-ADM-02`–`07`, `FR-PLT-05/11/12`, `FR-CHAT-08`, `FR-W1-14`, `FR-W3-15`, `FR-W2-08` | WP-03/04/10/11/15, G4/G5 | [openapi-catalogue.md](./evidence/openapi-catalogue.md) (138 paths / 157 ops) + §7.5 SoT; product out-of-scope mark for leftovers still required |
| G-39 | `FR-W1-08/09/10/17/18`, design §11.2/`slot_picker` | WP-08, G3/G4 | Partial W1 `get_availability` + `booking_prefs`; UI/resume `slot_choice` + Playwright still required |
| G-40 | `FR-W1-06/07`, design §13.3 clarify | WP-08 | Confidence unused; clarify interrupt/turn missing |
| G-41 | Arch MCP hold/confirm; design §11.2 book | WP-08 | Resume must call MCP; no direct repo create on agent path |
| G-42 | `FR-W1-13`, `FR-PLT-08/16` | WP-08/14 | Chat resume notify path missing vs desk `_notify_patient` |
| G-43 | `FR-W1-11/12`, arch `booking_idempotency` | WP-08 | Key stored only; uniqueness migration missing |
| G-44 | `FR-W1-04`, `FR-PLT-07/12` | WP-08/10 | Guidance+audit only; no emergency handoff ticket |
| G-45 | `FR-CHAT-11`, design appointment_help | WP-08 | Routed to W1 triage today |
| G-46 | Arch QA-03 / durable interrupt | WP-08/15 | W1 `interrupt()` + `thread_id`; residual multi-replica soak |
| G-47 | `FR-CHAT-07/18`, design streaming | WP-09 | SSE token stream after safety; residual ask-stream |
| G-48 | `FR-W1-14/20`, design staff UX | WP-06/08 | Escalations + front-desk + source badge; residual SLA |
| G-49 | Infra Ollama budget; models.yaml 8192 | WP-11 | Host context historically 262144 |
| G-50 | Design composer paperclip; `FR-W2-01`–`05` | WP-06/09 | Chat paperclip → Records ingest; residual in-thread indexed notice |

**Live-Postgres verification (2026-10-27).** `./scripts/test.sh --postgres` runs `pytest -m integration` in a one-off API container on the `sahyog_data` network. It asserts Postgres 16, the `vector`/`pg_trgm`/`pgcrypto`/`btree_gin` extensions, the core tables, Alembic head `0009_consent_granted_default`, that `audit_events` rejects both `UPDATE` and `DELETE` through its trigger, the consent lifecycle and the export/deletion/purge paths. Seventeen tests pass. The same migration chain was also applied twice to a freshly created `sahyog_ci` database (`0001` → `0009`, then a no-op) and the same 17 tests passed against it, which is the sequence the CI `postgres` job runs. CI itself still does not host Keycloak, MinIO or the MCP services for the integration job; those dependencies remain operator-run.

## 5. Change control

- **Adding a gap:** record it in the same change as the feature reduction; name the owner, severity, interim control and closure trigger. A feature cannot be "temporarily simplified" without a row here.
- **Changing severity:** requires the clinical/security owner for S1/S2 and a note in the decision log.
- **Closing a gap:** link evidence; if the evidence is a test, name the test and the gate; if it is a client decision, link the ADR/decision. Remove the interim control only when the replacement is proven.
- **Accepting a gap at a gate:** a written variance with consequence, residual risk, owner and expiry. Silence is not acceptance (`C-06`).
- **Review cadence:** weekly in delivery, at each gate, and at handover. The known-limitations register in the handover package is generated from this file, not retyped.

## 6. Intentional non-scope (not gaps)

These are not implementation gaps; they are explicit boundaries of R1–R3. Listing them here prevents them being discovered as surprises:

| Item | Why it is out | Where it is handled |
|---|---|---|
| ABDM certification/linking | Requires national certification and a client integration programme | Roadmap Y-20; [architecture.md §12.7](./architecture.md#127-abdm-and-future-identity) |
| FHIR write-back | A clinical write without an integration agreement is unsafe | Roadmap; adapter is read-only |
| Clinical validation / regulatory clearance | Requires a clinical trial/regulatory process, not engineering | G-12; product/clinical owner |
| Production HA/multi-region | A single-site pilot is the current scope; K8s HA manifests are delivered but not proven on the pilot | G-11; [architecture.md §14.7](./architecture.md#147-production-topology-kubernetes-manifests-delivered) |
| Break-glass access | Not available; normal role/consent path only | [plan.md](./plan.md) non-scope; roadmap |
| RLS/full column encryption | Post-pilot hardening; repository predicates and audit now, no field encryption or RLS | G-10 |
| Real patient data / real credentials | Demonstration and synthetic pilot only | `D-11`, `Q-11`, setup safety note |
| Billing/chargeback | Showback only in R1–R3 | G-15; roadmap |
| Native mobile apps, telemedicine, wearables, inpatient ADT | Not in the product scope | Plan non-scope; roadmap |
| Multi-tenant SaaS | Single-tenant deployment per client | Architecture §16.3 |
| Cloud-specific managed services as a hard dependency | Portability requirement | Architecture §16.2 |
