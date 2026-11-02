# Kubernetes deployment

This directory is the Kubernetes reference deployment for Sahyog Care
Companion. It mirrors the Compose services and keeps the same in-cluster
service names, so application defaults (`http://api:8000`,
`http://litellm:4000`, `http://mcp-broker:8100`, `http://postgres:5432`) work
without a second configuration dialect.

Kustomize is the only tool required. There is no Helm chart and no kind
dependency.

## Layout

| Path | Purpose |
|---|---|
| `base/` | Namespace, workloads, data services, identity, gateway, MCP, migration and bootstrap Jobs, HPAs, default-deny ingress policies |
| `base/config/` | Copies of shared configs consumed by Kustomize generators; `scripts/k8s-deploy.sh` fails if a copy drifts from its source |
| `components/observability/` | Langfuse, OTel collector, Prometheus, Grafana, ClamAV and Squid proxy |
| `components/local-model/` | Ollama StatefulSet for local drafting and embeddings |
| `components/seed/` | Opt-in demo data Job; never part of an overlay |
| `overlays/pilot/` | Single-site, one replica per workload, Mailpit included |
| `overlays/production/` | Two-replica API/worker/web/broker, PDBs, topology spread, HPA bounds, Mailpit removed |
| `overlays/ha/` | Production overlay plus required shared graph-checkpointer settings |

The `pilot` overlay does **not** claim high availability. The `production`
overlay is a production-shaped reference, not proof of HA: it still uses a
single Postgres, Redis, MinIO and Keycloak instance and does not include a
cross-region DR exercise.

## App-tier HA overlay

The `ha` overlay enables `HA_MODE=true` and `CHECKPOINTER_REQUIRED=true`, so API
readiness fails when the shared Postgres graph checkpointer is unavailable.
Run `./scripts/k8s-ha-smoke.sh` to render the overlay and, when installed, run
`kubeconform`. The generated JSON is manifest evidence only and does not claim a
failover exercise or HA certification.

App multi-replica + shared Postgres checkpointer; data plane still single
Postgres/Redis/MinIO — not multi-region HA.

## Prerequisites

- Kubernetes 1.29+ with `kubectl` 1.30+ (validated authoring environment:
  `kubectl v1.36.1`, Kustomize v5.8.1).
- An ingress controller. The manifests assume ingress-nginx in the
  `ingress-nginx` namespace; network policies select that namespace by its
  automatic `kubernetes.io/metadata.name` label.
- A default StorageClass that supports `ReadWriteOnce`.
- DNS and a TLS certificate for three hostnames:
  - `care.example.invalid` — web and `/api`
  - `auth.care.example.invalid` — Keycloak
  - `storage.care.example.invalid` — MinIO presigned uploads

  These are placeholders. Replace them in `base/configmap.yaml`,
  `base/keycloak.yaml` (it reads `KEYCLOAK_PUBLIC_URL` from the ConfigMap) and
  the overlay `ingress.yaml` files. Build the web image with the matching
  `AUTH_ORIGIN` or the CSP will block the Keycloak iframe.
- An image registry the cluster can pull from.

### Why Keycloak has its own host

The SPA owns `/auth/callback`. A path-prefixed Keycloak ingress (`/auth`) would
shadow that route and break the OIDC redirect and CSP `frame-src`. Host-based
routing avoids the collision and keeps the Keycloak issuer stable.

## Build and push images

```bash
REGISTRY=registry.example.invalid/sahyog
VERSION=0.1.0

docker build -f docker/api.Dockerfile -t "$REGISTRY-api:$VERSION" .
docker build \
  -f docker/web.Dockerfile \
  --build-arg VITE_API_BASE_URL= \
  --build-arg VITE_OIDC_AUTHORITY=https://auth.care.example.invalid/realms/sahyog \
  --build-arg VITE_OIDC_CLIENT_ID=sahyog-web \
  --build-arg VITE_OIDC_REDIRECT_URI=https://care.example.invalid/auth/callback \
  --build-arg VITE_OIDC_POST_LOGOUT_REDIRECT_URI=https://care.example.invalid/ \
  --build-arg VITE_APP_ENV=production \
  --build-arg AUTH_ORIGIN=https://auth.care.example.invalid \
  -t "$REGISTRY-web:$VERSION" .
docker push "$REGISTRY-api:$VERSION"
docker push "$REGISTRY-web:$VERSION"
```

An empty `VITE_API_BASE_URL` makes the SPA call its own origin; ingress routes
`/api` to the API Service. If you change the hosts, the web build args and the
Keycloak redirect overrides in `base/configmap.yaml` must change together:
`KEYCLOAK_WEB_ROOT_URL`, `KEYCLOAK_WEB_REDIRECT_URIS` and
`KEYCLOAK_WEB_ORIGINS` replace the localhost values baked into the realm
template.

`docker/web.Dockerfile` uses `nginxinc/nginx-unprivileged` and listens on 8080;
the web Service maps port 80 to 8080. The pod runs as UID 101 with a read-only
root filesystem.

In production, pass immutable digests to the deploy script:
`--api-image repo@sha256:... --web-image repo@sha256:...`.

## Secret

The manifests reference `sahyog-secrets` but never contain it. Create it from
`.env` (only if absent) or from your secret manager:

```bash
./scripts/k8s-deploy.sh --overlay pilot --create-secret-from-env --confirm
```

