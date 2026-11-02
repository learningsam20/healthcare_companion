# Secret and key rotation

| Field | Value |
|---|---|
| Alert | Scheduled rotation due; suspected secret leak; provider requires key change; failed auth after a rotation |
| Severity | S1 if a key is suspected compromised or a rotation has locked out clinical access; S2 for a planned rotation |
| Owner | Security + E2 platform; E4 for provider keys |
| Last reviewed | 2026-10-25 |

## Symptom

A rotation is due, a provider or security team requires a new credential, or a scan/incident indicates a secret may have leaked. A failed rotation shows as 401/403s, `/readyz` dependency failures, model gateway errors, S3 access errors or login failures. This runbook covers JWT/JWKS, `MCP_CONTEXT_SECRET`, S3 keys, the LiteLLM master key, SMTP/Slack/SMS/FHIR provider keys, Keycloak client/admin secrets and database passwords.

## Impact

Secrets are shared across the API, worker, scheduler, MCP services, LiteLLM, Keycloak and observability. Rotating one side without the other causes an outage; rotating a database password in the Kubernetes Secret without changing it in Postgres locks the application out. There is **no rotation script** and `scripts/keycloak_admin.py` has no rotate subcommand. `scripts/k8s-deploy.sh --create-secret-from-env` only creates `sahyog-secrets`; it refuses to overwrite an existing Secret. Plan each rotation as a change with a validation and rollback step.

## Preconditions

- Named operator and approver; a change window; a current encrypted backup ([restore.md](./restore.md)).
- The previous secret value is available in the vault for rollback; never print values, paste them into tickets, or put them in shell history.
- Rotate one group at a time and validate before starting the next. A suspected leak may require immediate out-of-order rotation; accept a short outage rather than leaving the leaked key valid.
- Know the profile (`minimal`/`core`/`full`) and whether the target is Compose or Kubernetes.

## Rotation order

| Order | Group | Secrets / variables | Why this position |
|---|---|---|---|
| 1 | Provider and channel keys | `OPENROUTER_API_KEY`, `SMTP_PASSWORD`, `SLACK_BOT_TOKEN`, `SMS_API_KEY`, `FHIR_CLIENT_SECRET` | External, low blast radius; validate with synthetic recipients |
| 2 | Object storage application key | `S3_ACCESS_KEY`, `S3_SECRET_KEY` | New key can coexist with the old one during validation |
| 3 | LiteLLM master key | `LITELLM_MASTER_KEY` | Brief model outage; rotate gateway and API together |
| 4 | MCP service/context | `MCP_SERVICE_TOKEN`, `MCP_CONTEXT_SECRET` | Shared HMAC/bearer boundary; no dual-secret support |
| 5 | Keycloak client secrets and signing keys | `KEYCLOAK_*_CLIENT_SECRET`, `KEYCLOAK_ADMIN_PASSWORD`, realm JWKS | Identity; stage signing keys and let caches/tokens expire |
| 6 | Database passwords | `POSTGRES_PASSWORD`, `LITELLM_DB_PASSWORD`, `LANGFUSE_DB_PASSWORD`, `KEYCLOAK_DB_PASSWORD` and their URLs | Highest blast radius; maintenance window and all consumers together |

## Procedure

