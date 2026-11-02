# Operations runbooks

This directory holds the procedures an on-call operator follows when an alert fires. They are written for the delivered Compose stack and the Kubernetes overlays in [`deploy/k8s`](../../deploy/k8s). Commands assume the repository root and a loaded `.env`; never paste patient data, tokens or secrets into a ticket, chat or shell history.

Every runbook follows the same shape: **symptom → impact → first five minutes → diagnosis → mitigation → rollback → evidence → owner**. The operator records timestamps and command output with identifiers redacted.

## Index

| Alert / symptom | Runbook |
|---|---|
| API unavailable, `/readyz` failing, dependency down | [api-unavailable.md](./api-unavailable.md) |
| PII detector unavailable, egress gate failing closed or a block storm | [pii-gate-failure.md](./pii-gate-failure.md) |
| Data loss, corruption or a restore drill | [restore.md](./restore.md) |
| Keycloak outage, login failure or admin lockout | [keycloak-outage.md](./keycloak-outage.md) |
| Load-test guard trip or suspected real-user impact | [load-abort.md](./load-abort.md) |
| Model gateway/provider outage, circuit open, local fallback, blocked egress | [model-outage.md](./model-outage.md) |
| Audit insert/trigger failure, chain mismatch or suspected tampering | [audit-chain-failure.md](./audit-chain-failure.md) |
| Redis/ARQ backlog, stuck ingestion or notification outbox | [queue-backlog.md](./queue-backlog.md) |
| LiteLLM budget hard stop, cost spike or reconciliation variance | [budget-cost-anomaly.md](./budget-cost-anomaly.md) |
| Analytics snapshot stale/failed or insight job failure | [analytics-stale.md](./analytics-stale.md) |
| JWT/JWKS, MCP, S3, LiteLLM, SMTP/Slack/SMS or database credential rotation | [key-rotation.md](./key-rotation.md) |
| S1/S2/S3 incident, safety stop-the-line, containment, client notification | [incident-response.md](./incident-response.md) |
| Wrong recipient/channel, consent or opt-in failure, unverified contact, Slack workspace mismatch | [notification-misdelivery.md](./notification-misdelivery.md) |
| Stale/corrupt scribe run or draft, blocked signing | [checkpoint-corruption.md](./checkpoint-corruption.md) |
| OCR/STT unavailable, malformed document, manual transcript fallback | [ingestion-ocr-failure.md](./ingestion-ocr-failure.md) |
| Failed/unconfigured scheduled backup or pharmacy stock drop import | [backup-and-stock.md](./backup-and-stock.md) |
| External MCP listener kill switch, quota/version behaviour, Compose vs Kubernetes presence | [mcp-external.md](./mcp-external.md) |

## Alert linkage

**No alert rule in this deployment is linked to a runbook, and no automatic alert-to-runbook routing exists.**

- [`docker/prometheus/prometheus.yml`](../../docker/prometheus/prometheus.yml) and [`deploy/k8s/components/observability/config/prometheus.yml`](../../deploy/k8s/components/observability/config/prometheus.yml) contain scrape configs only. There is no `rule_files`, no `alerting` block and no Alertmanager service in Compose or Kubernetes.
- Grafana is provisioned with a Prometheus datasource; no Grafana alert rules are provisioned.
- API `/healthz`/`/readyz`, `/api/v1/meta`, LiteLLM/Keycloak/MCP-broker metrics and `./scripts/status.sh` are human-visible signals. They do not page anyone and do not execute a runbook.
- The only automated guards are in [`scripts/load_test.sh`](../../scripts/load_test.sh) (`--abort-on-real-slo` and the budget guard) and the optional in-app `delivery_failure` notice sent when `NOTIFY_OPS_SUBJECT` is set. Neither is a Prometheus/Alertmanager alert.
- The wider alert catalogue in the architecture is a target design, not an implemented alerting stack. Do not tell a client or reviewer that these alerts fire.

To complete the linkage, define Prometheus rules (or an equivalent) for each symptom above, route them to Alertmanager and the on-call rotation, add a `runbook_url` annotation pointing at the matching file, and test each rule with a synthetic condition. Until that exists, on-call must select the runbook from this index manually.

## Drill record

**No drill record exists yet. No runbook in this directory has been exercised as a recorded drill.** `docs/evidence/` now contains analytics, FinOps, trace, evaluation and malware-scan outputs in addition to load-test results, but none of them is a drill record. Until a drill is recorded, these documents are procedures only; do not claim they are tested or validated.

The G-25 production gate requires the top five safety runbooks to be drilled. The proposed top-five set and the additional key-rotation drill are:

| Runbook | Required drill | Status |
|---|---|---|
| [restore.md](./restore.md) | Restore from an encrypted backup into a clean environment; verify smoke checks and row counts | Not performed; no record |
| [pii-gate-failure.md](./pii-gate-failure.md) | Stop the detector or force a block storm; verify fail-closed, local fallback and no external egress | Not performed; no record |
| [audit-chain-failure.md](./audit-chain-failure.md) | Simulate an audit insert/trigger failure; stop clinical writes, preserve/export evidence, make no row repair | Not performed; no record |
| [notification-misdelivery.md](./notification-misdelivery.md) | Synthetic wrong-recipient matrix and stop-worker containment; confirm recall limits | Not performed; no record |
| [incident-response.md](./incident-response.md) | S1 tabletop covering clinical/security escalation, evidence and client notification | Not performed; no record |
| [key-rotation.md](./key-rotation.md) | Rotate a staging credential end-to-end in the documented order, validate and roll back | Not performed; no record |

A drill record must name the runbook and version, date, environment, facilitator and participants, scenario, observed timings, pass/fail, defects, and follow-up owner/date. A tabletop is acceptable only where the runbook says so; a restore, rotation or containment step must be executed in a non-production environment with synthetic data. Do not record a drill as passed until the evidence and follow-ups are attached.

## Common commands

```bash
./scripts/status.sh                 # containers, endpoints and health probes
./scripts/logs.sh --service api --since 15m
./scripts/restart.sh --service api
./scripts/stop.sh                   # stop the active profile
./scripts/stop.sh --service worker  # contain notification dispatch
./scripts/start.sh --profile core   # start after a controlled stop (Compose app tier)
./scripts/start.sh --profile core --local  # host API/UI/workers; deps stay in Docker
./scripts/dev.sh --profile core     # same host-app mode once deps are up
./scripts/smoke.sh --skip-ui        # API/auth/chat/grid checks against a running stack
```

Kubernetes:

```bash
./scripts/k8s-status.sh --namespace sahyog
kubectl -n sahyog rollout status deployment/api
kubectl -n sahyog logs deployment/api --since=15m
kubectl -n sahyog rollout undo deployment/api   # only after recording the current image
```

## Evidence and escalation

- Record the alert name, start time, affected environment, release/image digests and the commands run.
- Redact names, contacts, patient IDs, tokens and message bodies. Use counts and request/trace IDs only.
- A safety alert (red flag, consent/scope, PII egress, signature, audit chain) is a stop-the-line event: contain first, then escalate to the clinical/security owner. Do not trade safety for availability.
- Use [incident-response.md](./incident-response.md) for severity, containment, escalation, client notification and post-incident review.
