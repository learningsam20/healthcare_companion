# Alertmanager local drill record (G-25)

| Field | Value |
|---|---|
| Date (UTC) | 2026-10-31 |
| Environment | local Compose `full` profile (or prometheus+alertmanager only) |
| Tester | engineering (scaffold drill) |
| Alertmanager | `docker/alertmanager/alertmanager.yml` → local webhook |
| Prometheus rules | `docker/prometheus/alerts.yml` with `runbook_url` |

## Procedure executed

1. Confirmed `rule_files` and `alerting.alertmanagers` in `docker/prometheus/prometheus.yml`.
2. Confirmed Alertmanager service defined in `docker-compose.yml` (port 5736).
3. Mapped alerts → runbooks:
   - `SahyogApiDown` → `docs/runbooks/observability.md`
   - `SahyogLiteLlmHighErrorRate` → `docs/runbooks/model-gateway.md`
   - `SahyogMcpBrokerUnhealthy` → `docs/runbooks/mcp.md`
   - `SahyogExternalEgressWithoutCompositePii` → `docs/runbooks/pii-egress.md`

## Result

- **Scaffold drill:** configuration and runbook linkage verified in-repo.
- **Not claimed:** production paging, on-call acknowledgement, or measured MTTA.
- Residual: replace webhook with Slack/email; record a live fire→ack→resolve for the top five alerts before production gate.

## Closure note

G-25 remains **Mitigated** until a live fire drill with on-call ack is attached. This file is configuration evidence, not a production drill.
