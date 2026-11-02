# Gaps that cannot close in-repo without external owners

These remain **Mitigated**, **Open**, or **Deferred** by design until the named evidence exists.
Do not mark them Closed from scaffolding alone.

| ID | Blocker | Owner evidence required |
|---|---|---|
| G-01 / G-02 | Clinical hi/mr safety copy sign-off | Named clinical reviewer signature |
| G-05 | hi/mr + clinical speech WER; Devanagari OCR CER | EN public LibriSpeech WER measured (`mean=0.0`); residual multilingual/OCR |
| G-06 | ~~Email/Slack staff~~ proven for pilot; **SMS optional** | SMS DLT/provider only if enabling `notifications_sms` |
| G-07 | 100% verified Slack coverage for opted-in patients | Ops coverage evidence (job alone insufficient) |
| G-09 | National ABDM certification | NHA programme / sandbox credentials |
| G-10 | Live IDOR matrix + RLS/encryption/break-glass | Security review; live red-team may be re-run when stack is quiet |
| G-11 | Cluster restore drill with RPO/RTO | Encrypted backup proven (G-30); full empty-env restore still operator-run |
| G-12 | Medical-device clinical validation / regulatory clearance | Product attestation gate is in-repo; CDSCO/FDA/MDR clearance remains out of demo scope (D-11) |
| G-13 | Clinical-graded X-01 live drafts | Live draft probe [nursing-x01-probe-20261031T181116Z.json](./nursing-x01-probe-20261031T181116Z.json); need 20 attested clinician grades |
| G-14 | Partner productisation / named consumer | Quotas, versioning, X-03 consumer onboarding |
| G-15 | FinOps operating history | 8–12 weeks usage + finance approval |
| G-16 | Human judge κ ≥ 0.6 | Attested human grades file |
| G-17 | M/L capacity_accepted | Load evidence on M/L host; P-host + kill drill recorded |
| G-19 | Signed DPDP/subprocessor DPA; egress security sign-off | Signed DPA + security approval before enabling egress |
| G-22 | Production-window threshold review | Kill drill recorded; residual on-call sign-off |
| G-24 | Settings provenance UI confirmation vs live Mem0 | API put/purge e2e [mem0-forget-e2e-20261031T180949Z.json](./mem0-forget-e2e-20261031T180949Z.json) (`closes_gap:false`) |
| G-25 | Production MTTA SLO | Email/Slack staff + 2‑min SLA ship; MTTA still needs ops rota evidence ([mtta-and-paging.md](../runbooks/mtta-and-paging.md)) |
| G-30 | ~~Encrypted backup~~ proven | [encrypted-backup-20261031T174501Z.json](./encrypted-backup-20261031T174501Z.json); residual: scheduled `BACKUP_OUT_DIR` in Compose |
| G-35 | ~~Five public sources inventoried~~ **Closed** | Inventory linked; residual human licence review for 4× `check_and_record` |
| G-36 | Signed WCAG 2.2 AA | QA + SR pass report |
| G-38 | Design-table leftovers out of scope | Product sign-off |

**In-repo advances (still Mitigated where noted):** G-03 live recall@k, G-08 FHIR SPA, G-31 FinOps variance alert rule + metric, G-25 Mailpit demo paging, G-30 encrypted backup + job metrics.

**G-28 is not an external blocker.** Composite runtime is proven; residual egress sign-off remains under **G-19**.

Demo interim controls stay in `docs/gaps.md`. Seed/sample data remains the only offline synthetic path (FR-DATA-12).
