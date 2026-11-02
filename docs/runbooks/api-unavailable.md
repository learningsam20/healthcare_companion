# API or dependency unavailable

| Field | Value |
|---|---|
| Alert | API 5xx/latency spike; `/readyz` 503; container unhealthy |
| Severity | S2 (S1 if clinical writes are affected and no human hand-off is available) |
| Owner | E2 platform, with E1 for model/agent behaviour |
| Last reviewed | 2026-10-25 |

## Symptom

The web app loads but API calls fail, a role cannot sign in to a workflow, or the API container is restarting. `/readyz` returns 503 or marks Postgres, Redis, Keycloak, LiteLLM or the MCP broker `down`. The scheduler or worker may be failing at the same time.

## Impact

Chat, records, booking, scribe and analytics may be unavailable. Safety rules run in the API before models, so an API outage stops clinical workflows; there is no bypass path. The UI must show an error/degraded state, not stale success.

## First five minutes

1. Confirm scope and start time: `./scripts/status.sh`.
2. Capture readiness (no content): `curl -fsS http://localhost:5706/readyz | python3 -m json.tool`.
3. Read the last 15 minutes of API and dependency logs:
   ```bash
   ./scripts/logs.sh --service api --since 15m --no-follow
   ./scripts/logs.sh --service postgres --since 15m --no-follow
   ./scripts/logs.sh --service litellm --since 15m --no-follow
   ```
4. Check host pressure (disk full, OOM, swap): `docker stats --no-stream`, `df -h`, `vm_stat` on macOS.
5. If the outage started after a deploy or config change, record the image tag/digest and stop further changes. Do not restart repeatedly without a hypothesis.

## Diagnosis

| Check | Command | Interpretation |
|---|---|---|
| Postgres | `curl -fsS http://localhost:5706/readyz` (`postgres` entry) | `down` → DB unreachable, migrations failed or pool exhausted |
| Redis | same payload | `down` → queue/SSE buffers unavailable; API may still refuse readiness |
| Keycloak | `curl -fsS http://localhost:5707/realms/sahyog/.well-known/openid-configuration` | failure → auth outage; follow [keycloak-outage.md](./keycloak-outage.md) |
| LiteLLM | `curl -fsS http://localhost:5708/health/liveliness` | failure → model calls fail; fallback aliases may still work |
| MCP broker | `curl -fsS http://localhost:5709/healthz` | failure → tools unavailable; chat must refuse grounded actions |
| PII gate (core/full) | `curl -fsS http://localhost:5715/healthz` | failure → external egress must fail closed; see [pii-gate-failure.md](./pii-gate-failure.md) |
| Disk/DB | `du -sh` on volumes; `psql` connection count if safe | full disk or `max_connections` explains cascading 5xx |

Do not query clinical tables or print request bodies while diagnosing. Use counts, status codes and event names.

## Mitigation

- **Single dependency down:** restart that dependency, not the entire stack:
  ```bash
  ./scripts/restart.sh --service litellm   # or postgres, redis, keycloak, mcp-broker
  ```
- **API-only failure after a config/prompt change:** revert the change, restart `api`, re-check `/readyz`.
- **Database unavailable:** stop writers (`./scripts/stop.sh` or scale API/worker to zero in K8s), preserve the volume, and follow [restore.md](./restore.md) only if corruption is confirmed.
- **Model provider outage:** keep the API up; switch the purpose alias to the configured local fallback if the clinical/quality owner approves. Identified W3 text must stay local.
- **MCP partition:** fail closed for tools and grounded answers; do not let the model invent a tool result.

## Rollback

Kubernetes keeps the previous ReplicaSet:

```bash
kubectl -n sahyog rollout undo deployment/api
kubectl -n sahyog rollout status deployment/api
```

Compose does not keep an automatic previous image. Re-deploy the last recorded image tag with the same `.env` and config, then run `./scripts/smoke.sh --skip-ui`. A config rollback is a git revert plus restart; never hand-edit a running container.

## Evidence to capture

- Alert name, start/end timestamps, environment, release and image digests.
- `/readyz` payload before and after mitigation (no secrets).
- Redacted log excerpts showing the failing dependency and the first error.
- Actions taken, including who approved any alias/fallback change.
- Post-incident: whether a runbook was missing and which gap it maps to.

## Escalation

E2 platform on-call first. Escalate to E1 if the failure involves agent behaviour, model routing or retrieval; to security if the cause is suspected unauthorized access or a leaked credential; to the clinical owner if a workflow is unavailable and a patient needs a human hand-off. Never enable a development auth bypass or skip PII checks to restore service.
