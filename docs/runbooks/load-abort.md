# Load-test abort or suspected real-user impact

| Field | Value |
|---|---|
| Alert | Load guard trip (`real_users_detected`, `budget_guard`, `real_user_p95`, `real_user_error`, `guard_unavailable`) or real-user SLO breach during a synthetic run |
| Severity | S1 if real users are affected or the approval/guard is missing |
| Owner | E2 on-call + load-test operator |
| Last reviewed | 2026-10-25 |

## Symptom

The load generator aborts, reports a guard failure, or the real-user p95/error rate breaches its threshold during a run. Operators may also notice real users reporting slow or failed requests while a capacity test is in progress.

## Impact

A load run shares the host and the model gateway with real users. A guard trip is a safety stop, not a benchmark failure to retry with guards off. Continuing can degrade a clinical workflow, exhaust the model budget or send notifications to the wrong people. The loadtest cohort is authenticated through Keycloak; there is no dev bypass and no direct database write.

## First five minutes

1. **Stop the run first.** Interrupt the terminal (`Ctrl-C`) or stop the generator:
   ```bash
   docker compose stop loadgen
   ```
   Do not restart it until the cause is understood.
2. Confirm real-user impact:
   ```bash
   ./scripts/status.sh
   curl -fsS http://localhost:5706/api/v1/analytics/load-guard | python3 -m json.tool
   ```
3. Check the load report and abort reason. The summary path defaults to the run's evidence file; read the reason and the sampled real-user metrics.
4. Check the API/worker/LiteLLM logs for errors and saturation, and host CPU/memory:
   ```bash
   ./scripts/logs.sh --service api --since 15m --no-follow
   ./scripts/logs.sh --service litellm --since 15m --no-follow
   docker stats --no-stream
   ```
5. If real users are affected, notify the clinical/operations owner and record the window. Stop the whole stack only if patients cannot be served safely; otherwise keep the UI up and disable the synthetic traffic.

## Diagnosis

| Abort reason | Meaning | Action |
|---|---|---|
| `real_users_detected` | Real events observed but the run was not approved for coexistence | Stop; obtain approval and a dedicated cohort/window before retrying |
| `real_user_p95` / `real_user_error` | Real-user latency/error guard breached | Stop; restore headroom; review thresholds and host capacity |
| `budget_guard` | Synthetic model cost exceeded the configured budget | Stop; reconcile LiteLLM spend; do not raise the budget to finish a run |
| `guard_unavailable` | The guard endpoint/Prometheus could not be read | Fail closed; fix observability before any further run |
| No guard trip but users report impact | Guard thresholds too loose or traffic not classified | Stop; treat as an incident; review classification and thresholds |

Never disable `--abort-on-real-slo`, set `LOAD_TEST_ALLOW_REAL_USERS=false` while real users are active, or re-run with a larger budget to "prove" capacity. A synthetic run excluded from showback is not a real-user cost exemption.

## Mitigation

- Allow the host to drain; confirm p95/error rates return to baseline before resuming normal work.
- If model capacity is the bottleneck, reduce concurrency/rate and re-plan the profile; do not change model aliases in a way that sends identified text externally.
- If notifications or bookings were created by the load cohort, use `--reset-test-data` only for tagged loadtest records; never delete real user data. Check the notification outbox and delivery records for test recipients.
- Record the guard thresholds, sampled real-user metrics and the exact abort time in the incident log.

## Rollback

There is no code rollback for a load run. Rollback is operational: stop the generator, verify real-user SLOs, and if the stack was degraded, restart affected services:

```bash
./scripts/restart.sh --service api
./scripts/restart.sh --service worker
```

If a deployment caused the degradation, use the K8s rollout undo procedure in [api-unavailable.md](./api-unavailable.md).

## Evidence to capture

- Run ID/profile, approval reference, `LOAD_TEST_ALLOW_REAL_USERS` and guard configuration.
- Abort reason, timestamps, real-user p95/error samples and thresholds.
- Synthetic vs real traffic split, budget spend and LiteLLM reconciliation.
- Host saturation and affected endpoints; any patient-facing impact and hand-off.
- Decision on retry, including any threshold change and approver.

## Escalation

E2 on-call owns containment. Clinical/operations owner is notified when real users are affected. Security/compliance is notified if the run used an unapproved window or if test notifications reached real recipients. A deliberate abort test is required evidence for G-22 before R3 acceptance.
