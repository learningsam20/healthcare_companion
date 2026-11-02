# Keycloak outage or admin lockout

| Field | Value |
|---|---|
| Alert | Login failures; auth host 5xx; `keycloak` readiness down; admin cannot sign in |
| Severity | S1 if no named user can authenticate for a clinical workflow; S2 if admin-only |
| Owner | E2 platform + security |
| Last reviewed | 2026-10-25 |

## Symptom

- The web app redirects to the auth host and shows an error, or the callback never completes.
- `/readyz` reports the `keycloak` check down.
- Admin APIs return 401/403 for every user, or no administrator can reach the console.
- Realm/client configuration changed unexpectedly.

## Impact

Every request must authenticate through Keycloak; there is no development bypass. A Keycloak outage stops sign-in for all roles. Already-issued short-lived access tokens may continue until expiry, but no one can refresh or sign in. Do not work around an auth outage by disabling verification, accepting unsigned tokens or using a local fake user.

## First five minutes

1. Check Keycloak and the API readiness:
   ```bash
   curl -fsS http://localhost:5707/realms/sahyog/.well-known/openid-configuration
   curl -fsS http://localhost:5706/readyz | python3 -m json.tool
   ```
2. Check container and logs:
   ```bash
   ./scripts/status.sh
   ./scripts/logs.sh --service keycloak --since 15m --no-follow
   ./scripts/logs.sh --service postgres --since 15m --no-follow
   ```
3. Confirm the DB backing Keycloak is up and the Keycloak database exists. Check disk space and memory.
4. If a config/realm change preceded the outage, freeze changes and record what changed. Do not re-import a realm over a populated one without approval.
5. Verify the Web client redirect URIs match the browser origin. A mismatch produces a login loop, not a Keycloak crash.

## Diagnosis

| Signal | Likely cause | Safe next step |
|---|---|---|
| Keycloak container restarting | DB connection/password mismatch, OOM, bad `KC_*` env | fix config, restart; never point at an empty DB |
| Auth page loads but callback fails | redirect URI/web origin mismatch, wrong client ID, clock skew | correct the client or clock; do not disable PKCE |
| `invalid_grant`/token errors for all users | realm signing key rotated, session expiry, wrong realm | inspect realm keys; restore the prior key/export if approved |
| Admin console inaccessible | bootstrap admin locked or password rotated | use the secret-manager/.env bootstrap credential; do not create a bypass user in the app |
| API reports Keycloak down but browser works | JWKS/network path from API to Keycloak | check in-cluster DNS/service, proxy and network policy |
| K8s `KC_HOSTNAME` wrong | host-based ingress misconfigured | correct `KEYCLOAK_PUBLIC_URL`/ingress; see `deploy/k8s/README.md` |

## Mitigation

- Restart Keycloak:
  ```bash
  ./scripts/restart.sh --service keycloak
  ```
- Fix the failing dependency (Postgres, DNS, ingress) first; Keycloak will not recover on its own if its DB is unavailable.
- **Realm corruption/loss:** import the last encrypted realm export into an empty realm:
  ```bash
  uv run python scripts/keycloak_admin.py import --file <realm-export.json>
  ```
  This overwrites users in that realm; get approval and confirm the target realm first.
- **Admin lockout:** use the bootstrap admin credential from the secret store to restore the admin role. If the credential is lost, follow the secret-rotation procedure with security; do not add an unauthenticated admin endpoint.
- **Ingress/hostname error:** correct the host/route and certificate; keep the app's issuer/audience validation strict.

## Rollback

Kubernetes:

```bash
kubectl -n sahyog rollout undo deployment/keycloak
kubectl -n sahyog rollout status deployment/keycloak
```

Compose: redeploy the last recorded Keycloak image/config and restart. Realm content is data, not code: roll back to a verified export, not to an earlier image alone.

## Evidence to capture

- Outage window, affected roles, environment and image digests.
- Keycloak/API readiness payloads, error codes and event names (no tokens or passwords).
- Realm/client change history and who approved it; redirect URI/host values.
- Restore/import actions and user-impact assessment.
- Confirmation that no auth bypass or token-verification weakening was introduced.

## Escalation

E2 platform first; security for suspected credential compromise, unauthorized admin changes or a lost bootstrap credential; clinical owner if clinicians cannot sign in and patients need a hand-off. If the outage is caused by a suspected intrusion, preserve logs and follow the incident process before restoring service.
