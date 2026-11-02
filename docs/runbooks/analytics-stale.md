# Analytics stale or insight job failure

| Field | Value |
|---|---|
| Alert | Dashboard `as_of` is old; snapshot missing/failed; insight expected but absent; analytics API error |
| Severity | S2 (S1 if a safety/compliance decision is being made from stale numbers) |
| Owner | Analytics + E2 platform |
| Last reviewed | 2026-10-25 |

## Symptom

- The analytics page shows an old `as_of`, a `not_configured`/`unknown` tile, or an error.
- A captured snapshot in `docs/evidence/analytics-snapshot-*.json` is older than the reporting window.
- `/api/v1/analytics/insights` is empty or returns an error when an operator expected recommendations.
- `./scripts/analytics-refresh.sh --live` fails or writes no file.

## Impact

This build computes analytics **at request time**; there is no scheduled snapshot job and no model-generated insight job. The `ANALYTICS_REFRESH_CRON` and `INSIGHTS_SCHEDULE_CRON` values in `.env` are not consumed by the scheduler. A live API response is current only for its own request; a saved snapshot is a frozen copy. `/analytics/insights` is deterministic rules with `ai_generated: false`, not a job. The UI shows `as_of`, a status badge and notes, and renders `—` for a null value; it has **no automatic stale banner**. When data is unavailable, show the last known snapshot with its timestamp and an explicit stale label — never replace it with zero.

## First five minutes

1. Confirm API/analytics availability:
   ```bash
   ./scripts/status.sh
   ./scripts/logs.sh --service api --since 15m --no-follow
   ```
2. Check the analytics feature flag and API:
   ```bash
   ./scripts/flags.sh --json
   curl -fsS http://localhost:5706/readyz | python3 -m json.tool
   ```
3. Capture a fresh manual snapshot (this is the only supported refresh):
   ```bash
   ./scripts/analytics-refresh.sh --days 30 --live --out docs/evidence/analytics-snapshot-<timestamp>.json
   ```
   The script authenticates through the real CLI Keycloak client, calls every analytics section, and aborts without writing if a section fails.
4. Compare the newest snapshot's `generated_at`, `window_days` and each section's `status` with the page's `as_of`.
5. If a deploy/config change preceded the failure, freeze it and record the digest; do not invent a rollup or backfill rows.

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| HTTP 403 `feature_disabled` | `analytics_dashboard` is off | enable it in Governance with admin approval; runtime change applies to the API process only |
| HTTP 503 `database_unavailable` | Postgres/read model unavailable | follow [api-unavailable.md](./api-unavailable.md); keep the last snapshot visible and stale-labelled |
| Snapshot script exits non-zero | auth/CLI secret, API or one analytics section failed | fix auth/API; no snapshot is written; retain the previous file |
| `reconciliation.status: partial` | unmatched app or gateway calls remain (for example direct embedding traffic) | keep spend labelled as partially reconciled; do not claim billing-grade |
| `reconciliation.status: insufficient_data` | no reconciliation row inside the freshness window | run the scheduled job or `finops.reconcile`; label spend as unreconciled |
| `audit_chain` tile `not_configured` | hash chaining is not implemented | do not present it as a passing chain check; see [audit-chain-failure.md](./audit-chain-failure.md) |
| Insights empty | deterministic rules produced no item | not a job failure; inspect the selected window and rule evidence |
| Insights endpoint errors | API/DB failure | fix the API; do not generate insights by hand |
| Page `as_of` current but numbers look wrong | source-table counts changed or the window is wrong | validate counts and the requested `days`; do not edit source rows |

The UI's `as_of` is the end of the requested window, not a guarantee that every source was refreshed at that moment. The snapshot file's `generated_at` is the capture time. Use both when judging staleness.

## Mitigation

- **Refresh evidence:** run the `--live` command above; store the file with its hash and the operator/time in the incident record.
- **API unavailable:** keep the last successful snapshot as the display/evidence source, mark it stale with its `generated_at`, and state that live recomputation is blocked. Do not publish zeros or "no activity" when the query failed.
- **Feature disabled:** enable `analytics_dashboard` in Governance (admin, audited) or change configuration and redeploy. Do not bypass role checks or query patient rows to build a private dashboard.
- **Insight expectations:** explain that insights are advisory deterministic rules, not a scheduled AI job. If a model-generated insight is required, record it as an unmet requirement rather than fabricating one.
- **Suspected source data problem:** compare aggregate counts only; escalate to the owning module. Never "fix" analytics by editing usage, audit, consent or clinical rows.
- **Stale decision risk:** if a clinical/compliance decision depends on the number, stop the decision until a fresh snapshot is captured and reviewed.

## Rollback

Revert a flag/config change and restore the prior value:

```bash
# Governance UI: set analytics_dashboard back to its previous value (audited)
kubectl -n sahyog rollout undo deployment/api   # only if a deploy caused the failure
kubectl -n sahyog rollout status deployment/api
```

Snapshot files are evidence: do not overwrite or delete an older snapshot to hide a gap. Write a new file with a new timestamp.

## Evidence to capture

- Page `as_of`, snapshot `generated_at`, window/days, section statuses and file hash.
- API/flag/readiness output and error codes; no patient rows or prompts.
- Whether the number was used in a clinical/compliance decision and who was told it was stale.
- The exact refresh command, operator, timestamp and result.
- Any `not_configured`/`unavailable` note shown to users (audit chain, reconciliation, incident register).

## Escalation

Analytics owns metric definitions and snapshots; E2 owns the API/database. The clinical owner is notified if a safety metric is stale and being used for care; compliance is notified if audit/consent/retention evidence is affected. Do not claim a scheduled refresh or AI insight job exists.