The script refuses to overwrite an existing Secret. Rotating a database
password in the Secret without rotating it in Postgres would lock the
application out, so rotation is deliberately a separate, manual operation.

`base/secret.example.yaml` documents every key. It is not a Kustomize resource
and must never be applied with real placeholders.

The application containers list `sahyog-secrets` first and `sahyog-config`
second. Non-secret in-cluster hostnames from the ConfigMap therefore win over
Compose-oriented values copied from `.env`.

## Render and apply

```bash
# Render only (default). Writes deploy/k8s/rendered/<overlay>.yaml.
./scripts/k8s-deploy.sh --overlay pilot
./scripts/k8s-deploy.sh --overlay production

# Render with registry overrides.
./scripts/k8s-deploy.sh --overlay pilot \
  --api-image registry.example.invalid/sahyog-api:0.1.0 \
  --web-image registry.example.invalid/sahyog-web:0.1.0

# Apply. Renders, runs a server-side dry run, creates the Secret if requested,
# removes completed bootstrap Jobs, applies, then waits for rollouts and Jobs.
./scripts/k8s-deploy.sh --overlay pilot --confirm --create-secret-from-env
./scripts/k8s-deploy.sh --overlay production \
  --api-image registry.example.invalid/sahyog-api@sha256:... \
  --web-image registry.example.invalid/sahyog-web@sha256:... \
  --confirm
```

The script is deliberately two-step: rendering never contacts a cluster, and
applying requires `--confirm` (or an interactive `yes`). It performs a
server-side dry run before the real apply.

Completed `sahyog-migrate`, `minio-init` and `keycloak-sync` Jobs are deleted on
redeploy because Kubernetes Job pod templates are immutable. If a Job is still
active, the script stops instead of deleting it.

## Verify

```bash
./scripts/k8s-status.sh
./scripts/k8s-status.sh --json
./scripts/k8s-status.sh --strict
```

The status command is read-only. It reports node readiness, deployments,
statefulsets, pods/restarts, Jobs, ingress hosts, HPA/PDB state and recent
warning events. It never prints Secret values.

For endpoint checks, resolve the example hostnames first or use port-forward:

```bash
kubectl -n sahyog port-forward service/api 8000:8000
curl -fsS http://localhost:8000/healthz
curl -fsS http://localhost:8000/readyz
```

Observability is cluster-internal:

```bash
kubectl -n sahyog port-forward service/grafana 3000:3000
kubectl -n sahyog port-forward service/prometheus 9090:9090
kubectl -n sahyog port-forward service/langfuse-web 5721:3000
```

Langfuse is deliberately not given an ingress. Its NextAuth callback is set to
the port-forward origin; a shared deployment must front it with SSO and a real
hostname before exposing it beyond operators.

In the pilot overlay the Mailpit UI is also available through
`kubectl -n sahyog port-forward service/mailpit 8025:8025`; production removes
Mailpit.

Use the Grafana admin password from the Secret; the status scripts never print
it.

## Seed demo data

Seeding is opt-in and must not run in production. After the API, Keycloak and
migration Job are ready:

```bash
kubectl apply -k deploy/k8s/components/seed
kubectl -n sahyog wait --for=condition=complete job/sahyog-seed --timeout=600s
```

The seed Job reads the same ConfigMap and Secret as the application. Demo
passwords come from the Secret and are not printed.

## Configuration and generated files

`base/config/{postgres-init.sh,minio-init.sh,litellm.yaml}` and
`components/observability/config/*` are copies required because Kustomize
refuses to load files outside a kustomization root. Edit the source files
(`docker/...`, `config/litellm.yaml`) and recopy; `scripts/k8s-deploy.sh`
compares them with `cmp` and aborts on drift. `--allow-drift` exists only for a
deliberate, reviewed divergence.

## Storage and presigned URLs

The browser uploads audio directly with a presigned PUT. The API signs against
`S3_ENDPOINT_URL` (in-cluster MinIO), then rewrites the scheme and host to
`S3_PUBLIC_ENDPOINT_URL` for the browser. The storage ingress must therefore
expose MinIO on the same path with no rewrite rule, or the signature will not
match.

`MINIO_API_CORS_ALLOW_ORIGIN` is set to the web origin. If you change the web
host, update it and rebuild the web image with the new `AUTH_ORIGIN`.

## What this deployment does not prove

- No multi-zone, failover, backup/restore or RPO/RTO test is included. Compose
  and this pilot are single-site.
- MinIO uses `bitnamilegacy/minio`, a pilot-only dependency. Production should
  use a supported S3-compatible service or a maintained MinIO release.
- Secrets are ordinary Kubernetes Secrets unless a secret manager/CSI driver is
  installed. Enable encryption at rest and external secret delivery before real
  credentials.
- The app/ai pods are not egress-default-denied. `EXTERNAL_EGRESS_ENABLED` is
  false and the Squid proxy is a demonstration hop; production must enforce
  provider egress through an approved firewall/proxy.
- No browser-driven end-to-end test runs against this cluster. Render and
  client-side validation are covered; live smoke tests require a cluster,
  images, DNS and TLS.
- The local 7B Ollama model is CPU-only here. Measure latency per language
  before routing production workloads to it.

These limitations are tracked in [`docs/gaps.md`](../../docs/gaps.md).