1. **Provider/channel keys.** Rotate at the provider, update the environment/Secret, then recreate/restart the consumers. In Compose, environment changes require `./scripts/start.sh --profile <profile>`; `./scripts/restart.sh` keeps the old environment. Validate with `curl /api/v1/meta` (adapter `configured`), a synthetic email to Mailpit/a test inbox, a test Slack channel, or an approved synthetic SMS number. Never use a patient contact for validation.
2. **S3 application key.** Create a new application identity with the same bucket policy **before** switching the app. For the local stack, put the new `S3_ACCESS_KEY`/`S3_SECRET_KEY` in the environment and run `docker compose run --rm minio-init`; it creates/attaches the user but does not revoke the old one. Restart `api` and `worker`, upload and retrieve a synthetic PDF, then revoke the old identity. For managed S3, use IAM access-key rotation with an overlap window. Do not rotate `MINIO_ROOT_*` first; the app must not use the root identity.
3. **LiteLLM master key.** Generate the new key, update `LITELLM_MASTER_KEY` for both LiteLLM and the API, and restart `litellm` then `api`. The old key is invalid immediately, so in-flight model calls fail. Validate `/health/liveliness`, `/readyz` and one synthetic chat. Do not put the key in `config/litellm.yaml`.
4. **MCP service token and context secret.** Update `MCP_SERVICE_TOKEN` and `MCP_CONTEXT_SECRET` together across `mcp-broker`, every `mcp-*` service, `api`, `worker` and `litellm` (LiteLLM references `MCP_SERVICE_TOKEN` for its MCP server entry). `MCP_CONTEXT_SECRET` must be at least 32 characters. There is no dual-secret acceptance: in-flight signed contexts (TTL 120 seconds) fail. Restart broker/MCP services first, then API/LiteLLM, and validate a tool-backed action (for example a booking lookup) through the UI.
5. **Keycloak client secrets/admin password.** Change the client credential in Keycloak and the matching `KEYCLOAK_*` value together, then restart the consumers. For the bootstrap admin, change the password in Keycloak and in the Secret, and confirm `uv run python scripts/keycloak_admin.py status` succeeds. For **JWKS/JWT signing**, use the Keycloak admin console: create a new RS256 realm key, set it active, keep the old key passive. The API caches JWKS for 300 seconds and access tokens last 900 seconds; wait at least 20 minutes (plus a rollback window) before removing the old key. No API restart is required, but one can force a JWKS refresh. Validate a real sign-in for at least two roles and `./scripts/smoke.sh --skip-ui`.
6. **Database passwords.** Use a maintenance window with clinical hand-off. Stop writers and consumers first (`api`, `worker`, `scheduler`, plus `litellm`, `keycloak` and `langfuse` when rotating their roles). In `psql`, use the interactive `\password <role>` prompt so the value is not in shell history; rotate `sahyog`, `litellm`, `langfuse` and `keycloak` as applicable. Immediately update `POSTGRES_PASSWORD`, `DATABASE_URL`, `LITELLM_DB_PASSWORD`/`LITELLM_DATABASE_URL`, `LANGFUSE_DB_PASSWORD`/`LANGFUSE_DATABASE_URL` and `KEYCLOAK_DB_PASSWORD` in the environment/Secret, then start every consumer. Never update only the Secret or only Postgres. Validate `/readyz`, `./scripts/smoke.sh --skip-ui` and one login.

For Kubernetes, update `sahyog-secrets` through the secret manager (or a reviewed Secret manifest), then restart the affected Deployments, for example:

```bash
kubectl -n sahyog rollout restart deployment/api deployment/worker deployment/scheduler
kubectl -n sahyog rollout status deployment/api
```

## Validation checklist

- `./scripts/status.sh` and `curl -fsS http://localhost:5706/readyz | python3 -m json.tool` show required dependencies up.
- `./scripts/smoke.sh --skip-ui` passes with real Keycloak auth; no bypass.
- `/api/v1/meta` shows the expected adapters `configured`/`disabled` (never prints secrets).
- A synthetic document upload/index, a model-backed answer, a tool action, and an approved notification each work.
- Logs contain no authentication storm, signature failure or provider 401 after the change.

## Rollback

Restore the previous secret version and recreate/restart the same consumers; for a database password, restore the old password in Postgres and the matching URL/Secret together. For JWKS, re-activate the old key while it is still present. For S3, re-enable the old identity. Never leave both old and new values valid longer than the validation/rollback window. If the rotation was triggered by a leak, do not roll back to the leaked value; fix forward and escalate.

## Evidence to capture

- Secret **names** and versions/timestamps, never values; operator, approver and change reference.
- Validation outputs (health, smoke, adapter status, synthetic send) with identifiers redacted.
- Any outage/auth failures, duration and affected roles.
- Which consumers were restarted and when; confirmation that old keys were revoked after the rollback window.
- For a suspected leak: discovery time/source, exposure scope, security incident ID and notification decision.

## Drill

A non-production rotation of the provider keys, S3 key, LiteLLM key, MCP secret and one database role is required before the first production rotation; a JWKS/DB tabletop is required with security and E2. **No rotation drill record exists yet.** Record date, environment, group order, timings, failures and fixes.

## Escalation

Security owns compromise decisions and disclosure; E2 owns platform secrets and databases; E4 owns provider portals; the clinical owner is notified when a rotation interrupts sign-in or clinical workflows. If a key may have leaked, preserve provider/egress logs, rotate immediately, and follow [incident-response.md](./incident-response.md).
