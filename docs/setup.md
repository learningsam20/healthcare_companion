# Care Companion — Setup and Operations Guide

| Field | Value |
|---|---|
| Product | Sahyog Care Companion |
| Document | `docs/setup.md` — prerequisites, configuration, startup, data, models, identity, operations and troubleshooting |
| Version | 1.0 — implementation baseline |
| Date | 2026-10-25 |
| Status | Approved baseline. Commands, paths and variables in this guide are the implementation contract; a command is valid when its script exists and the clean-machine run in §22 passes. Where this guide and [architecture.md](./architecture.md) differ, architecture wins; where both differ from [spec.md](./spec.md), the specification wins. |
| Audience | Developers, the engineering team, and acceptance, pilot and demo operators |
| Related documents | [spec.md](./spec.md) · [design.md](./design.md) · [architecture.md](./architecture.md) · [plan.md](./plan.md) · [roadmap.md](./roadmap.md) · [infra.md](./infra.md) · [gaps.md](./gaps.md) |
| Reference deployment | Docker Compose on one host; Postgres 16 + pgvector, S3Proxy, Keycloak, Redis, LiteLLM, MCP servers and Langfuse (Postgres backend). `core` is the acceptance profile; `full` adds observability and load evidence. The pilot runs `core`/`full` on the Mac M4 Pro 26 GB host sized in [infra.md](./infra.md) |

> **Safety note.** This repository is a demonstration system built with synthetic/public data. Do not load real patient data, real credentials or production exports. Identified data must not leave the hospital boundary; only de-identified text may reach an external model provider. If a step appears to require real PHI, stop and use the sample profile.

## 1. What this guide covers

This guide takes a clean machine to a working Care Companion stack and then to the evidence required at each gate:

- **One database engine.** Postgres 16+ with pgvector in every profile, including the laptop pilot and CI. There is no SQLite path (`D-02`, `Q-09`, `MC-21`).
- **One identity path.** Keycloak in every profile; no dev-auth bypass, no synthetic token switch. E2E tests seed Keycloak users (`Q-17`, `D-13`).
- **Real adapters.** SMS, SMTP/email, Slack, stock and read-only FHIR are real adapters configured from `.env` or a vault. Missing credentials produce a visible `unconfigured` state; the system never silently substitutes a mock (`D-21`, `Q-11`). Test doubles live only under tests. Secrets load order: process env → optional `SECRETS_BACKEND=file|vault` → `.env` via Settings (`app/core/vault.py`).
- **Profiles.** `minimal`, `core`, `full` and the optional `melt` add-on, exactly as defined in [architecture.md](./architecture.md#142-docker-compose-profiles).
- **Configuration.** Precedence, the typed feature registry, purpose-based model routing, notification channels and dangerous flags.
- **Identity.** Realm, clients, roles, synthetic users, patient Slack identity at onboarding and the load-test cohort.
- **Data and models.** Sample/full data load, test-data reset, model aliases, the Mac M4 Pro model set, LiteLLM, PII, STT and OpenDecider.
- **Operations.** Scripts, health/readiness, telemetry plumbing (OTLP spans/metrics; agent traces exported to Langfuse with content capture off, G-23), analytics/FinOps, evals, load tests, backup/restore, retention, Kubernetes manifests and troubleshooting.
- **Acceptance.** The clean-machine checklist in §22 with the evidence each gate expects.

The architecture behind these choices is in [architecture.md](./architecture.md#14-deployment-and-operations). Requirements and gates are in [spec.md](./spec.md). Delivery sequence is in [plan.md](./plan.md). Sizing and cost are in [infra.md](./infra.md). Known language/telemetry limitations and their mitigations are in [gaps.md](./gaps.md).

## 2. Prerequisites

### 2.1 Hardware and operating system

| Profile / role | Minimum | Recommended | Notes |
|---|---|---|---|
| `minimal` development | 4 CPU, 8 GB RAM, 20 GB free | 6 CPU, 16 GB RAM, 40 GB free | Postgres, S3Proxy, Keycloak, Redis, LiteLLM, MCP, Mailpit; host Ollama optional |
| `core` integration/acceptance | 8 CPU, 16 GB RAM, 60 GB free | 10 CPU, 32 GB RAM, 120 GB free | Adds scheduler, local STT, Langfuse (Postgres) and OTel |
| `full` acceptance/load | 8 CPU, 32 GB RAM, 120 GB free | 12 CPU, 64 GB RAM, 200 GB free | Adds Prometheus/Grafana, ClamAV, load generator and egress proxy; local models stay on host Ollama |
| **Pilot reference host** | **Mac M4 Pro, 26 GB unified memory, 1 TB SSD** | Same; external production-grade host for scale | The pilot target (`Q-28`). Docker Desktop gets 14 GB; host Ollama gets ≈7 GB; macOS keeps the rest. See the memory budget in [infra.md](./infra.md#53-laptop-pilot-mac-m4-pro-26-gb) |
| W3 local STT | CPU `small` int8 acceptable | Metal/GPU acceleration or `medium` int8 on a larger host | The pilot uses transcript upload as the fallback if CPU latency misses the target |
| Local LLM | 7–8B Q4 on the Mac | Purpose-specific small models | Pin after the D3/D4 model spike; do not assume an example tag is best |

Supported hosts: macOS 14+ on Apple silicon, Linux x86_64/arm64, Windows 11 with WSL2. Compose acceptance should run on macOS or Linux; Windows-native Docker is not an acceptance environment. The Mac pilot is a **single-host pilot**, not HA evidence.

These are development, acceptance and pilot footprints, not procurement quotes. The parameterized profiles (P laptop pilot, S demo/acceptance, M hosted pilot, L production HA) and capex/opex ranges are in [infra.md](./infra.md#4-reference-profiles-and-bill-of-materials). Measured utilisation replaces planning assumptions at G1 and G5.

### 2.2 Software

| Tool | Version target | Why |
|---|---|---|
| Git | 2.40+ | Repository and hooks |
| Docker Engine / Docker Desktop | 26+ with Compose v2 | Containers and profiles; allocate ≥14 GB to the Docker VM on the Mac pilot |
| Python | 3.12.x | API, workers, MCP servers, evals |
| `uv` | Current | Deterministic Python installs and virtualenvs |
| Node.js | 22 LTS | Vite/React build and tests |
| `npm` | 10+ | SPA installs and scripts |
| Make (optional) | Current | Convenience targets; scripts are authoritative |
| Playwright browsers (optional) | Installed by `npm --prefix apps/web exec playwright install` | Required to run the delivered Playwright/axe suite via `scripts/test.sh --e2e` (G-26) |
| k6 (optional) | 1.3+ | Full-profile smoke container only; the main load test is Python 3.12 + `httpx` via `uv` |
| Ollama | Current | Local models on the host; the compose `ollama` profile is opt-in and not started by `scripts/start.sh` |
| `ffmpeg` (optional) | Current | Audio fixture preparation |
| `jq`, `curl` | Current | Health checks and scripts |
| `kubectl` + `kustomize` (optional) | Current | Validating and applying `deploy/k8s/` |

Do not install Python packages globally. The repo uses `uv` for Python and `npm` for Node. Container images are the reference runtime; host tools exist for development and evidence.

### 2.3 External services and credentials

Every external integration is a **real adapter**. If a credential or endpoint is absent, the adapter reports `unconfigured` and the affected action is disabled with a visible reason. It does not simulate success.

| Service | Required? | Use | Missing state | Secret handling |
|---|---|---|---|---|
| Keycloak | Required in every profile | OIDC identity, roles, clinics | Stack is not ready | Bootstrap admin credentials local only; app uses a least-privilege service account |
| Postgres/pgvector | Required in every profile | All application, usage, audit and checkpoint data; Langfuse DB | Stack is not ready | `DATABASE_URL` in `.env`/vault |
| S3 / S3Proxy | Required in every profile | Documents, audio, exports, anchors | Stack is not ready | `S3_ACCESS_KEY`/`S3_SECRET_KEY` (aws-v4) |
| LiteLLM | Required for model features | All generative/embedding calls; MCP gateway | Chat/triage/scribe degrade to hand-off; red flags still run | Master key plus per-service virtual keys |
| Ollama | Required for local aliases and W3 | Local generation and embeddings | `local_main`/`embed` unavailable; W3 blocked unless transcript upload + local draft exists | No key; bind to localhost |
| OpenRouter | Optional | External **de-identified** aliases | External route absent; local/fallback only | `OPENROUTER_API_KEY` in `.env`/vault |
| Langfuse | Required for `core`/`full` acceptance evidence | Trace UI and worker on Postgres; receives metadata-only app traces with content capture off (G-23) | App continues; export is best-effort and the local trace ID remains on chat/scribe/audit records | Project keys in `.env`/vault |
| SMTP/email | Required for the email channel | Booking/action email through a Gmail-compatible SMTP account; Mailpit for local capture | Channel `unconfigured`; in-app remains | `SMTP_PASSWORD` or OAuth2 refresh token in `.env`/vault |
| Slack | Required for the Slack channel | Staff alerts in one workspace; opt-in patient messages in a separate workspace | Channel `unconfigured`; in-app remains | Bot token in `.env`/vault; workspace/channel allowlists in config |
| SMS | Required for the SMS channel | Real provider HTTP adapter | Channel `unconfigured`; in-app remains | `SMS_API_KEY` in `.env`/vault |
| FHIR | Optional | Read-only R4 demographics/encounters via `/api/v1/fhir/*` when `FHIR_BASE_URL` is set | `/meta` shows unconfigured; upload/manual workflows remain; no write-back | OAuth2 client credentials when the HIS requires them |
| ABDM | Not delivered | No linking or certification | Out of scope; documented in [roadmap.md](./roadmap.md) | — |
| Kaggle | Optional | Public datasets for the full load; sample works offline | Sample profile only | Operator environment, never committed |

In-app notifications are the record. Email, SMS and Slack are best-effort copies and may carry no clinical detail. A demo must use the dedicated staff/patient test workspaces, an approved test inbox and test numbers; no real patient is contacted.

### 2.4 Ports

Only expose what you need. Data services bind to localhost in development; in production they sit behind private networks.

Host-facing ports are allocated sequentially from **5705**. Container ports are unchanged (for example `api:8000`, `keycloak:8080`, `postgres:5432`), so internal service discovery and application defaults do not depend on the host mapping.

| Host port | Service | Profile | Exposure |
|---:|---|---|---|
| 5705 | Web (nginx + SPA) | minimal/core/full | Browser |
| 5706 | API | all | Browser/API client |
| 5707 | Keycloak | all | Browser (auth path) |
| 5708 | LiteLLM proxy | all | Loopback |
| 5709 | MCP broker | all | Loopback |
| 5710 | MCP scheduling | all | Loopback |
| 5711 | MCP records | all | Loopback |
| 5712 | MCP clinical | all | Loopback |
| 5713 | MCP platform | all | Loopback |
| 5714 | MCP decider | all | Loopback |
| 5715 | MCP PII | all | Loopback |
| 5716 | MCP STT | core/full | Loopback |
| 5717 | Mailpit SMTP capture | minimal/core/full | Loopback |
| 5718 | Mailpit web UI | minimal/core/full | Browser (local) |
| 5719 | S3Proxy S3 API (aws-v4) | minimal/core/full | Loopback |
| 5720 | *(unused — no S3 console)* | — | — |
| 5721 | Langfuse web | core/full | Browser (local) |
| 5722 | Prometheus | full | Loopback |
| 5723 | Grafana | full | Browser (local) |
| 5724 | Postgres | minimal/core/full | Loopback |
| 5725 | Redis | all | Loopback |
| 5726 | Egress proxy | full | Loopback |
| 5727 | ClickHouse HTTP | melt | Loopback |
| 5728 | Ollama container | opt-in `ollama` profile | Loopback |
| 5729 | Vite dev server | dev | Loopback |
| 4317 / 4318 | OTel collector | core/full | Internal only |
| 3310 | ClamAV | full | Internal only |
| 11434 | Host-installed Ollama | external | Loopback (not this stack) |

There are no mock SMS, Slack or FHIR ports. The delivered SMS/email/Slack adapters are real or `unconfigured`; the FHIR read adapter and clinician SPA panel are delivered (G-08 residual: write-back/ABDM). Mailpit is a real SMTP server used to capture local email. Contract tests use recorded fixtures under `tests/doubles/`, never a runtime switch.

If a port is already in use, change the matching `*_PORT` in `.env`; keep the container port unchanged. The web app's API base URL, Keycloak authority and redirect URIs must match the host ports.

## 3. Profiles

Profiles are cumulative. `scripts/start.sh` sets `COMPOSE_PROFILES`; do not mix profile flags manually unless you know the dependency graph.

| Profile | Services | What works | Known gaps |
|---|---|---|---|
| `minimal` | `web`, `api`, `worker`, `postgres`, `s3proxy`, `keycloak`, `redis`, `litellm`, `mcp-broker`, `mcp-scheduling`, `mcp-records`, `mcp-clinical`, `mcp-platform`, `mcp-decider`, `mcp-pii`, `mailpit`, host Ollama | Chat for all roles, W1, W2, grids, cost, analytics/FinOps base, Keycloak auth, S3 storage; real notification adapters when configured. Memory (G-24) and X-01 (G-13) stay flag-off until `FEATURE_*` is set. Composite PII is proven (G-28); egress stays off (G-19). Decider prefers host OpenDecider with keyword fallback (G-29). Without the scheduler, insights stay deterministic and reconciliation only runs when invoked. | No scheduler, no Langfuse/OTel, no `mcp-stt`, no dashboards |
| `core` | Adds `scheduler`, `mcp-stt`, `langfuse-web`, `langfuse-worker`, `otel-collector` | Delivered application slices plus retention/consent jobs, analytics snapshots, local-model insights, audit anchors, staleness checks and spend reconciliation. HTTP OTLP spans/metrics and per-run agent traces are exported to Langfuse with content capture off (G-23). Whisper STT is available; hi/mr WER residual is G-05. | No Prometheus/Grafana/loadgen/egress proxy; wire `BACKUP_OUT_DIR` for scheduled encrypted backup (G-30) |
| `full` | Adds `prometheus`, `grafana`, `clamav`, `loadgen`, `egress-proxy` | Acceptance and load evidence, dashboards, ClamAV scan-before-accept for documents and completed audio with quarantine (G-32). Local models use host Ollama | Single-host limits; not HA; no Prometheus alert rules or Alertmanager yet (G-25) |
| `melt` (add-on) | Adds `clickhouse` | Optional OTLP/MELT warehouse demonstration | Not required by Langfuse; sizing separate |

**Acceptance uses `core`**, with `full` where a gate needs observability, malware scanning or load evidence (`MC-26`). In `full`, `scripts/start.sh` sets `CLAMAV_HOST=clamav` and `MALWARE_SCAN_MODE=required` unless `.env` overrides them, so upload acceptance fails closed when the scanner is unavailable. `minimal` is a developer convenience and never an acceptance claim. All profiles run Postgres and Keycloak; a missing credential is `unconfigured`, never mocked.

The Mac pilot runs `core` day to day and `full` for a bounded evidence window. Do not run Prometheus, Grafana, ClamAV and a large local model concurrently on 26 GB; the budget and exclusions are in [infra.md](./infra.md#53-laptop-pilot-mac-m4-pro-26-gb).

## 4. Quick start

### 4.0 Docker vs local host-app

| Mode | Command | What runs where | When to use |
|---|---|---|---|
| **All-in-Docker** | `./scripts/start.sh --profile minimal\|core\|full` | API, web, worker, scheduler **and** dependencies in Compose | Acceptance, demos, load evidence, parity with pilot images |
| **Local host-app** | `./scripts/start.sh --profile … --local` or `./scripts/dev.sh` | **Host:** uvicorn API (agents in-process), Vite UI, ARQ worker + scheduler. **Docker:** Postgres, Keycloak, Redis, S3Proxy, LiteLLM, MCP, Mailpit (+ profile extras) | Day-to-day debug — edit Python/TS and reload without rebuilding images |

Notes for `--local` / `dev.sh`:

- `.env` may keep container DNS (`postgres`, `keycloak`, …); local mode loads secrets into the process environment and rewrites those URLs to `localhost:<published-port>` for host processes.
- Postgres and Redis attach to both `app` and `data` so loopback ports (`POSTGRES_PORT` / `REDIS_PORT`) publish; a data-only attachment on an `internal: true` network cannot publish host ports.
- Compose `api` / `web` / `worker` / `scheduler` are stopped so host ports 5706 / 5729 are free.
- Vite defaults to <http://localhost:5729> (HMR) and proxies `/api` to the host API.
- Skip async jobs with `--no-workers` if you only need UI + API.
- Prerequisites: Docker daemon, `uv`, `npm`, and (for models) host Ollama. After changing networks, recreate: `docker compose up -d --force-recreate postgres redis`.
- If `.env` sets `HA_MODE` / `CHECKPOINTER_REQUIRED`, the host API needs `psycopg[binary]` (declared in `apps/api`); run `uv sync --all-packages` so LangGraph’s Postgres checkpointer can open without system libpq.

### 4.1 Minimal, for UI/API development

Prerequisites: Docker, Python/uv, Node/npm, and Ollama on the host if you want local model calls.

```bash
git clone <repository-url> care-companion
cd care-companion

cp .env.example .env
# Set secrets from §6.2–§6.4. External egress stays off until DPDP/security sign-off (G-19);
# composite PII is implemented and proven (G-28) but egress remains fail-closed by default.

# Option A — everything in Docker
./scripts/start.sh --profile minimal

# Option B — fast debug: app on host, deps in Docker
./scripts/start.sh --profile minimal --local

./scripts/seed-users.sh
./scripts/load-data.sh --sample
./scripts/status.sh   # Compose mode
./scripts/smoke.sh    # points at API_BASE_URL / Vite or nginx web
```

Expected URLs (Compose / nginx web):

| Service | URL |
|---|---|
| Web | <http://localhost:5705> |
| API health | <http://localhost:5706/healthz> |
| API readiness | <http://localhost:5706/readyz> |
| Keycloak | <http://localhost:5707> (realm `sahyog`) |
| LiteLLM | <http://localhost:5708/health/liveliness> |
| MCP broker | <http://localhost:5709/healthz> |
| S3Proxy | <http://localhost:5719> (aws-v4; no console) |
| Mailpit (email capture) | <http://localhost:5718> |

In **local host-app** mode open Vite at <http://localhost:5729> (**not** `127.0.0.1` — OIDC redirects and CORS are localhost). The UI calls same-origin `/api` via the Vite proxy to the host API on 5706.

Sign in with a seeded Keycloak user. There is no role/user switcher and no dev-auth bypass. If a notification adapter is not configured, the channel shows `unconfigured` in the UI and delivery grid; the domain action still succeeds.

### 4.2 Core, for integration, R2/R3 and acceptance

Prerequisites: a running Docker daemon with enough memory, host Ollama for local aliases, and the secrets below. The first start pulls images and can take 10–20 minutes.

```bash
cp .env.example .env
# Required: POSTGRES_PASSWORD, KEYCLOAK_ADMIN_PASSWORD, KEYCLOAK_CLIENT_SECRET,
# S3_ACCESS_KEY, S3_SECRET_KEY, LITELLM_MASTER_KEY, MCP_SERVICE_TOKEN,
# MCP_CONTEXT_SECRET, SEED_DEMO_PASSWORD, LANGFUSE_* keys, APP_SECRET_KEY,
# PII_TOKEN_SECRET, SMTP_* for the email channel, SLACK_* and SMS_* when enabled.
# FHIR_* enable the read-only adapter + SPA panel when FEATURE_FHIR_READ is on (G-08).
# External egress remains off by default until DPDP/security sign-off (G-19); composite
# PII is proven (G-28) and the gateway stays fail-closed when egress is disabled.

./scripts/start.sh --profile core
./scripts/seed-users.sh
./scripts/load-data.sh --sample
./scripts/smoke.sh --sources --notifications --analytics --flags
```

Expected URLs: as §4.1 plus Langfuse at <http://localhost:5721>, OTel Collector on 4317/4318 (internal), and `mcp-stt` on host port 5716 (container port 8107).

Use Mailpit for the first email run even when Gmail is configured: it proves the template and delivery record without touching a real inbox. Switch `SMTP_HOST`/`SMTP_PORT` to the provider only after the Mailpit path and the delivery-status grid pass. Email remains the real SMTP adapter in both cases.

`start.sh` waits for dependencies, runs migrations explicitly (not on API boot), imports/updates the Keycloak realm idempotently and prints a redacted summary. If readiness is not truthful, fix the dependency; do not bypass it.

### 4.3 Full, for load, security and observability evidence

```bash
./scripts/start.sh --profile full
./scripts/status.sh
./scripts/seed-users.sh --load-test 20
./scripts/load_test.sh --profile r3 --auth keycloak --traffic-class synthetic \
  --rate 1400 --burst 4 --duration 60m --allow-real-users --abort-on-real-slo
```

The full profile adds Prometheus/Grafana, ClamAV, the egress proxy and a k6 smoke container. Local models stay on the host Ollama daemon. The main `load-test.sh` run is Python/httpx on the host and authenticates through Keycloak. It is still a single-host environment; do not claim HA or production capacity. The load test authenticates the dedicated `loadtest.*` Keycloak cohort through the same public APIs as real users. It does not use a dev bypass, direct database seeding or a disabled safety path. Running alongside real users additionally requires `LOAD_TEST_ALLOW_REAL_USERS=true`, an approved window and the real-user abort guard (§17.3).

For notification load, set `NOTIFICATIONS_ENABLED=false` so in-app records still prove the workflow and no real message is sent; a notification-channel load test uses the approved test recipients and is a separate bounded run.

### 4.4 Melt, optional warehouse demonstration

```bash
./scripts/start.sh --profile full --with-melt
# or
docker compose --profile minimal --profile core --profile full --profile melt up -d clickhouse
```

`melt` adds ClickHouse as an **optional OTLP/MELT destination**. Langfuse remains on Postgres (`D-23`); ClickHouse is not a hard dependency. Use this profile to prove OTLP portability, not to complete application acceptance. Sizing is in [infra.md](./infra.md).

### 4.5 Kubernetes-ready deployment

Compose is the reference acceptance path. `deploy/k8s/` contains Kustomize/Helm-ready manifests for every service, HPA/PDB, NetworkPolicy, PVC or external-service overlays, and a migration/seed Job (`ADR-16`, `D-27`).

```bash
kubectl kustomize deploy/k8s/overlays/pilot >/tmp/care-k8s.yaml   # render/validate
./scripts/k8s-deploy.sh --overlay pilot --namespace sahyog          # render only
./scripts/k8s-deploy.sh --overlay pilot --namespace sahyog --confirm # apply
./scripts/k8s-status.sh --namespace sahyog                           # read-only status
./scripts/k8s-status.sh --namespace sahyog
```

The `pilot` overlay targets one node; `production` documents the HA topology in [architecture.md](./architecture.md#147-production-topology-kubernetes-manifests-delivered). CI runs `kubectl kustomize` and schema validation; a kind smoke test runs where the CI runner allows. Kubernetes manifests do not make the pilot HA.

## 5. Repository layout and configuration

### 5.1 Layout

```text
care-companion/
  apps/
    web/                      # Vite + React + TypeScript
    api/                      # FastAPI modular monolith
      app/
        core/                 # config, logging, security, telemetry
        modules/              # auth, chat, scheduling, records, scribe,
                              # notifications, analytics, finops, admin
        integrations/         # fhir/, stock/, sms/, email/, slack/
        agents/               # graphs, nodes, prompts binding
        repositories/
  services/
    mcp-broker/               # signed context, allowlists, forwarding
    mcp-scheduling/
    mcp-records/
    mcp-clinical/
    mcp-platform/
    mcp-decider/
    mcp-pii/
    mcp-stt/
  packages/
    py-common/                # config, logging, auth context, errors, telemetry
    contracts/                # OpenAPI-generated TS client, JSON/SSE schemas
  config/
    app.yaml
    features.yaml             # typed feature registry (owner, environments, expiry, lock)
    models.yaml               # purpose-based routes and aliases
    litellm.yaml
    mcp.yaml
    notifications.yaml        # channel enablement, templates, allowlists, retry budgets
    metrics.yaml              # versioned analytics metric registry
    finops_model.yaml         # versioned sizing/cost model shared with infra.md
    red_flags.yaml
    specialties.yaml
    stock.yaml
    prices.yaml
    prompts/
  evals/
    sets/
    harness/
    adapters/
      ragas/
      deepeval/
  tests/
    doubles/                  # recorded fixtures/contract doubles; never runtime
  deploy/
    k8s/
      base/
      overlays/
        pilot/
        production/
  scripts/
  docs/
    adr/
    data-contracts/
    runbooks/
    gaps.md
  docker/
  docker-compose.yml
  .env.example
```

### 5.2 Configuration precedence

1. Process environment (highest).
2. `.env.<profile>` (e.g. `.env.core`), optional.
3. `.env` (local, gitignored).
4. Versioned YAML defaults in `config/*.yaml` (lowest).

Secrets belong in environment variables or a secret manager, never in YAML, images, the repository or the frontend. Non-secret behaviour (limits, thresholds, aliases, retention, routes) belongs in versioned YAML.

Feature flags use the same precedence with a typed registry: `FEATURE_<KEY>` process env > `.env.<profile>` > `.env` > the `config/features.yaml` default. Flags are read once at startup and published through `/meta`; only the runtime-safe subset is changeable by an admin, and every change is audited. Safety-locked flags cannot disable red flags, audit, consent, the PII gate, scope filtering, signature controls or required human review. An unknown, expired or locked-value flag fails validation instead of being ignored.

### 5.3 Configuration files

| File | Purpose | Secret? |
|---|---|---|
| `config/app.yaml` | Environment, ports, upload limits, retention, rate limits, locales, analytics schedules and small-cell minimum | No |
| `config/features.yaml` | Typed feature registry: key, default, environments, owner, expiry, safety/lock class | No |
| `config/models.yaml` | Purpose → alias → provider/model, timeouts, fallbacks, egress class, token budgets | No (keys from env) |
| `config/litellm.yaml` | LiteLLM proxy model list, router, MCP servers, guardrail hook, spend DB | No (keys from env) |
| `config/mcp.yaml` | MCP servers, tool allowlists per graph, timeouts, output caps | No |
| `config/notifications.yaml` | Channel enablement, template versions, senders, quiet hours, retry budget, SMS/email/Slack allowlists | No (secrets via env) |
| `config/metrics.yaml` | Metric ID, version, formula/SQL, dimensions, freshness and suppression | No |
| `config/finops_model.yaml` | Versioned sizing/cost parameters, profiles, growth assumptions and what-if defaults shared with [infra.md](./infra.md) | No |
| `config/red_flags.yaml` | Red-flag rules, severity, version/checksum | No |
| `config/specialties.yaml` | Closed specialty catalogue and crosswalk | No |
| `config/stock.yaml` | Stock adapter, path/URL, staleness threshold | No |
| `config/prices.yaml` | Model, STT/OCR, SMS/email price catalogue with effective dates | No |
| `config/prompts/**` | Prompt versions and metadata | No (no PHI) |
| `.env` | Secrets and environment-specific values | **Yes** |

`config/features.yaml` is the only source of build-time feature defaults. `config/notifications.yaml` never contains a token or password; those come from `SMTP_*`/`SLACK_*`/`SMS_*` environment variables. `config/metrics.yaml` is the only place a tile's definition lives; a new metric without a registry entry is rejected in review (`FR-ANL`). `config/finops_model.yaml` is the single model behind the FinOps what-if workspace and `infra.md`; a divergence is a defect (`ANL-AC-06`, `MC-33`).

### 5.4 Dangerous flags

| Flag | Default | Effect | Guardrail |
|---|---|---|---|
| `EXTERNAL_EGRESS_ENABLED` | `false` | Allows de-identified text to OpenRouter | PII gate healthy; W3 local; audit |
| `AUTO_SIGN` | `false` | Must never be true | Startup fails if true; clinical safety control |
| `LANGFUSE_CAPTURE_CONTENT` | `false` | Captures prompts/answers in traces | Must stay false; startup rejects true |
| `ALLOW_CLOUD_STT` | `false` | Allows cloud speech-to-text | Off by default; requires DPDP/security review |
| `DISABLE_PII_GATE` | `false` | Bypasses the egress scrubber | Startup fails if true; never for acceptance |
| `NOTIFY_SEND_EXTERNAL` | `false` | Allows real SMS/email/Slack sends | Requires approved templates, verified recipients and allowlisted workspaces/channels |
| `NOTIFY_OPS_SUBJECT` | (empty) | Keycloak subject for ops/FinOps/emergency handoff staff notify | Required for live `staff_handoff` / overdue paging; tickets still create with `delivery_status=skipped` when empty |
| `LOAD_TEST_ALLOW_REAL_USERS` | `false` | Lets the load test share an environment with real users | Requires approval, a Keycloak test cohort, tag separation and the real-user abort guard (`FR-OPS-15`) |

Each dangerous flag is audited when changed. A production/acceptance deployment rejects a dangerous config before serving traffic. There is **no** `DEV_AUTH_BYPASS` flag and no "local storage" switch; Postgres and Keycloak are always on.

## 6. Environment variable reference

`.env.example` is authoritative and validated at startup. Values below are examples, not production defaults.

### 6.1 Application and security

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `APP_ENV` | `dev` / `staging` / `production` | Yes | No | Controls production validations and safe defaults |
| `APP_PROFILE` | `minimal` / `core` / `full` | Yes | No | Must match the Compose profile |
| `APP_BASE_URL` | `http://localhost:5705` | Yes | No | Public web URL |
| `API_BASE_URL` | `http://localhost:5706` | Yes | No | Public/internal API URL |
| `CORS_ORIGINS` | `http://localhost:5705,http://localhost:5729` | Yes | No | Exact allowlist; no `*` outside local |
| `LOG_LEVEL` | `INFO` | No | No | `DEBUG` never logs content |
| `TZ` | `Asia/Kolkata` | Yes | No | Display timezone; storage UTC |
| `APP_SECRET_KEY` | random 32+ bytes | Yes | **Yes** | CSRF/secret derivation; rotate |
| `JWT_ISSUER` | `http://localhost:5707/realms/sahyog` | Yes | No | Must match Keycloak |
| `JWT_AUDIENCE` | `sahyog-api` | Yes | No | API audience mapper |
| `JWT_JWKS_CACHE_TTL` | `300` | No | No | Seconds |
| `SESSION_IDLE_MINUTES` | `30` | No | No | Keycloak session alignment |
| `RATE_LIMIT_DEFAULT` | `60/min` | No | No | Per user/IP where applicable |
| `MAX_ACTIVE_SESSIONS` | `20` | No | No | Per user |
| `UPLOAD_MAX_MB` | `20` | No | No | Advisory client + enforced server |
| `AUDIT_EXPORT_MAX_DAYS` | `31` | No | No | Compliance export limit |
| `SUPPORTED_LOCALES` | `en-IN,hi-IN,mr-IN` | Yes | No | UI, notifications and safety copy |
| `DEFAULT_LOCALE` | `en-IN` | Yes | No | Fallback locale |
| `LANGUAGE_DETECTION_ENABLED` | `true` | No | No | Mixed-language input metadata |

### 6.2 Database and queue

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `DATABASE_URL` | `postgresql+psycopg://app:...@postgres:5432/care` | Yes | **Yes** | App role; not superuser. No SQLite URL is accepted |
| `LANGFUSE_DATABASE_URL` | `postgresql://langfuse:...@postgres:5432/langfuse` | core/full | **Yes** | Separate database on the same cluster |
| `EMBEDDING_DIM` | `1024` | Yes | No | Must match the embedding model/table |
| `DB_POOL_SIZE` | `10` | No | No | Per API replica |
| `DB_POOL_TIMEOUT` | `30` | No | No | Seconds |
| `PG_SHARED_BUFFERS` | `1GB` | No | No | Pilot cap; see architecture §6.7 |
| `REDIS_URL` | `redis://redis:6379/0` | Yes | No (auth optional) | Queues, run buffers, locks |
| `SSE_BUFFER_TTL_SECONDS` | `3600` | No | No | Ephemeral run stream |
| `QUEUE_CONCURRENCY` | `4` | No | No | Worker ingest concurrency |
| `INGEST_MAX_PAGES` | `200` | No | No | Per document |
| `INGEST_TIMEOUT_SECONDS` | `600` | No | No | Per job |
| `RETENTION_DRY_RUN` | `true` | No | No | Scheduler default; explicit live run for evidence |

### 6.3 Keycloak / OIDC

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `KEYCLOAK_URL` | `http://keycloak:8080` | Yes | No | Container-internal JWKS/back-channel base |
| `KEYCLOAK_PUBLIC_URL` | `http://localhost:5707` | Yes | No | Browser-visible issuer base; must match token `iss` |
| `KEYCLOAK_REALM` | `sahyog` | Yes | No | Realm |
| `KEYCLOAK_CLIENT_ID` | `sahyog-web` | Yes | No | Public SPA client; PKCE |
| `KEYCLOAK_AUDIENCE` | `sahyog-api` | Yes | No | API audience mapper |
| `KEYCLOAK_ADMIN_CLIENT_ID` | `sahyog-admin` | Yes | No | Confidential service account |
| `KEYCLOAK_ADMIN_CLIENT_SECRET` | random | Yes | **Yes** | Least-privilege admin API |
| `KEYCLOAK_ADMIN_USER` | `admin` | Local bootstrap | **Yes** | Container bootstrap; not app runtime |
| `KEYCLOAK_ADMIN_PASSWORD` | random | Local bootstrap | **Yes** | Container bootstrap; rotate |
| `KEYCLOAK_JWKS_CACHE_TTL` | `300` | No | No | Seconds |
| `OIDC_SCOPES` | `openid profile email` | No | No | No offline access unless required |
| `OIDC_REDIRECT_URI` | `http://localhost:5705/auth/callback` | Yes | No | Must match Keycloak exactly |

### 6.4 Object storage

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `S3_ENDPOINT_URL` | `http://s3proxy:80` | Yes | No | Local S3Proxy or cloud S3-compatible endpoint |
| `S3_PUBLIC_ENDPOINT_URL` | `http://localhost:5719` | No | No | Browser-facing host used to rewrite presigned URLs |
| `S3_REGION` | `us-east-1` | No | No | Passed to SigV4 / S3Proxy |
| `S3_ACCESS_KEY` | random | Yes | **Yes** | App key **and** S3Proxy aws-v4 identity |
| `S3_SECRET_KEY` | random | Yes | **Yes** | App secret **and** S3Proxy aws-v4 credential |
| `S3_USE_PATH_STYLE` | `true` | No | No | Required for S3Proxy; false for some cloud S3 |
| `S3_SERVER_SIDE_ENCRYPTION` | empty | No | No | Empty for local S3Proxy; `AES256` for SSE-S3-capable stores |
| `S3_BUCKET_DOCUMENTS` | `sahyog-documents` | Yes | No | Private |
| `S3_BUCKET_AUDIO` | `sahyog-audio` | Yes | No | Private; 24 h lifecycle |
| `S3_BUCKET_EXPORTS` | `sahyog-exports` | Yes | No | Private; 24 h |
| `S3_BUCKET_ANCHORS` | `sahyog-audit-anchors` | Yes | No | Immutable/object lock where available |
| `S3_BUCKET_EVAL` | `sahyog-eval` | No | No | Synthetic eval artefacts |
| `S3_BUCKET_BACKUPS` | `sahyog-backups` | No | No | Encrypted DB/object backups; restore role only |
| `PRESIGN_TTL_SECONDS` | `300` | No | No | Scoped, short-lived |

### 6.5 LiteLLM, models and MCP

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `LITELLM_BASE_URL` | `http://litellm:4000` | Yes | No | OpenAI-compatible endpoint |
| `LITELLM_MASTER_KEY` | `sk-...` | Yes | **Yes** | Proxy admin key; not exposed to browser |
| `LITELLM_MCP_BASE_URL` | `http://litellm:4000` | Yes | No | MCP REST endpoints |
| `LITELLM_MCP_KEY` | virtual key | Yes | **Yes** | Service virtual key with MCP scope |
| `MODEL_ROUTES_CONFIG` | `config/models.yaml` | Yes | No | Purpose-based routing |
| `OPENROUTER_API_KEY` | `sk-or-...` | Optional | **Yes** | External de-identified only |
| `OPENROUTER_MAIN_MODEL` | provider/model ID | Optional | No | Pin after verification |
| `OPENROUTER_SMALL_MODEL` | provider/model ID | Optional | No | Cheap classification/clarification |
| `OLLAMA_BASE_URL` | `http://host.docker.internal:11434` | Yes for local | No | Host or `ollama` service |
| `OLLAMA_CHAT_MODEL` | `ollama_chat/qwen2.5:7b-instruct-q4_K_M` | Local | No | Pin after the Mac model spike; keep the LiteLLM provider prefix |
| `OLLAMA_SMALL_MODEL` | `ollama_chat/qwen2.5:3b-instruct-q4_K_M` | Local | No | Intent fallback/clarification; keep the provider prefix |
| `EMBED_MODEL` | `bge-m3` | Yes | No | 1024-d default; must match `EMBEDDING_DIM` |
| `JUDGE_MODEL` | alias `judge` | Eval | No | Calibrated judge; not a release gate alone |
| `MODEL_TIMEOUT_SECONDS` | `30` | No | No | Per call |
| `MODEL_MAX_RETRIES` | `2` | No | No | Capped exponential backoff |
| `CIRCUIT_BREAKER_FAILURES` | `5` | No | No | Opens the route |
| `MCP_BROKER_URL` | `http://mcp-broker:8100` | Yes | No | Single enforcement point |
| `MCP_SCHEDULING_URL` | `http://mcp-scheduling:8101` | Yes | No | Internal |
| `MCP_RECORDS_URL` | `http://mcp-records:8102` | Yes | No | Internal |
| `MCP_CLINICAL_URL` | `http://mcp-clinical:8103` | Yes | No | Internal |
| `MCP_PLATFORM_URL` | `http://mcp-platform:8104` | Yes | No | Internal |
| `MCP_DECIDER_URL` | `http://mcp-decider:8105` | Yes | No | Internal |
| `MCP_PII_URL` | `http://mcp-pii:8106` | Yes | No | Internal |
| `MCP_STT_URL` | `http://mcp-stt:8107` | core/full | No | Internal |
| `MCP_SERVICE_TOKEN` | random | Yes | **Yes** | Service-to-service auth |
| `MCP_CONTEXT_SECRET` | random 32+ bytes | Yes | **Yes** | Signs `_context`; rotate with overlap |
| `MCP_CONTEXT_TTL_SECONDS` | `120` | No | No | Short-lived |
| `MCP_TOOL_TIMEOUT_SECONDS` | `20` | No | No | Per tool |
| `MCP_MAX_OUTPUT_BYTES` | `262144` | No | No | Output cap |

### 6.6 PII, decider and STT

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `PII_ENGINE` | `composite` | No | No | Runtime-proven composite (Presidio + GLiNER); gateway requires `engine=composite` before egress (G-28) |
| `PII_FAIL_CLOSED` | `true` | No | No | Keep true; `EXTERNAL_EGRESS_ENABLED` stays false until security sign-off (G-19) |
| `PII_TOKEN_SECRET` | random 32+ bytes | Yes | **Yes** | Token map secret for reversible de-identification |
| `PII_MODEL_PATH` | `/models/privacy-filter` | Optional | No | Optional Privacy Filter weights |
| `PRESIDIO_SPACY_MODEL` | `en_core_web_sm` | Optional | No | Installed in `sahyog-api:local` / `mcp-pii` image |
| `GLINER_MODEL` | `knowledgator/gliner-pii-large-v1.0` | Optional | No | Loaded by composite engine |
| `DECIDER_ADAPTER` | `mcp` | No | No | Prefer host Ollama OpenDecider (`DECIDER_BACKEND=ollama`); keyword fallback when unreachable (G-29) |
| `DECIDER_MODEL_PATH` | OpenDecider GGUF via Ollama | Optional | No | Pull on host; see G-29 evidence |
| `STT_ADAPTER` | `local` | core/full | No | faster-whisper local path; cloud only behind `ALLOW_CLOUD_STT` |
| `WHISPER_MODEL` | `small` / `medium` | core/full | No | Weights on disk; EN WER measured, hi/mr residual (G-05) |
| `WHISPER_DEVICE` | `cpu` / `metal` / `cuda` | core/full | No | Prefer Metal on Mac host |
| `WHISPER_COMPUTE_TYPE` | `int8` / `float16` | core/full | No | Match device |
| `ALLOW_CLOUD_STT` | `false` | No | No | Must remain false without review |

### 6.7 Integrations

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `FHIR_BASE_URL` | `https://hapi.fhir.org/baseR4` | For FHIR read | No | Read-only R4; open test URL or HIS base |
| `FHIR_CLIENT_ID` | client ID | When OAuth | No | With secret + token URL for HIS |
| `FHIR_CLIENT_SECRET` | secret | When OAuth | **Yes** | Client-credentials grant |
| `FHIR_TOKEN_URL` | token endpoint | When OAuth | No | Required with client id/secret |
| `FHIR_TIMEOUT_SECONDS` | `15` | Optional | No | HTTP timeout |
| `STOCK_ADAPTER` | `csv` / `api` | Yes | No | `api` reads the vendor sandbox/feed |
| `STOCK_CSV_PATH` | `/data/stock.csv` | CSV | No | Snapshot; source/time shown |
| `STOCK_API_URL` | vendor URL | API | No | Read-only |
| `STOCK_API_KEY` | key | API | **Yes** | Vault preferred |
| `SMS_ADAPTER` | `http` | For SMS | No | Real provider HTTP adapter |
| `SMS_BASE_URL` | vendor API | For SMS | No | Client-supplied |
| `SMS_API_KEY` | key | For SMS | **Yes** | Vault preferred |
| `SMS_SENDER_ID` | `SAHYOG` | No | No | DLT/template compliance in production |

An adapter with no endpoint/credential reports `unconfigured`; it does not fall back to a console or mock. Feature surfaces depending on it are disabled with a reason, and in-app notifications still work.

### 6.8 Notification channels

In-app is always on for essential safety and booking events and is not configurable off. SMS, email and Slack are best-effort copies with per-channel delivery records. `config/notifications.yaml` controls templates, enablement and allowlists; secrets stay here.

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `NOTIFICATIONS_ENABLED` | `true` | Yes | No | Master switch for outbound copies; in-app remains |
| `EMAIL_ADAPTER` | `smtp` | For email | No | Only `smtp`; point it at Mailpit locally |
| `SMTP_HOST` | `mailpit` / `smtp.gmail.com` | For SMTP | No | Mailpit locally; provider host for pilot |
| `SMTP_PORT` | `1025` (container) / `587` (provider) | For SMTP | No | Internal Mailpit port; STARTTLS on 587 |
| `SMTP_CAPTURE_PORT` | `5717` | No | No | Host mapping for Mailpit SMTP; UI on 5718 |
| `SMTP_AUTH_MODE` | `none` / `password` / `oauth2` | For SMTP | No | Use `oauth2` where Workspace requires it |
| `SMTP_USERNAME` | `care@example.test` | For SMTP | No | Sending identity; never logged |
| `SMTP_PASSWORD` | app password | For SMTP | **Yes** | Use an app password, not the mailbox password |
| `SMTP_OAUTH2_REFRESH_TOKEN` | token | OAuth2 | **Yes** | Only where the provider supports OAuth2 |
| `SMTP_USE_STARTTLS` | `true` | For SMTP | No | Required for Gmail; Mailpit local may be plain |
| `SMTP_TIMEOUT_SECONDS` | `10` | No | No | Bounded; failure never blocks the domain action |
| `EMAIL_FROM` | `no-reply@sahyog.example.test` | For email | No | Verified sender |
| `EMAIL_REPLY_TO` | `support@sahyog.example.test` | No | No | Monitored mailbox |
| `SLACK_ADAPTER` | `bot` | For Slack | No | Real Slack adapter; no mock mode |
| `SLACK_STAFF_BOT_TOKEN` | `xoxb-...` | Bot | **Yes** | Staff workspace bot; scope `chat:write` |
| `SLACK_PATIENT_BOT_TOKEN` | `xoxb-...` | Bot | For patient Slack | Patient workspace bot; separate install |
| `SLACK_BOT_TOKEN` | `xoxb-...` | Legacy | No | Alias for staff token only |
| `SLACK_STAFF_WORKSPACE_ID` | `T012345` | For staff Slack | No | Separate staff workspace |
| `SLACK_PATIENT_WORKSPACE_ID` | `T067890` | For patient Slack | No | Separate patient/other-users workspace |
| `SLACK_ALLOWED_CHANNELS` | `C012345,C067890` | For staff Slack | No | Staff channel allowlist; no wildcard |
| `SLACK_PATIENT_ALLOWED_CHANNELS` | `C0...` | Optional | No | Patient channel allowlist when posting to channels |
| `NOTIFY_RETRY_MAX` | `5` | No | No | Bounded retries with jitter |
| `NOTIFY_RETRY_BACKOFF_SECONDS` | `60` | No | No | Exponential base |
| `NOTIFY_SEND_EXTERNAL` | `false` | Yes | No | Dangerous flag; enable only for an approved audience |

SMS settings are in §6.7. A notification carries no diagnosis, note text, document link, access token or patient identifier for Slack; email/SMS carry a minimal template and an authenticated link only. Staff and patient Slack audiences are distinct workspaces; a patient must opt in and have a verified Slack ID on their profile (§7.5).

### 6.9 Evaluation, analytics, feature flags and load guards

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `EVAL_FRAMEWORK` | `ragas` | Eval | No | `ragas` for RAG, `deepeval` for non-RAG |
| `EVAL_JUDGE_ALIAS` | `judge` | Eval | No | Through LiteLLM; uncalibrated against human review; never a release gate alone (G-16) |
| `DEEPEVAL_ENABLED` | `true` | No | No | Non-RAG suites; the runner records framework/version |
| `DEEPEVAL_MODEL_ALIAS` | `judge` | Optional | No | Must use the gateway |
| `ANALYTICS_ENABLED` | `true` | Yes | No | Six-tab analytics area |
| `ANALYTICS_REFRESH_CRON` | `15 * * * *` | No | No | Snapshot refresh in the scheduler |
| `ANALYTICS_SMALL_CELL_MIN` | `5` | Yes | No | Suppress/aggregate patient-level counts below this |
| `ANALYTICS_STALE_AFTER_MINUTES` | `90` | No | No | Beyond this, tiles show stale/unknown |
| `ANALYTICS_SNAPSHOT_RETENTION_DAYS` | `365` | No | No | Aggregate snapshots only |
| `INSIGHTS_ENABLED` | `true` | No | No | Improvement opportunities, advisory only; scheduled local-model drafts with accept/reject and a deterministic fallback (G-30) |
| `INSIGHTS_MODEL_ALIAS` | `local_main` | No | No | Local by default; aggregate-only input |
| `INSIGHTS_SCHEDULE_CRON` | `0 6 * * 1` | No | No | Weekly generation |
| `INSIGHTS_MAX_ACTIVE` | `20` | No | No | Ranked list cap |
| `INSIGHTS_RETENTION_DAYS` | `90` | No | No | Expired insights are not shown |
| `FINANCE_FX_RATE_INR_PER_USD` | `88` | FinOps | No | Display/accounting conversion; show rate and date |
| `FINANCE_FX_RATE_DATE` | `2026-10-25` | FinOps | No | Finance-provided; update with the rate |
| `FINANCE_SHOWBACK_ENABLED` | `true` | No | No | Aggregate-only export |
| `FINANCE_MODEL_CONFIG` | `config/finops_model.yaml` | Yes | No | Same model as analytics what-if |
| `FEATURE_<KEY>` | `FEATURE_<declared-key>=true` | No | No | Overrides the registry; unknown/expired keys fail startup |
| `LOAD_TEST_ALLOW_REAL_USERS` | `false` | Yes | No | Dangerous flag; needs approval and abort guard |
| `LOAD_TEST_AUTH` | `keycloak` | Load | No | Public API + real auth; no dev bypass |
| `LOAD_TEST_COHORT_PREFIX` | `loadtest` | Load | No | Dedicated users/fixtures; never matches real patients |
| `LOAD_TEST_TRAFFIC_CLASS` | `synthetic` | Load | No | Reported separately from real traffic |
| `LOAD_TEST_ABORT_ON_REAL_SLO` | `true` | Load | No | Stops on real-user p95/error breach |
| `LOAD_TEST_REAL_P95_MS` | `4000` | Load | No | Guard threshold; documented in the run plan |
| `LOAD_TEST_REAL_ERROR_PCT` | `1` | Load | No | Guard threshold |
| `LOAD_TEST_BUDGET_USD` | `5` | Load | No | Hard budget guard for the run |

Feature flags are **not** free-form settings: add a key to `config/features.yaml` with owner, environments, default, expiry and safety class, then use `FEATURE_<KEY>` only for environment overrides. `./scripts/flags.sh --validate` fails on a duplicate, expired or safety-locked-on override. Analytics and FinOps definitions live in `config/metrics.yaml` and `config/finops_model.yaml`, not in environment variables.

### 6.10 Telemetry, cost and retention

| Variable | Example | Required | Secret | Notes |
|---|---|---|---|---|
| `OTEL_EXPORTER_OTLP_ENDPOINT` | `http://otel-collector:4317` | core/full | No | OTLP gRPC |
| `OTEL_EXPORTER_OTLP_PROTOCOL` | `grpc` | No | No | `grpc` or `http/protobuf` |
| `OTEL_SERVICE_NAME` | `sahyog-api` | No | No | Per service |
| `OTEL_SAMPLE_RATE` | `0.2` | No | No | No content attributes |
| `OTEL_RESOURCE_ATTRIBUTES` | `deployment.environment=pilot` | No | No | No identifiers beyond internal IDs |
| `LANGFUSE_HOST` | `http://langfuse-web:3000` | core/full | No | Self-hosted |
| `LANGFUSE_PUBLIC_KEY` | `pk-lf-...` | core/full | **Yes** | Project key |
| `LANGFUSE_SECRET_KEY` | `sk-lf-...` | core/full | **Yes** | Project secret |
| `LANGFUSE_CAPTURE_CONTENT` | `false` | Yes | No | Must be false for PHI |
| `LANGFUSE_RETENTION_DAYS` | `30` | No | No | Metadata |
| `PROMETHEUS_PORT` | `5722` | full | No | Admin only; container listens on 9090 |
| `GRAFANA_ADMIN_PASSWORD` | random | full | **Yes** | Admin only |
| `APP_EVENT_RETENTION_DAYS` | `90` | No | No | No PHI |
| `AUDIT_RETENTION_DAYS` | `365` | No | No | Minimum 1 year |
| `AUDIO_RETENTION_HOURS` | `24` | Yes | No | Lifecycle + deletion job |
| `CHAT_RETENTION_DAYS` | `30` | Yes | No | Messages/checkpoints |
| `DRAFT_RETENTION_DAYS` | `30` | No | No | Unsigned drafts |
| `MEMORY_INACTIVITY_DAYS` | `180` | No | No | Reserved for mem0 preference memory; mem0 is not wired (G-24) |
| `PRICE_CATALOG_PATH` | `config/prices.yaml` | Yes | No | Effective dates |
| `DEFAULT_MONTHLY_BUDGET_USD` | `50` | No | No | Placeholder; configurable |
| `SESSION_TOKEN_CAP` | `50000` | No | No | Per session; configurable |
| `BUDGET_ALERT_PCT` | `80` | No | No | Alert threshold |
| `BUDGET_HARD_STOP` | `true` | No | No | Blocks or routes local |

### 6.11 Frontend (`VITE_*`)

Only non-secret, build-time values belong here. Never put a client secret or provider key in a `VITE_*` variable.

| Variable | Example | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | `http://localhost:5706` | API origin only; the app appends `/api/v1` |
| `VITE_OIDC_AUTHORITY` | `http://localhost:5707/realms/sahyog` | Keycloak realm |
| `VITE_OIDC_CLIENT_ID` | `sahyog-web` | Public client |
| `VITE_OIDC_REDIRECT_URI` | `http://localhost:5705/auth/callback` | Must match Keycloak |
| `VITE_OIDC_POST_LOGOUT_URI` | `http://localhost:5705/` | Keycloak logout |
| `VITE_APP_ENV` | `dev` / `staging` | Display/build checks |
| `VITE_DEFAULT_LOCALE` | `en-IN` | Default locale |
| `VITE_SUPPORTED_LOCALES` | `en-IN,hi-IN,mr-IN` | Locale switcher |
| `VITE_SENTRY_DSN` | empty | Do not enable with PHI; no default |

### 6.12 Validation and secrets

At startup the API/worker validate:

- Required vars for the selected profile.
- Postgres connectivity, extensions, migration head and a **rejection of any non-Postgres URL**.
- Redis connectivity.
- Object-store bucket access.
- Keycloak issuer/JWKS reachability (every profile).
- LiteLLM aliases/health and MCP endpoints/allowlists.
- PII/STT/decider health when required by the profile.
- `EMBEDDING_DIM` against the model/table.
- **Feature registry:** schema, unique keys, owner/expiry dates, allowed environments and safety-lock rules; unknown, expired or forbidden overrides fail.
- **Notification channels:** when email is enabled, SMTP host/port/TLS/auth; when Slack is enabled, bot token, both workspace IDs and channel allowlists; when SMS is enabled, provider URL/key; templates are versioned and PHI-checked.
- **Analytics:** metric registry integrity, a valid FX rate/date, the small-cell minimum, and snapshot freshness at readiness.
- **FinOps model:** `config/finops_model.yaml` version matches the metric registry and the published `infra.md` model.
- **Load guard:** `LOAD_TEST_ALLOW_REAL_USERS` cannot be true without the test cohort and abort-guard settings; it is rejected outside an approved environment.
- Dangerous flags and production-incompatible defaults.

The effective config (secrets masked), effective feature flags, model routes and config hash are shown in the admin health view and `/meta`. An invalid config fails startup; the app does not boot into a half-working state.

**Secret generation examples**

```bash
openssl rand -base64 48   # APP_SECRET_KEY / MCP_CONTEXT_SECRET / PII_TOKEN_SECRET
openssl rand -hex 24      # service tokens / passwords for local use
```

Never commit `.env`, `*.pem`, `*.key`, real patient data, provider keys or Keycloak bootstrap passwords. `.gitignore` includes `.env*` (except `.env.example`), `data/`, `*.gguf`, `*.onnx`, `playwright-report/`, `test-results/` and generated object stores.

## 7. Keycloak setup

### 7.1 Realm and clients

Create one realm, `sahyog`, with three clients and one MCP service client:

| Client | Type | Flow | Purpose | Redirect / access |
|---|---|---|---|---|
| `sahyog-web` | Public | Standard flow, PKCE S256 | SPA sign-in | `http://localhost:5705/*`, `http://localhost:5729/*`; exact web origins |
| `sahyog-api` | Bearer-only / resource server | — | API audience | Included in access token `aud` |
| `sahyog-admin` | Confidential | Service account | Least-privilege user/role admin | No browser redirect; service account roles only |
| `sahyog-mcp` | Confidential | Service account | MCP broker/service calls | Scoped service role |

Access-token audience must include `sahyog-api`. Web origins must be exact; do not use `*` outside local development.

### 7.2 Roles

Realm roles map one-to-one to application roles:

`patient`, `caregiver`, `doctor`, `front_desk`, `pharmacist`, `compliance`, `admin`, `service`.

- Do not create a composite "superuser" for convenience.
- Unknown roles are rejected from privileged routes (`FR-AUTH-03`).
- A user may have more than one role only when the access matrix allows it; the UI selects an active role and the server still checks the action.
- Clinic scope is a user attribute/group (`clinic_ids`) or a DB mapping, not a client-supplied header. The application resolves it server-side.
- The patient linkage (`app_user.patient_id`) is stored in the application database, not trusted from a token claim.
- Every role has a scoped chat surface (patient/caregiver, doctor, front desk, pharmacist, compliance, administrator) with tools limited to that role's data (`D-28`).

### 7.3 Token and session settings

| Setting | Suggested | Why |
|---|---|---|
| Access token lifespan | 5–15 minutes | Limits revocation delay |
| SSO session idle | 30 minutes | Clinical workstation hygiene |
| SSO session max | 8 hours | Working day |
| Refresh token rotation | On | Detect replay |
| Revoke refresh token | On | Logout/rotation |
| Brute-force protection | On | Credential attacks |
| OTP for `compliance`/`admin` | Recommended in R1; required in production | `FR-AUTH-11` |
| Step-up OTP for booking | Configurable | Repeated/anomalous booking |

Logout must clear in-memory tokens and TanStack Query caches. Do not store access/refresh tokens in `localStorage`. Use `oidc-client-ts`/`react-oidc-context` with in-memory user storage; a page reload may require a silent renew or a new sign-in, which is acceptable.

### 7.4 Realm import and test users

The repository provides a realm template under `docker/keycloak/` and `scripts/seed-users.sh`. The script is idempotent and uses the `sahyog-admin` service account, not the master admin.

Test users (synthetic only, `@example.test`):

| Username | Role | Clinic | Linked patient | Purpose |
|---|---|---|---|---|
| `patient.priya` | patient | Baner | Priya Sharma | Booking, upload, ask, patient Slack opt-in |
| `patient.arjun` | patient | Baner | Arjun Patil | Second patient scenario (Marathi locale) |
| `caregiver.meena` | caregiver | Baner | consent to Priya | Consent/context banner |
| `doctor.rao` | doctor | Baner | — | Own schedule (Dr. Ananya Rao), W3 review/sign |
| `doctor.kulkarni` | doctor | Baner + Kothrud | — | Second doctor schedule (Dr. Vikram Kulkarni) |
| `frontdesk.imran` | front_desk | Baner | — | Clinic-wide queue/override, front-desk assistant |
| `pharmacist.kavita` | pharmacist | Baner | — | Stock/reservation, pharmacist assistant |
| `compliance.auditor` | compliance | network | — | Audit/export, compliance assistant, no content |
| `admin.ops` | admin | network | — | Config/health/cost, admin assistant, no content |
| `service.mcp` | service | network | — | Service account; no interactive login |

`SEED_DEMO_PASSWORD` is required in every profile; the script refuses to run without it. The same password for every demo user is acceptable only in a synthetic local environment. Change it for staging/acceptance; never use a default password in production.

### 7.5 Slack identity and patient opt-in

- Staff Slack uses `SLACK_STAFF_WORKSPACE_ID`. Staff users are mapped by Keycloak `sub` ↔ Slack user ID in the application database.
- Patient Slack uses a **separate** `SLACK_PATIENT_WORKSPACE_ID` and is off unless the patient opts in.
- Onboarding and settings capture a verified Slack contact; a missing, unverified, non-opted-in or wrong-workspace contact is suppressed with `recipient_missing`, `recipient_unverified`, `opt_in_required` or `workspace_mismatch`.
- An unmapped user never receives a channel-wide mention; the adapter fails closed and the in-app notification remains.
- `add-user.sh --slack-id <id> --slack-audience patient|staff` records the mapping and audits it. A patient cannot be added to the staff workspace by this path.
- No Slack message contains clinical detail, note text, document links or tokens.

### 7.6 Load-test cohort

The load test must behave like a real client while never touching a real patient. `seed-users.sh --load-test <n>` creates a dedicated Keycloak cohort and tagged fixtures:

| Item | Convention | Constraint |
|---|---|---|
| Users | `loadtest.patient01…n`, `loadtest.frontdesk01…`, `loadtest.doctor01…` | Realm roles as normal; user attribute `cohort=loadtest` |
| Patients | `lt_pat_*` with synthetic documents/appointments | Tagged, resettable, never linked to demo/real patients |
| Contacts | `loadtest+...@example.test` and approved test numbers | Resolve to Mailpit/approved test recipients, never a real patient |
| Traffic | `traffic_class=synthetic` | Reported separately from real-user metrics and excluded from adoption/FinOps showback |
| Reset | `./scripts/reset-test-data.sh --cohort loadtest --include-users --confirm` | Removes only tagged cohort rows, objects and Keycloak users; audited |
| Budget | `LOAD_TEST_BUDGET_USD` | Aborts the run when reached |

The cohort authenticates through Keycloak and uses the same public API paths as a real user. Seeding also points each patient row at the actual Keycloak subject, so in-app notifications resolve to the logged-in test user. In a shared environment, `LOAD_TEST_ALLOW_REAL_USERS=true` also requires the real-user SLO guard and an approved window; the run aborts rather than degrade real users. Do not seed the cohort directly into a shared database, and do not reuse a demo patient.

The dry-run guard counts human actors in the last 15 minutes and excludes both load-test subjects and `system:*` background jobs (notification dispatch, retention, ingestion). A dry run passes only when no real user was active in that window (`real_events=0`); otherwise wait or use an approved shared-environment run.

The reset resolves the cohort's actual Keycloak subject IDs before deleting rows, so audit events written by those users are removed with the cohort. Audit remains append-only for every application path: a transaction-scoped `sahyog.synthetic_reset_scope` exemption accepts deletes only for the named synthetic patient IDs and subjects, and every other delete or update still raises. The reset appends its own `test_data.reset` audit event and refuses to run in production without `--allow-protected`.

### 7.7 Admin API script

`scripts/add-user.sh` uses the `sahyog-admin` client credentials to create a user, assign a realm role, set clinic attributes and optionally record a Slack identity. It:

- Refuses to create a user with an unknown role.
- Prints the internal user ID and Keycloak `sub` mapping, never the password.
- Writes an audit/security event.
- Requires `--confirm` for a role change on an existing user.

The app may show a read/invite UI through the same service account, but it never stores or proxies passwords.

### 7.8 Common Keycloak errors

| Symptom | Likely cause | Fix |
|---|---|---|
| `401 invalid issuer` | Token `iss` differs from `KEYCLOAK_PUBLIC_URL`/`JWT_ISSUER` | Set `KEYCLOAK_PUBLIC_URL` to the browser-visible realm URL; keep `KEYCLOAK_URL` internal; avoid `localhost` vs `host.docker.internal` mismatch |
| `401 invalid audience` | `aud` mapper missing | Add `sahyog-api` audience mapper; re-login |
| Redirect loop | Redirect URI mismatch or PKCE misconfigured | Match `VITE_OIDC_REDIRECT_URI` exactly; public client + PKCE S256 |
| CORS error on token endpoint | Web origin missing | Add exact origin; no wildcard in non-dev |
| Admin script 403 | Service account lacks `manage-users`/`view-users` | Add least-privilege roles; do not use master admin |
| Disabled user still writes | Token still valid and no revocation check | Wait one access-token lifetime or add a revocation check for writes (`FR-AUTH-08`) |
| Test user cannot sign in after reset | Keycloak user deleted but app linkage remains | Re-run `seed-users.sh`; verify `app_user.keycloak_sub`; do not hand-edit tokens |

## 8. Models and LiteLLM

### 8.1 Purpose-based routing

Application code requests a **purpose**, never a provider model ID. `config/models.yaml` maps each purpose to an alias, provider route, egress class, timeout, fallback and token budget. An administrator can change one purpose's route with validation and audit; no code change (`D-24`, `FR-GW-02`).

**Build status.** Purpose routes are live. `intent` prefers OpenDecider via `mcp-decider` with a labelled keyword fallback (G-29). `pii` is the proven composite engine; the gateway still fails closed unless `engine=composite` (G-28) and egress stays off (G-19). `stt` uses faster-whisper when weights are present (G-05 residual for hi/mr). Deterministic red-flag rules remain authoritative. `rag_answer`, `w3_draft`, `summary`, `title`, `insights` and `embedding` use the LiteLLM gateway.

| Purpose | Default alias | Default route | Egress class | Notes |
|---|---|---|---|---|
| `intent` | `intent` | OpenDecider via `mcp-decider` | `local` | Host Ollama OpenDecider when reachable; keyword fallback labelled (G-29) |
| `red_flag_second_pass` | `red_flag` | OpenDecider/rules + `local_small` | `local` | Deterministic rules are authoritative for safety |
| `rag_answer` | `main` | OpenRouter (de-identified) | `external_deidentified` | Falls back to `local_main`; otherwise hand-off; egress off by default |
| `w3_draft` | `local_main` | Ollama | `local` | Identified processing; never external |
| `summary` | `local_main` | Ollama | `local` | X-01 nursing summary when `FEATURE_X01_NURSING_SUMMARY` is on (G-13) |
| `title` | `title` | `local_small` | `local` | Session titles; neutral fallback |
| `judge` | `judge` | Configured eval route | Eval only | Uncalibrated against human review; not a release gate alone (G-16) |
| `embedding` | `embed` | Ollama `bge-m3` | `local` | Ingestion/retrieval |
| `stt` | `stt` | `mcp-stt` faster-whisper | `local` | Local Whisper; EN WER measured; hi/mr residual (G-05) |
| `pii` | `pii` | `mcp-pii` composite | `local` | Composite proven; gateway requires it before any egress (G-28) |
| `insights` | `insights` | `local_main` | `local` | Scheduled local-model drafts with evidence; deterministic rules are the fallback (G-30) |

A purpose without a route fails validation. A route that would send identified text to an external alias is rejected at startup, and the application gateway enforces PII fail-closed before egress. The LiteLLM proxy has no independent de-identification guard (G-28).

### 8.2 Mac M4 Pro model set

The pilot host has 26 GB unified memory. Use purpose-specific small models, not one model for everything (`Q-10`, `D-19`):

| Role | Pinned-default candidate | Approx. memory | Why |
|---|---|---:|---|
| Local main (W3/summary/insights) | 7–8B multilingual instruct, Q4_K_M | 5–6 GB | Fits with KV cache and leaves room for services |
| Local small (titles/clarification) | 3–4B instruct, Q4 | 2–3 GB | Fast, low-memory classification/summaries |
| Embeddings | `bge-m3` | 1–2 GB | 1024-d multilingual; matches `EMBEDDING_DIM` |
| STT | `faster-whisper` small int8 | 1–1.5 GB | CPU/Metal; transcript upload fallback |
| PII | GLiNER-PII large + Presidio + optional Privacy Filter | 2–3 GB | Local; fail-closed egress |
| Decider | OpenDecider-small Q4/Q8 | 1–2 GB | Typed decision; not a chat model |

These are **candidates**, not claims. The model spike measures quality, latency, language coverage and memory on the actual host, then pins model tags/revisions in `config/models.yaml`. Example tags in `.env` are illustrative; do not silently change an alias without an eval run and a recorded decision. Composite PII, OpenDecider and Whisper are proven in-repo (G-28/G-29/G-05); still re-verify after image recreate and keep egress off until sign-off.

### 8.3 Ollama

Host install:

```bash
ollama serve
ollama pull bge-m3
ollama pull qwen2.5:7b-instruct-q4_K_M     # example; pin after the model spike
ollama pull qwen2.5:3b-instruct-q4_K_M     # example small model
ollama list
```

`scripts/start.sh` does not start an Ollama container. Point `OLLAMA_BASE_URL` at the host daemon (`http://host.docker.internal:11434` from Compose). The compose profile `ollama` exists only if you explicitly add it to `COMPOSE_PROFILES`; do not run that container and host Ollama at the same time.

**Memory cap (G-49).** Unbounded Desktop context (e.g. 262k) can allocate tens of GiB of KV cache. Cap the host daemon with `./scripts/ollama-memory-cap.sh` (`OLLAMA_CONTEXT_LENGTH=8192`, `OLLAMA_MAX_LOADED_MODELS=1`), quit/reopen Ollama, and keep the Desktop context slider ≤ 8k. Virtual address space may still look large on macOS; the goal is ~≤16 GiB physical RSS.

On the Mac pilot, run Ollama on the host so it uses Metal and unified memory.

### 8.4 OpenRouter

1. Create a key with a spend limit.
2. Set `OPENROUTER_API_KEY` in `.env` or the vault (never the frontend).
3. Do **not** set `EXTERNAL_EGRESS_ENABLED=true` until DPDP/security sign-off (G-19). Composite PII is proven (G-28); the gateway still fails closed when the engine is unhealthy or residual identifiers remain.
4. Before enabling egress, obtain the security sign-off, then run a W1/W2 smoke with a de-identified fixture and check LiteLLM's spend log and the application `usage_record`.
5. Set a monthly budget and alert; do not run evals or load tests against the paid route unless budgeted.

If OpenRouter is unavailable or blocked, the router falls back to `local_main` if configured. If no local model is available, the workflow degrades to a human hand-off; it does not fabricate an answer.

### 8.5 LiteLLM proxy

`config/litellm.yaml` contains:

- The model list with aliases and provider prefixes, and purpose routes referenced from `config/models.yaml`.
- Router settings: fallbacks, retries, timeout, circuit breaker.
- MCP servers (broker URL + service key).
- Spend logging to the LiteLLM database.
- Virtual keys/scopes for API, worker, MCP broker and evals.

The LiteLLM proxy has no pre-call PII guardrail; the application gateway is the fail-closed control (G-28).

Validate before starting:

```bash
docker compose run --rm litellm --config /app/config/litellm.yaml --health
curl -s http://localhost:5708/health/liveliness
curl -s -H "Authorization: Bearer $LITELLM_MASTER_KEY" http://localhost:5708/v1/models | jq
```

Do not expose the master key to the browser. Issue a virtual key per service; rotate on a schedule. The app uses the OpenAI-compatible endpoint; no provider SDK is allowed in product code (`MC-13`).

### 8.6 Embeddings and dimension

- `bge-m3` produces 1024-d vectors by default; `EMBEDDING_DIM=1024` must match the table.
- Changing the model or dimension requires a re-embed migration and a full ingest replay; it is not a config-only change (`FR-DATA-13`).
- Embeddings are cached by content hash; a re-upload of identical bytes does not create duplicates.
- If embeddings fail, ingestion fails visibly; it never indexes a partial document silently.

### 8.7 PII stack

**Build status.** The composite engine is **proven** (G-28): Presidio + spaCy + GLiNER on `mcp-pii` / `sahyog-api:local` report `engine=composite` and `not_clinical_grade=false` ([mcp-pii-detect-probe.json](./evidence/mcp-pii-detect-probe.json)). The API `PiiGate` still rejects a fallback engine, a non-clinical-grade result or residual identifiers before any external chat alias. `EXTERNAL_EGRESS_ENABLED` remains `false` until DPDP/security sign-off (G-19). The LiteLLM proxy has no independent de-identification guard; the application gateway is the enforcement point.

Composite stack:

1. Presidio with custom Indian recognisers (phone, address, ID formats, names, Hindi/Marathi script).
2. GLiNER-PII for zero-shot entity detection.
3. Optional Privacy Filter if the model is available and verified.
4. Deterministic rules for known direct identifiers (regex fallback only when composite cannot load).

Tokenisation replaces direct identifiers with reversible tokens; the token map stays in-boundary. If the detector fails or times out, external egress is blocked.

```bash
./scripts/test.sh --pii
```

Do not enable `EXTERNAL_EGRESS_ENABLED` or describe this as a clinical-grade / regulatory PII clearance. Re-verify `engine=composite` after every `mcp-pii` recreate.

### 8.8 STT and OCR

**Build status.** `mcp-stt` in `core`/`full` uses faster-whisper when weights are present. English LibriSpeech WER is measured (G-05); Hindi/Marathi/code-mixed clinical speech and Devanagari OCR CER are not. If weights or the adapter are unavailable, completion fails with `stt_unavailable` and does not fabricate a transcript. W3 remains usable through the manual transcript entry path. OCR is not an automated pipeline in this build.

Check the truthful state:

```bash
curl -s http://localhost:5716/healthz
./scripts/smoke.sh --stt
```

### 8.9 OpenDecider

**Build status.** The OpenDecider model adapter is **not bundled** (G-29). `mcp-decider` exposes a deterministic keyword intent classifier plus the shared red-flag rules. Responses state the engine; red-flag safety never depends on the decider. Do not present the classifier as an OpenDecider model call.

The target is a local typed-decision model exposed as `mcp-decider`, not a chat alias: trained prompt format, typed decision request, advisory output, deterministic rules first, and a local fallback if the model is unavailable.

## 9. Data estate

### 9.1 Sources

Five public sources and the generated layer:

| Source | Rows (baseline) | Licence | Use |
|---|---|---|---|
| Medical Appointment No Shows (Kaggle/OpenML 43439) | 110,527 | CC BY-NC-SA 4.0 | Scheduling/no-show signal |
| Medical Transcriptions (Kaggle `tboyle10/medicaltranscriptions`) | ~5,000 notes | Check and record | Dictation/transcript seed |
| Disease Symptom Prediction (Kaggle `itachi9604/disease-symptom-description-dataset`) | ~4,900 | Check and record | Symptom→specialty signal |
| A-Z Medicine Dataset of India (Kaggle `shudhanshusingh/az-medicine-dataset-of-india`) | 250,000+ | Check and record | Formulary/stock reference |
| Healthcare Dataset, synthetic (Kaggle `prasad22/healthcare-dataset`) | ~55,000 admissions | Check and record | Patient/encounter master |
| Generated layer | 500 doctors, 480k slots, 2,000 PDFs, 300 transcripts | Team-owned | Everything the public sets lack |

Exact row counts, licences and checked dates belong in `docs/data-contracts/` and the D4 contracts before any row is used. Baseline counts are context, not verification. The Kaggle datasets are for demonstration only (`Q-13`); do not redistribute them or use them commercially.

### 9.2 Sample profile (offline)

The sample profile is synthetic and requires no Kaggle login:

```bash
./scripts/load-data.sh --sample
./scripts/seed-users.sh --load-test 5   # Patient rows for PERF-02 / load cohort
./scripts/generate-synthetic.sh --doctors 50 --slots 5000 --pdfs 50 --transcripts 20 \
  --patient-cohort both --ingest
```

It creates:

- Deterministic weekday appointment slots against doctors derived from the demo dataset (calendar horizon scales with `--slots`).
- Synthetic patients with linked users, including the demo personas and optional `loadtest.*` patients.
- Extractable synthetic PDFs in object storage for W2 ingestion (add `--ingest` to run the real embedding path).
- Use `--patient-cohort loadtest` (or `both`) so PDFs land on the load-test patients for NFR-PERF-02.
- Synthetic encounters, transcripts and turns for W3 safety checks; no clinical note is signed.
- A stock CSV with source/time (pharmacy catalogue size is separate from appointment/PDF generation).

Script caps align with NFR-SCALE-02 (up to 500 doctors, 480k slots, 2k PDFs, 2k transcripts). Defaults stay small for laptop demos; a full-size run is slow on P hosts and should be staged, then grids (including pharmacy) re-measured. X-01 nursing eval fixtures live under `evals/sets/nursing_x01.jsonl` (shape harness); clinical-graded live drafts remain residual (G-13).
- A red-team PDF and PII fixtures in the eval set only.

### 9.3 Full public-data load

```bash
# Requires Kaggle credentials in the operator environment (never in the repo).
# Invented row counts are forbidden; seed/sample is not a substitute for these sources.
./scripts/load-data.sh --download --source all
./scripts/load-data.sh --source appointments --source notes --source symptoms --source medicines --source patients
./scripts/load-data.sh --validate
```

`scripts/load_public_sources.py` (invoked by `load-data.sh`):

1. Downloads each enabled public source via the Kaggle CLI into `data/raw/<id>/` (gitignored).
2. Measures SHA-256 and CSV row counts from the actual files; updates `docs/data-contracts/`.
3. Writes `docs/evidence/public-source-inventory-*.json` with status `passed` or `incomplete`.
4. Refuses to run `--download` without credentials rather than fabricating rows.

Application ingest (Pydantic validation, specialty catalogue map, `synthetic=true` on generated-layer rows) remains a follow-on after inventory. Do not commit raw datasets.

### 9.4 Data quality checks

| Check | Pass criterion |
|---|---|
| Row counts | Before/after counts with drop reasons |
| Dates | Zero discharge-before-admission; appointment dates within range |
| Duplicates | Document `(patient_id, sha256)` unique; appointment slot unique |
| Specialty mapping | 100% mapped or explicitly flagged |
| Generated rows | `synthetic=true`; prompt/seed version present |
| PII fixtures | Present only in the eval/red-team set; never in seed/demo data |
| Load-test fixtures | Tagged `cohort=loadtest`; excluded from demo counts, adoption metrics and showback; resettable without touching demo rows |
| Language metadata | Every chat/note/eval row has a detected/provided language tag; mixed-language fixtures present |
| Embedding dimension | Matches `EMBEDDING_DIM` and table |
| Licence | Recorded with source and checked date |

### 9.5 Reset and go-live erasure

Two distinct operations:

```bash
# Remove only tagged test/load data and cohort users; keeps schema
./scripts/reset-test-data.sh --cohort loadtest --include-users --confirm

# Optional: also clear stored evaluation runs (release evidence is retained by default)
./scripts/reset-test-data.sh --cohort loadtest --include-eval-artefacts --confirm

# Full destructive reset for a clean benchmark; drops/recreates schema, re-migrates and seeds
./scripts/reset-db.sh --confirm
```

`reset-test-data.sh` is idempotent, audited, refuses without `--confirm`, and never deletes rows that are not tagged as synthetic/test. `reset-db.sh` is destructive and requires an explicit confirmation; `--objects` is a separate confirmation for object storage. Before go-live, the reset job proves the test dataset is erasable (`D-25`, `FR-OPS-14`).

## 10. Object storage

### 10.1 Buckets

| Bucket | Contents | Visibility | Lifecycle |
|---|---|---|---|
| `sahyog-documents` | Uploaded patient documents | Private | Retention by record policy; delete cascades |
| `sahyog-audio` | Consultation audio | Private | Delete within 24 h; alert on failure |
| `sahyog-exports` | Compliance exports | Private | 24 h |
| `sahyog-audit-anchors` | Daily Merkle roots | Private, object lock where available | 1 year+ |
| `sahyog-eval` | Synthetic eval artefacts | Private | Eval retention |
| `sahyog-backups` | Encrypted DB/object backups | Private | 30 days rolling |

Create buckets idempotently:

```bash
./scripts/start.sh --profile core   # calls the bucket bootstrap
# or
AWS_ACCESS_KEY_ID="$S3_ACCESS_KEY" AWS_SECRET_ACCESS_KEY="$S3_SECRET_KEY" aws --endpoint-url http://localhost:5719 s3 ls
mc mb --ignore-existing local/sahyog-documents local/sahyog-audio local/sahyog-exports local/sahyog-audit-anchors local/sahyog-eval local/sahyog-backups
mc anonymous set none local/sahyog-documents local/sahyog-audio local/sahyog-exports local/sahyog-audit-anchors local/sahyog-backups
```

Local S3Proxy does not enforce bucket lifecycle rules; the scheduler runs explicit deletion/retention jobs. Production managed S3 should still apply lifecycle policies.

### 10.2 Presigned uploads

1. The browser calls `POST /api/v1/documents/uploads` with filename, size, content type and patient context (server-derived).
2. The API creates a pending document, object key and short-lived presigned PUT (default 300 s).
3. The browser uploads directly to S3/S3Proxy.
4. The browser calls `POST /api/v1/documents/{id}/complete`; the API verifies HEAD (size/type/hash), runs the ClamAV INSTREAM scan before acceptance, records the verdict/engine, quarantines a positive or fails closed when required, then creates the ingestion job and enqueues it.
5. The worker downloads the accepted object, sniffs the real type, parses, chunks and embeds; it does not decide whether the object is safe to accept.
6. A failed/abandoned upload is marked for cleanup; no orphan document row or object.

Bucket CORS must allow the web origin, `PUT`, and the required headers. Do not enable public read.

## 11. Database and migrations

### 11.1 Postgres (the only database)

- Image: `pgvector/pgvector:pg16` or a managed Postgres 16+ with the extension.
- One cluster, separate databases/roles:
  - `care` — application; role `app` read/write domain tables, insert/select audit (no update/delete).
  - `langfuse` — separate database; Langfuse's own role.
  - `keycloak` — separate database/schema preferred.
  - `litellm` — spend/usage tables or its own database.
  - `readonly` — optional analytics.
- Never use the superuser for the app.
- Extensions: `vector`, `pg_trgm`, `pgcrypto`, `btree_gin`; readiness fails if missing.
- Pilot settings: `shared_buffers=1GB`, `work_mem=32MB`, `max_connections=100` (see [architecture.md](./architecture.md#67-postgres-only-database-profile)).

```bash
./scripts/migrate.sh
./scripts/migrate.sh --revision head
```

Migrations are forward-only. An empty database migrates to head; CI repeats this on Postgres only. A destructive change needs a backup and an expand/contract plan. There is no `--sqlite` option and no dialect switch.

### 11.2 Seeds, reset and test data

```bash
./scripts/seed-users.sh
./scripts/load-data.sh --sample
./scripts/generate-synthetic.sh
./scripts/reset-test-data.sh --cohort loadtest --confirm
./scripts/reset-db.sh --confirm    # destructive; explicit confirmation
```

`reset-db.sh` drops/recreates the schema, re-runs migrations and seeds; it refuses without `--confirm` and never touches an object store unless `--objects` is also passed with confirmation.

### 11.3 Backup

```bash
./scripts/backup.sh --out /backups/care-$(date +%Y%m%d-%H%M) \
  --encrypt age1replace-with-your-recipient
```

The backup includes the application database plus the LiteLLM and Langfuse databases when present (`pg_dump` custom format), all six object buckets, the Keycloak realm export and the versioned config. It records a manifest with row/object counts, SHA-256 hashes, the Alembic revision, image/version metadata and a PHI warning. The output directory must be outside the repository and is created mode `0700`; pass `--skip-objects` or `--skip-keycloak` for a partial backup, and `--encrypt` to leave only an `age` archive. The archive contains PHI and Keycloak client secrets; encrypt it before it leaves the host. A measured restore drill remains required before a production claim (`MC-24`, G-11).

## 12. Running the stack

### 12.1 Scripts

| Script | Purpose | Common options |
|---|---|---|
| `scripts/start.sh` | Validate config, start a profile, wait for readiness, print URLs | `--profile minimal / core / full`, `--local` (host API/UI/workers), `--with-melt`, `--no-build`, `--seed`, `--no-workers` |
| `scripts/stop.sh` | Graceful stop; keep volumes | `--service <name>` |
| `scripts/restart.sh` | Stop/start one service or all | `--service <name>` |
| `scripts/status.sh` | Health/readiness/version summary | `--json` |
| `scripts/logs.sh` | Tail redacted logs | `--service`, `--since`, `--no-follow` |
| `scripts/dev.sh` | Host API (agents) + Vite + ARQ workers; deps in Docker | `--profile`, `--local`, `--no-infra`, `--no-api`, `--no-web`, `--workers` / `--no-workers` |
| `scripts/migrate.sh` | Alembic upgrade head; explicit | `--revision` |
| `scripts/seed-users.sh` | Create synthetic users/roles/clinics | `--realm`, `--force`, `--load-test <n>` |
| `scripts/add-user.sh` | Invite/add one user via Keycloak Admin API | `--role`, `--clinic`, `--slack-id`, `--slack-audience`, `--confirm` |
| `scripts/load-data.sh` | Load public sources or sample | `--sample`, `--source`, `--download`, `--validate` |
| `scripts/generate-synthetic.sh` | Doctors/slots/PDFs/transcripts; optional real ingestion; SCALE-02 caps | `--doctors`, `--slots`, `--pdfs`, `--transcripts`, `--patient-cohort demo\|loadtest\|both`, `--seed`, `--ingest` |
| `scripts/load_test.sh` | Python/httpx load profile; real Keycloak auth; `--rate` in requests/hour | `--profile r1 / r2 / r3`, `--rate`, `--burst`, `--duration`, `--cohort-size`, `--auth keycloak`, `--traffic-class synthetic`, `--allow-real-users`, `--abort-on-real-slo`, `--budget-usd`, `--include-llm`, `--patients-only`, `--dry-run`, `--summary`, `--reset-test-data` |
| `scripts/eval.sh` | Deterministic safety gate; optional RAGAS/DeepEval adapters | `--suite w1 / w2 / w3 / x01 / all`, `--alias`, `--framework ragas / deepeval / deterministic`, `--stub`, `--no-persist`, `--report`, `--quiet` |
| `scripts/analytics-refresh.sh` | Rebuild analytics snapshots for a date range; dry-run default | `--from`, `--to`, `--live`, `--metric` |
| `scripts/export-finops.sh` | Aggregate-only showback export with price/FX provenance | `--from`, `--to`, `--format csv / json` |
| `scripts/flags.sh` | List/validate effective flags; diff env vs registry | `--validate`, `--json`, `--diff` |
| `scripts/smoke.sh` | End-to-end smoke on a running stack | `--profile`, `--sources`, `--notifications`, `--analytics`, `--flags`, `--stt`, `--summary`, `--skip-ui` |
| `scripts/backup.sh` | Backup Postgres/telemetry/objects/Keycloak/config with counts and hashes | `--out`, `--encrypt`, `--skip-objects`, `--skip-keycloak`, `--note` |
| `scripts/restore.sh` | Restore into an empty environment and verify | `--from`, `--identity`, `--confirm`, `--skip-objects`, `--skip-keycloak`, `--skip-smoke`, `--allow-existing-realm` |
| `scripts/retention.sh` | Purge/verify retention jobs | `--dry-run` (default), `--live` |
| `scripts/export-audit.sh` | Compliance export | `--from`, `--to`, `--actor`, `--resource` |
| `scripts/test.sh` | Unit/integration/contract tests | `--postgres`, `--pii`, `--authz`, `--contracts`, `--i18n`, `--e2e` |
| `scripts/lint.sh` | Ruff/mypy/import boundaries/tsc; Semgrep only if installed (not a delivered gate, G-27) | `--fix` |
| `scripts/reset-db.sh` | Destructive reset (explicit) | `--confirm`, `--objects` |
| `scripts/reset-test-data.sh` | Remove tagged test/load data only | `--cohort`, `--include-users`, `--include-eval-artefacts`, `--allow-protected`, `--confirm`, `--dry-run` |
| `scripts/k8s-deploy.sh` | Render/apply a Kustomize overlay; render-only unless `--confirm` | `--overlay pilot / production`, `--namespace`, `--output`, `--confirm` |
| `scripts/k8s-status.sh` | Kubernetes rollout/health summary | `--namespace` |

All scripts use `set -euo pipefail`, fail non-zero, print a redacted summary and are idempotent where possible. Destructive actions require an explicit flag and confirmation.

### 12.2 Start sequence

**Compose mode** (`./scripts/start.sh`):

1. Validate `.env`, the selected profile, the feature registry and the model-purpose routes.
2. Validate notification configuration for every enabled channel and the analytics/FinOps model version.
3. Start data dependencies (Postgres, Redis, S3Proxy, Keycloak, Mailpit).
4. Wait for health.
5. Run migrations explicitly.
6. Import/update the Keycloak realm idempotently.
7. Seed an empty demo or test cohort if requested.
8. Start LiteLLM with validated config.
9. Start MCP servers/broker.
10. Start API / web / worker / scheduler containers.

**Local host-app mode** (`./scripts/start.sh --local` or `./scripts/dev.sh`):

1–7 as above for dependencies (no app-tier image build required).
8. Stop Compose `api` / `web` / `worker` / `scheduler` if they hold host ports.
9. Rewrite container DNS in the process environment to `localhost:<port>`.
10. Start host uvicorn (agents in-process), ARQ worker + scheduler, and Vite HMR.
11. Start worker/scheduler.
12. Wait for readiness, including analytics snapshot freshness and channel health.
13. Start web (nginx).

`start.sh` runs migrations as an explicit start step, never on API boot. This prevents an API replica from mutating a shared schema during a rolling start.

### 12.3 Health and readiness

```bash
curl -s http://localhost:5706/healthz | jq
curl -s http://localhost:5706/readyz | jq
./scripts/status.sh --json | jq
```

`/healthz` proves the process is alive. `/readyz` proves required dependencies are usable and migrations are at head. Readiness is truthful: it does not return ready when Postgres, Redis, the object store, Keycloak JWKS or the PII service (for egress) are unavailable. LiteLLM/MCP/decider degradation may return a degraded state, not a false ready. Enabled notification channels and analytics snapshots are reported as degraded with a reason, not silently green; a stale snapshot never renders as a zero. The effective feature flags, model routes and config hash are exposed by `/meta` and the admin health view.

### 12.4 Shutdown and reset

```bash
./scripts/stop.sh                 # keep volumes
./scripts/stop.sh --volumes       # destructive; explicit confirmation
```

On SIGTERM the API stops accepting runs, cancels/checkpoints in-flight runs, drains SSE, lets workers finish or requeue, and closes connections. A forced kill may lose an in-flight task but not a durable checkpoint.

## 13. Users, roles and demo accounts

### 13.1 Seed

```bash
export SEED_DEMO_PASSWORD='<local-only-strong-password>'
./scripts/seed-users.sh
```

The script creates the realm roles/clients if missing, the synthetic clinics, the demo users in §7.4, and prints a summary with no passwords. It is idempotent; `--force` resets demo profiles only, never production users.

### 13.2 Add a user

```bash
./scripts/add-user.sh \
  --username dr.new \
  --email dr.new@example.test \
  --first-name New \
  --last-name Doctor \
  --role doctor \
  --clinic clinic_pune_central \
  --confirm
```

For a patient with Slack enabled:

```bash
./scripts/add-user.sh \
  --username patient.new \
  --email patient.new@example.test \
  --role patient \
  --clinic clinic_pune_central \
  --slack-id U012345 \
  --slack-audience patient \
  --confirm
```

The script validates the role/clinic/audience, uses the `sahyog-admin` service account, maps the Keycloak `sub` to an internal user, and writes an audit event. It does not log passwords.

### 13.3 Role smoke matrix

| User | Can | Cannot |
|---|---|---|
| `patient.priya` | Own chat, own records, book/cancel, ask own record, opt in to Slack | See another patient, staff grids, audit, config |
| `caregiver.meena` | Consented patient's records/appointments/chat context | Access after expiry/revocation; switch without consent |
| `doctor.rao` | Treating patients' records, W3 draft/sign, own queue, doctor assistant | Admin/config, unrelated patients, chat bodies of others |
| `frontdesk.imran` | Clinic appointments, queue, override/cancel/reschedule, front-desk assistant | Clinical notes, another clinic, audit export |
| `pharmacist.kavita` | Stock, reservations, signed prescription lines, pharmacist assistant | Full notes, admin, other clinics |
| `compliance.auditor` | Audit query/export, compliance analytics, compliance assistant, metadata | Clinical content, chat bodies, config writes |
| `admin.ops` | Users/config/health/cost metadata, feature flags, operational analytics and FinOps, admin assistant | Clinical content, chat bodies, note reads |
| `loadtest.*` | Synthetic cohort APIs and tagged fixtures | Any demo/real patient, staff grids, analytics, config |

Analytics is role-scoped: `admin` sees operational and FinOps metrics; `compliance` sees compliance/audit posture; neither sees note or chat bodies. Insights are advisory and read-only: the scheduler persists local-model drafts with evidence and accept/reject actions, while deterministic rules are the fallback (G-30). Every role's assistant is limited to the same data scope as its human surface.

Run the matrix test after seeding:

```bash
./scripts/test.sh --authz
```

## 14. Frontend development and build

### 14.1 Local dev

```bash
npm --prefix apps/web install
npm --prefix apps/web run dev
```

Vite proxies `/api` to `VITE_API_BASE_URL`; the OIDC redirect must match Keycloak. Every profile uses Keycloak; there is no synthetic user switcher.

### 14.2 Build and serve

```bash
npm --prefix apps/web run build
npm --prefix apps/web run preview
```

The production image builds the SPA and serves it with nginx. The initial authenticated route JS budget is under 300 KB gzipped excluding lazy chunks (`FR-UI-11`); check with the bundle report.

### 14.3 Themes, responsive and i18n

- Theme is applied before first paint via a class on `<html>`; no flash.
- The left nav becomes a drawer under the mobile breakpoint; chat composer stays usable at 360 px.
- All UI strings are in locale files; `en-IN`, `hi-IN` and `mr-IN` ship from R1 (`D-10`). Mixed-language input is accepted; the detected/provided language is stored as metadata and passed to prompts, agents and traces.
- Notifications and safety copy have Hindi and Marathi versions; clinical-content machine translation is not presented as clinically validated.
- No PHI in URLs, localStorage, analytics or console.
- Icon-only buttons have an accessible name and a tooltip on hover/focus; Escape dismisses the tooltip.
- Markdown is rendered with a strict allowlist; raw HTML is not rendered; external links use `rel="noopener noreferrer"`.
- Every agent answer and W3 draft renders the shared Sources panel: document, tool, memory, conversation, rule or general, with `resolved`/`stale`/`missing`/`forbidden` state. Memory is never presented as clinical evidence; an unresolved source cannot be hidden behind a generic citation.
- Analytics tabs are keyboard-navigable, state `as_of`/freshness, and provide an accessible table alternative to every chart. A stale or failed refresh shows stale/unknown, not zero.

Known i18n gaps (transliteration, mixed-script retrieval normalization, model quality by language, notification template coverage beyond en/hi/mr) and their mitigations are tracked in [gaps.md](./gaps.md).

### 14.4 Browser support

Latest two versions of Chrome, Edge, Firefox and Safari; iOS Safari and Android Chrome for patient flows. Run `scripts/test.sh --e2e` against a disposable Compose stack: the Playwright suite covers Keycloak sign-in, chat/provenance, booking, scribe, analytics, axe checks, the dark theme and a 360 px viewport (G-26). It is not an automated CI job in this repository, so record the report with the release evidence.

## 15. Backend, workers and scheduler

### 15.1 Local API

```bash
uv sync --all-packages
uv run uvicorn app.main:app --reload --port 5706
```

The API requires config validation; a missing dependency fails fast. Prefer `./scripts/start.sh --local` or `./scripts/dev.sh` so dependencies stay in Docker and host env URLs are rewritten.

### 15.2 Worker

```bash
uv run arq app.worker.WorkerSettings
```

The worker runs document ingestion (with an in-process fallback if Redis is unavailable) and notification dispatch on `sahyog:worker` (`ARQ_WORKER_QUEUE`). It is idempotent by job ID/content hash, retries with capped backoff, and records a terminal status. A queue backlog is visible in the admin health view. A failed channel copy never rolls back the booking, signature or record write. Scheduled retention, consent, analytics, anchor and reconciliation jobs live in the separate scheduler (core/full) on `sahyog:scheduler` (`ARQ_SCHEDULER_QUEUE`); the queues are separate so neither process claims a job it cannot run. `ops.backup` / `ops.stock_import` are registered and fail visibly when unconfigured; wire `BACKUP_OUT_DIR` for scheduled encrypted backup (G-30).

### 15.3 Scheduler

```bash
uv run arq --cron app.scheduler.WorkerSettings
```

**Build status.** The scheduler runs audio retention every 15 minutes, chat-session retention at 02:15, consent expiry at 02:30, an analytics snapshot at minute 5, spend reconciliation at minute 10, a staleness check at minute 20, audit anchoring at 02:45 and insight generation at 03:10. The always-on worker dispatches notifications every minute on its own queue. Every run writes a `job_runs` row exposed on `/metrics` (`sahyog_job_*`); `SahyogJobStale` / `SahyogJobFailures` are loaded in `full`. `ops.backup` / `ops.stock_import` register and fail visibly when unconfigured — set `BACKUP_OUT_DIR` for scheduled age-encrypted backup (G-30). A stale analytics tile is surfaced as stale, not filled with zero.

```bash
./scripts/analytics-refresh.sh --from 2026-10-01 --to 2026-10-25 --live
./scripts/backup.sh
```

## 16. Telemetry, cost and dashboards

### 16.1 Langfuse

- Self-hosted in `core`/`full`, using its own Postgres database on the shared cluster; no ClickHouse dependency (`D-23`, ADR-15).
- Content capture off (`LANGFUSE_CAPTURE_CONTENT=false`).
- **Build status:** Langfuse web/worker and its health endpoint work, and the API exports per-run agent traces to Langfuse's ingestion API. The exporter refuses to run when content capture is enabled; span metadata has identifiers, counts, hashes and durations only, with `input`/`output` null. HTTP request spans still go to the OTel collector. A verified scribe trace contains `scribe.safety`, `pii.pregate`, `llm.complete`, `scribe.draft` and `scribe.ground`; the trace ID is stored on chat/scribe/audit records and shown in the UI (G-23).
- Each run must have a trace with node/tool/model spans and no PHI in span attributes; the trace ID links to audit events. Export is sampled by `TRACE_EXPORT_SAMPLE_RATIO` and best-effort.
- Retention metadata 30 days; no prompts/answers in traces unless explicitly masked and approved.

Check:

```bash
curl -s http://localhost:5721/api/public/health
./scripts/smoke.sh --telemetry     # reports collector/telemetry presence; does not prove a Langfuse trace
```

### 16.2 OpenTelemetry, Prometheus and Grafana

- The API emits OTLP HTTP spans (method, route, status, traffic class) and HTTP metrics to the collector; attributes are redacted. The export is OTLP-compatible with any MELT backend (`D-22`).
- The collector's trace pipeline writes to its debug exporter; the API separately exports per-run agent spans to Langfuse (metadata only, content capture off). The metric pipeline exposes Prometheus in `full`. Graph/node/tool/model spans are instrumented (G-23).
- `full` adds Prometheus/Grafana dashboards for p95, error rate, queue depth, model usage/cost, red-flag rate and ingestion status.
- `melt` adds ClickHouse as an optional demonstration backend; Langfuse remains on Postgres.
- Alerts: scope leak, audit failure, PII block, red-flag failure, LiteLLM/DB/Keycloak outage, budget threshold, queue backlog, audio deletion failure. Runbook coverage for these alerts is partial (G-25).

### 16.3 Cost

- Every LLM/embedding call writes a `usage_record` with provider, model, alias, purpose, units, price version and attribution. STT has no call path in this build (G-29).
- `config/prices.yaml` has effective dates; no price is hard-coded in code.
- Dashboards show cost per run/workflow/consultation and the formula.
- Budgets: global, role/user, session; 80% alert and 100% hard stop or local-model fallback (LiteLLM enforces the gateway budget; app budgets are advisory).
- LiteLLM spend reconciliation with `usage_record` is implemented as a read-only comparison. The FinOps API returns `matched`, `partial`, `variance` or `insufficient_data` with matched/unmatched counts and variance; the verified local run is `partial` (19 app calls, 32 gateway calls, 12 matched, 0 variance on matched calls). Unmatched calls remain visible, so do not present showback as billing-grade until they are reviewed and automated variance alerting exists (G-31, G-25).

Check:

```bash
./scripts/smoke.sh --cost
# Admin → Costs: verify alias, purpose, price version, date and per-run cost.
```

### 16.4 Analytics, evaluations and FinOps

The Analytics area is served from versioned metric definitions (`config/metrics.yaml`) and aggregate queries. The scheduler captures a snapshot at minute 5 and a staleness check at minute 20; the manual refresh script remains for ad-hoc ranges (G-30). Six tabs are expected: Overview, Quality & safety, Compliance posture, Evaluations, FinOps and AI insights. Every tile exposes its definition, `as_of`, freshness and drill-down; patient-level counts below `ANALYTICS_SMALL_CELL_MIN` are suppressed or aggregated.

```bash
./scripts/analytics-refresh.sh --from 2026-10-01 --to 2026-10-25 --live
./scripts/export-finops.sh --from 2026-10-01 --to 2026-10-25 --format csv
./scripts/smoke.sh --analytics
```

FinOps: confirm every billable unit is attributable to clinic/workflow/alias/provider/session; budgets show 80% alerts and 100% hard stop or local fallback; unit economics show cost per booking/answer/signed note/active user/1,000 requests with formula, currency, FX rate and price date; showback export is aggregate-only and audited. LiteLLM spend reconciliation reports matched/unmatched counts and variance; the local evidence run is `partial` with zero variance on matched calls (G-31). Do not sign a reconciliation item while unmatched gateway calls remain and automated variance alerting is absent (G-25). The what-if workspace loads the same versioned model as [infra.md](./infra.md) (`config/finops_model.yaml`), supports cloud/colo/on-prem scenarios, growth in users/volumes and profitability, and labels every result an estimate (`ANL-AC-06`, `MC-33`).

**Build status.** With the scheduler running, AI insights are persisted drafts generated through the local alias (`generator=local_model`, `ai_generated=true`, model alias recorded) with evidence, and can be accepted or rejected through `POST /analytics/insights/{id}/decision` with audit. Without a successful scheduled generation, the API falls back to deterministic rules and labels them. Recommendations remain advisory and cannot change a prompt, model, budget or clinical behaviour (G-30).

### 16.5 Feature flags

```bash
./scripts/flags.sh --validate
./scripts/flags.sh --json
./scripts/flags.sh --diff          # process env/profile vs registry
./scripts/smoke.sh --flags
```

The effective flags and config hash are visible at `/meta` and Admin → Settings → Features. Runtime-safe changes require a role, typed confirmation and audit; startup-locked/safety flags require a config change and redeploy. A flag cannot disable red flags, audit, consent, PII egress or human review. Expired flags fail CI, and an unknown `FEATURE_*` key fails startup rather than being ignored.

### 16.6 Sources of information

Every agent answer and W3 draft persists its `SourceRef` list and resolver status. Check a W2 answer, a tool-backed booking and a W3 draft:

- Documents resolve to the correct patient-scoped chunk; a foreign chunk is `forbidden`, not cited.
- Preference memory (G-24) is flag-gated (`memory_preferences`, default off). When off, no `memory` source is produced. When on, memory sources must be labelled preference/context, never clinical evidence.
- Tool results show the tool and `as_of`; a stale stock read shows `stale`.
- Conversation references point to a session the user can access.
- The panel survives reload and matches the SSE `sources.resolved` event.

## 17. Testing, evaluation and load

### 17.1 Test commands

```bash
./scripts/lint.sh
./scripts/test.sh --postgres
./scripts/test.sh --pii
./scripts/test.sh --authz
./scripts/test.sh --contracts
./scripts/test.sh --i18n
./scripts/flags.sh --validate
npm --prefix apps/web test
npm --prefix apps/web exec playwright test
npm --prefix apps/web exec axe ...
```

`./scripts/test.sh --postgres` runs the integration-marked tests in a one-off `sahyog-api:local` container on the `sahyog_data` network, so it verifies the real Postgres/pgvector schema and the audit append-only trigger without assuming a host-published database port. It requires a built API image and a running Compose stack.

CI runs Ruff/format, strict mypy, import boundaries, pytest, the OpenAPI contract check, locale coverage, the feature registry, web typecheck/build, a blocking production `npm audit --audit-level=high`, Compose profile validation, Kubernetes render/kubeconform, shell syntax and gitleaks. A live Postgres job migrates an empty database through the full chain, repeats the upgrade to prove idempotence and runs `pytest -m integration`; the same sequence can be run locally against a fresh database. `pip-audit` runs as an advisory report, not a gate, because several transitive advisories need major upgrades (G-37). CI does not run Playwright/axe, the full eval suites, Semgrep/SAST, SBOM generation or image scanning; those are operator-run or recorded as gaps (G-16, G-26, G-27). A release run adds the full eval, real-user-safe load, restore and security reports.

### 17.2 Evals

```bash
./scripts/eval.sh --suite all --stub --framework deterministic   # offline gate
./scripts/eval.sh --suite w1 --framework deterministic
./scripts/eval.sh --suite w1 --framework ragas --alias judge
./scripts/eval.sh --suite w2 --framework deepeval --alias judge --no-persist
```

The deterministic framework is the release gate. This build ships two approved 30-case sets: **W1** for red-flag recall, false positives and localized safety guidance, and **W2** for provenance resolution, cross-patient rejection, staleness and model-claimed status reset. `--suite all` runs every set present in `evals/sets/`; the 24-case `rag_w3` and `qa_x01` answer-bearing sets are present and were scored by RAGAS 0.4.3 and DeepEval 3.9.9, with per-case failures and an unreviewed judge (G-16). A failed deterministic case fails the command even if an external framework reports a good aggregate score.

RAGAS and DeepEval are installed in the API image through the `eval` dependency group. Their adapters are lazy and route the judge and embeddings through LiteLLM using `LITELLM_BASE_URL`, `LITELLM_MASTER_KEY`, `--alias` and `EVAL_EMBEDDING_ALIAS`. RAGAS cases need `question`, `answer`, `contexts` and `ground_truth`; DeepEval cases need `input`, `actual_output`, `expected_output` and `retrieval_context`. If a suite lacks those fields, the gateway key is absent, or a framework call fails, the run is recorded as `unavailable` or `error` and the command exits non-zero; nothing is skipped silently. The deterministic W1/W2 safety cases do not carry generated answers, so a model-quality claim still requires recorded or live RAGAS/DeepEval suites (G-16).

Every run records framework name/version, dataset hash, prompt and graph hashes, judge alias, git SHA, thresholds and per-case pass/fail in `eval_runs`/`eval_metric_results`; artifacts go to the `sahyog-eval` bucket and the latest runs appear in Analytics → Evaluations. `--report PATH` writes the JSON report, `--no-persist` runs offline, and `--stub` is deterministic-only. Stub output proves the harness on a laptop; it is not acceptance evidence for a real-model claim.

### 17.3 Load

```bash
# Isolated environment with a dedicated Keycloak cohort
./scripts/seed-users.sh --load-test 20
./scripts/load_test.sh --profile r1 --auth keycloak --traffic-class synthetic --rate 500 --duration 60m
./scripts/load_test.sh --profile r3 --auth keycloak --traffic-class synthetic --rate 1400 --burst 4 --duration 60m

# Shared environment: explicit approval, cohort and abort guard required
LOAD_TEST_ALLOW_REAL_USERS=true ./scripts/load_test.sh \
  --profile r3 --auth keycloak --traffic-class synthetic \
  --rate 1400 --burst 4 --duration 60m --allow-real-users --abort-on-real-slo
```

`--rate` is requests per hour, matching the SLO, not requests per second; the script converts it to an arrival rate and virtual users. A 4× burst applies to the same per-hour target. Use at least a 60-minute window so the p95 has enough samples.

The test authenticates the `loadtest.*` cohort through Keycloak and calls the same public APIs as a real user. It never uses a dev bypass, direct database seeding, a disabled rate limit/PII/audit path or a production provider key. Outbound notifications are disabled for the capacity run (`NOTIFICATIONS_ENABLED=false`); notification-channel behaviour is tested separately with approved recipients.

When it runs alongside real users, the run is allowed only in an approved off-peak window with `LOAD_TEST_ALLOW_REAL_USERS=true`. The report must show test vs real traffic separately, the real-user p95/error and budget guards armed, and a clean abort test (trip the guard deliberately once). If a guard trips or real-user impact is suspected, the run stops and the incident runbook starts; do not disable the guard to finish a run.

R1/R2 use the documented demo profile (500 req/h); R3 proves 1,400 req/h with a 4× burst. The Mac pilot is the pilot host, not the R3 capacity host; use the P/M/L sizing model in [infra.md](./infra.md) for the claim.

### 17.4 Engineering-quality gates

```bash
./scripts/lint.sh                 # Ruff, mypy strict, ESLint, tsc
npm --prefix apps/web run typecheck
uv run lint-imports               # dependency rule; no cross-module imports
uv run pytest --cov=apps/api      # threshold and exceptions live in CI config
npm --prefix apps/web run build     # bundle budget report
./scripts/test.sh --contracts
kubectl kustomize deploy/k8s/overlays/pilot >/dev/null
```

The dependency rule is enforced for imports: routes → services → domain/repositories → ports; adapters implement ports and no product code imports a provider SDK, SMTP client, Slack SDK or direct MCP tool. `lint-imports`, Ruff, strict mypy, ESLint and `tsc` run in `scripts/lint.sh` and CI; tests and contract checks cover gateway and scope behaviour. A raw SQL call outside a repository is not currently a build-failing lint; the only such calls are the `SELECT 1` health probe and the read-only LiteLLM spend import. Semgrep/SAST, PHI scan, SBOM and image scanning are not part of this build's gate (G-27; PHI scan is discussed in G-18). Coverage and performance budgets are thresholds to defend, not badges; a temporary exception needs an owner, reason and expiry.

### 17.5 Analytics and notification privacy checks

```bash
./scripts/analytics-refresh.sh --from 2026-10-01 --to 2026-10-25 --live
./scripts/smoke.sh --analytics --notifications
```

Assert that analytics rows, insights, exports and notification delivery records contain no patient identifiers or note/chat body; small-cell suppression is active; an insight cannot mutate config; and each enabled channel has a delivery record with status/attempts, or a truthful `unconfigured` state. A failure here blocks the gate, even if the UI looks correct.

## 18. Security and production notes

### 18.1 Local hardening checklist

- [ ] `.env` is gitignored and not in shell history with real secrets.
- [ ] No real PHI; sample/synthetic data only.
- [ ] Keycloak test users use a strong `SEED_DEMO_PASSWORD`, not the example.
- [ ] S3Proxy/S3 buckets are private; aws-v4 required; no anonymous access.
- [ ] PostgreSQL/Redis ports bind to localhost only.
- [ ] LiteLLM master key is not in the browser or logs.
- [ ] `LANGFUSE_CAPTURE_CONTENT=false`; `AUTO_SIGN=false`; `DISABLE_PII_GATE=false`; `NOTIFY_SEND_EXTERNAL=false` unless an approved test send is active; `LOAD_TEST_ALLOW_REAL_USERS=false` unless an approved run is active.
- [ ] SMTP app password/OAuth refresh token, SMS API key and Slack bot token are server-side only; Slack scopes are minimum (`chat:write`), staff and patient workspaces and channels are allowlisted, and an unmapped user cannot trigger a channel-wide mention.
- [ ] Test Email/SMS/Slack sends resolved to Mailpit/approved test recipients, not a real patient.
- [ ] Every external integration with missing credentials shows `unconfigured`; no mock adapter is reachable at runtime.
- [ ] Feature registry validates; safety-locked flags cannot be changed at runtime; every runtime change is audited.
- [ ] Analytics/insights/exports are aggregate-only and small-cell suppressed; no note/chat body appears.
- [ ] CORS origins are exact, no `*`.
- [ ] gitleaks passes; no secrets in git history. No custom PHI scanner exists in this build (G-18).
- [ ] Import boundaries, strict types and performance budgets pass. Semgrep/SAST is not part of this build's gate (G-27).
- [ ] Containers run non-root; images pinned.
- [ ] OTLP span/metric attributes and structured-log fields contain no names, contacts or clinical text.

### 18.2 Production/acceptance differences

- TLS 1.2+ at ingress; HSTS; secure cookies; no bypass path.
- Managed Postgres/Redis/S3, private networks, least-privilege roles; Keycloak HA.
- Secrets from a secret manager, not a `.env` file on disk.
- 2+ API replicas, 2+ workers, 2+ LiteLLM/broker replicas; readiness/liveness; PDB/HPA via `deploy/k8s/`.
- Egress allowlist/proxy; no data-service public ports. The SMTP relay, SMS provider and Slack API are explicit allowlisted destinations reachable only by their adapters.
- Gmail/SMTP, SMS and Slack credentials in a secret manager with rotation/revocation; verified sender domain, SPF/DKIM/DMARC and bounce handling for email; client-owned Slack workspaces with minimum-scope bot, channel allowlist and user mapping.
- Backups, restore drills, audit anchors, on-call runbooks, alert routing.
- MFA for compliance/admin in production; step-up for anomalous booking if enabled.
- Feature-flag changes follow the protected-setting process; safety flags cannot be disabled; analytics remains aggregate-only and every export is audited.
- Load tests are not run against production without an approved window, cohort and abort guard; a production load-test flag is non-default and time-bound.
- No production claim without a security review, DPDP review and clinical validation plan.

### 18.3 What is not deployed

Service mesh, multi-region active-active, autoscaling policies, real ABDM linking/FHIR write-back, cloud-specific managed services as a hard dependency, a separate vector database/agent platform/observability SaaS, break-glass access, inpatient ADT, billing and telemedicine. Kubernetes manifests are delivered, but they do not make a single-host pilot highly available ([architecture.md](./architecture.md#1414-what-is-explicitly-not-deployed)).

## 19. Backup, restore and retention

### 19.1 Backup

```bash
./scripts/backup.sh --out /backups/care-$(date +%Y%m%d-%H%M) \
  --encrypt age1replace-with-your-recipient --note "pre-release"
```

Backs up the application database, telemetry databases when present, all object buckets, the Keycloak realm export and the versioned config, **including feature flags, model routes, metric definitions, FinOps model and notification templates/allowlists**; records counts, hashes and release metadata. The script refuses an output directory inside the repository. Store encrypted and access-restricted; test quarterly.

### 19.2 Restore

```bash
./scripts/restore.sh --from /backups/care-YYYYMMDD-HHMM --confirm
./scripts/restore.sh --from /backups/care-YYYYMMDD-HHMM.tar.gz.age \
  --identity ~/.config/age/keys.txt --confirm
```

The restore refuses a non-empty application database, non-empty buckets or a Keycloak realm that already has users (`--allow-existing-realm` overrides the last check). It verifies every manifest hash and size, stops the application and telemetry services it restores, applies the database and objects, imports the realm, runs `alembic upgrade head`, verifies row/object counts **before** restarting workers, validates flags/model routes/metric definitions/FinOps config, and runs the smoke suite. `--skip-objects`, `--skip-keycloak` and `--skip-smoke` are explicit partial modes. Target recovery within 4 hours; RPO 24 hours baseline, 15 minutes with WAL archiving for production.

### 19.3 Retention

```bash
./scripts/retention.sh --dry-run
./scripts/retention.sh --live --confirm
```

Implemented purges are audio at 24 h, chat sessions/checkpoints at 30 days, expired consents and delivered notification records at 90 days. A patient-initiated deletion request soft-deletes immediately and the worker purges patient-linked rows after `retention.deletion_grace_days` (default 30); both phases write an audit event. A document delete removes the S3 object, chunks and citation references immediately, also audited. Signed clinical notes and audit events are never deleted by this build, and draft/prompt, Langfuse-metadata, analytics-snapshot, AI-insight and eval-artifact retention remain policy targets tracked in [gaps.md](./gaps.md). Every implemented purge is audited; a failed audio deletion is logged and retried on the next run, but no alert fires (G-25). The scheduler runs the same logic; the script is for evidence and manual recovery.

## 20. Runbooks

The following runbooks live under `docs/runbooks/` and are linked from the admin health view:

1. Model provider outage / circuit open.
2. LiteLLM or MCP gateway unavailable.
3. PII detector unavailable or block storm.
4. Suspected scope leak / foreign citation.
5. Missed red flag report.
6. Audit write failure or chain mismatch.
7. Postgres restore / point-in-time recovery.
8. Queue backlog / stuck ingest.
9. Audio deletion failure (24 h breach).
10. Key rotation (JWT, `_context`, field encryption, provider keys).
11. Budget hard stop / cost anomaly.
12. Keycloak outage or admin lockout.
13. Checkpoint corruption / stale run.
14. Incident response and client notification.
15. Clean-machine setup and demo reset.
16. Email/SMS/Slack delivery failure or misdelivery.
17. Analytics snapshot stale or insight job failure.
18. FinOps variance, budget breach or cost anomaly.
19. Load-test abort or suspected real-user impact.
20. SMS/stock adapter `unconfigured` or credential expiry; FHIR read link missing / HIS unreachable (G-08).
21. Kubernetes rollout failure or manifest drift.

Each has symptom, impact, first 5 minutes, diagnosis commands (redacted), mitigation, rollback, evidence to capture and owner.

## 21. Troubleshooting

| Symptom | Likely cause | Fix |
|---|---|---|
| `start.sh` fails on config | Missing required var or dangerous flag | Read the validation message; fix `.env`; never bypass |
| API `/readyz` 503 | Postgres/Redis/S3Proxy/Keycloak JWKS/PII down | `./scripts/status.sh --json`; inspect the failed dependency; do not force ready |
| Startup rejects `DATABASE_URL` | A SQLite or non-Postgres URL | Use Postgres; there is no fallback engine (`D-02`, `MC-21`) |
| Web loads but API 401 | OIDC issuer/audience mismatch | Check `JWT_ISSUER`, `JWT_AUDIENCE`, Keycloak mapper; sign out/in |
| Redirect loop after login | Redirect URI/PKCE mismatch | Match `VITE_OIDC_REDIRECT_URI`; public client + PKCE S256 |
| CORS error | Web origin missing | Add exact origin; restart web/API |
| LiteLLM 401 | Missing/wrong virtual key | Check `LITELLM_MASTER_KEY`/service key; do not expose to browser |
| LiteLLM model not found | Purpose not mapped or provider key missing | Check `/v1/models` and `config/models.yaml`; fix the route |
| Ollama connection refused | Host/container address wrong | Use `host.docker.internal` on Docker Desktop; check `ollama serve`/port |
| Mac memory pressure / swap | Profile too large or too many local models | Stop Prometheus/Grafana/ClamAV, unload unused models, use `core`; see infra memory budget |
| Embedding dimension error | `EMBEDDING_DIM` ≠ model/table | Fix config and re-embed; do not alter the table ad hoc |
| MCP tool rejected | Missing/invalid signed `_context` or allowlist | Check broker logs (redacted), TTL/secret/audience; do not pass patient ID in args |
| MCP server unhealthy | Service token/config missing or adapter cold-start | `status.sh`; check profile; re-verify `mcp-pii` `engine=composite` and OpenDecider/Whisper reachability (G-28/G-29) |
| PII egress blocked | Expected while `EXTERNAL_EGRESS_ENABLED=false` or when the gate rejects non-composite / residual identifiers | Keep egress off until G-19 sign-off; fix composite health before any enablement attempt |
| Ingestion stuck | Worker down/queue backlog/parse failure | `status.sh`; inspect job status (no content); retry idempotently |
| Postgres migration fails | Dirty state or destructive change | Read migration log; restore/`migrate.sh`; do not edit the DB by hand |
| S3 bucket missing | Bootstrap not run | Re-run start/`s3-init`; check `S3_ACCESS_KEY`/`S3_SECRET_KEY`, endpoint, path-style |
| Audio not deleted | Lifecycle/job failure | Check scheduler and object lifecycle; alert; run retention live with confirmation |
| Langfuse blank/500 | Postgres DB/keys/worker wrong | Check Langfuse DB, worker, project keys and `/api/public/health`; export is best-effort, so also check API logs for `telemetry.langfuse.*`. The local trace ID remains on chat/scribe/audit records (G-23) |
| Browser E2E unavailable | Missing browsers, web build or Keycloak/API stack | Install with `npm --prefix apps/web exec playwright install` and run `scripts/test.sh --e2e` against a disposable Compose stack; the suite is delivered (G-26) |
| Docker out of memory | `core`/`full` too large | Raise Docker memory within the host budget; stop optional services; do not run two Ollama instances |
| gitleaks false positive | Fixture contains a test identifier | Move it to the approved eval fixture path; document the exception; never whitelist a real secret |
| Budget alert/stop | Spend threshold reached | Check admin cost view; route to local/cheap alias; raise budget only with product-owner approval |
| Email not received | SMTP host/TLS/auth wrong or Mailpit not running | Check Mailpit at :5718 (SMTP capture :5717); inspect channel status/attempts; verify sender, STARTTLS and app password; the booking remains valid |
| Email goes to a real inbox in test | `NOTIFY_SEND_EXTERNAL=true` or provider SMTP configured | Stop the test, set Mailpit, rotate the credential if exposed, record the misdelivery incident |
| Slack alerts missing | Bot not in channel, missing `chat:write`, workspace/channel not allowlisted, or user unmapped | Fix the allowlist/scope; an unmapped user must stay silent, never fall back to a channel-wide mention; in-app remains |
| Patient Slack unavailable | Opt-in or verified Slack ID missing | Capture the Slack ID at onboarding/settings; never add a patient to the staff workspace |
| SMS not visible | Provider URL/key absent or adapter `unconfigured` | Configure the real adapter; check delivery record; never use a real patient number in a demo |
| FHIR panel empty / link missing | No FHIR link or `FHIR_BASE_URL` unconfigured (G-08) | Admin maps FHIR Patient id; `/meta` shows adapter status; SPA shows honest empty states; write-back/ABDM remain out of scope |
| Feature flag startup failure | Unknown key, expired flag, bad environment or safety-locked override | Fix `config/features.yaml`/`FEATURE_*`; do not bypass validation; check `/meta` after restart |
| Feature flag change rejected | Flag is startup-locked or caller lacks role | Use config + redeploy for locked flags; runtime-safe changes need admin, confirmation and audit |
| Analytics tiles stale/empty | Scheduler stopped, Redis unreachable or the snapshot job failed | Check `job_runs` and the scheduler logs; run `analytics-refresh.sh` for an ad-hoc range; show stale, never zero (G-30) |
| AI insights absent | Scheduler not running, `INSIGHTS_ENABLED=false` or the insight job failed | Check `job_runs` and the scheduler; the API falls back to deterministic rules and labels them. Model-generated insights are persisted with accept/reject when the job succeeds (G-30) |
| FinOps reconciliation mismatch | Unmatched app/gateway calls or a stale reconciliation | Check `spend_reconciliations.detail`, review unmatched request IDs and the job run; show `partial`/`variance`, never force a match. `SahyogFinopsVariance` fires in Prometheus; Mailpit is the demo pager only (G-31, G-25) |
| Load test aborts on real-user guard | Real-user p95/error or budget guard tripped | Treat as a safety stop; inspect real-traffic metrics; stop the run; do not disable the guard |
| Source panel shows `missing`/`forbidden` | Citation resolver failed or a foreign chunk was blocked | Keep the answer ungrounded, inspect the resolver/audit event; never substitute a generic citation |
| Eval runner fails on DeepEval | Adapter/version issue, missing `litellm` in the image, or a judge timeout | Record the framework that actually ran and its report; do not mix a RAGAS score into a DeepEval run. The 2026-10-25 RAGAS evidence scored all 24 cases; DeepEval uses `openai/<alias>` (G-16) |
| K8s apply fails | Manifest drift, missing secret/overlay or namespace | `kubectl kustomize` locally, check the overlay and secret refs; Compose acceptance is unaffected |
| Infra profile does not match measured load | Unvalidated sizing inputs or changed volumes | Re-run the [infra.md](./infra.md) model with measured values; do not claim an unmeasured profile |

## 22. Clean-machine acceptance checklist

Run this on a machine that has never run the project. Record the date, OS, Docker/Python/Node versions, commit SHA and every command's result.

- [ ] Prerequisites from §2 installed; Docker memory adequate; on the Mac pilot, Ollama uses Metal.
- [ ] `git clone`; `cp .env.example .env`; required secrets set (no defaults in acceptance).
- [ ] `./scripts/start.sh --profile core` reaches healthy (all-in-Docker). Optionally also verify `./scripts/start.sh --profile core --local` (host API/UI/workers; deps in Docker; Vite :5729).
- [ ] `/readyz` truthfully reports Postgres, Redis, S3Proxy, Keycloak, LiteLLM/MCP and analytics freshness; no degraded critical dependency.
- [ ] `./scripts/migrate.sh` applies to head on Postgres; no SQLite job exists.
- [ ] `./scripts/seed-users.sh` creates roles/users without printing passwords; one user of each role signs in.
- [ ] `./scripts/load-data.sh --sample` loads and validates; counts/licences recorded.
- [ ] `./scripts/smoke.sh --sources --notifications --analytics --flags --summary` passes (API, auth, chat, W1, W2, grids, cost, audit, sources, channels/`unconfigured`, analytics, flags). `--summary` prints a JSON summary; it does not exercise an X-01 slice.
- [ ] `./scripts/flags.sh --validate` passes; `/meta` matches the effective flags and model routes; a runtime-safe change is audited; a locked flag cannot be changed at runtime; YAML defaults keep `x01_nursing_summary` and `memory_preferences` `false` until explicitly enabled.
- [ ] Patient: sign in, create/rename/delete a session, book routine, upload PDF, ask a cited question in English and Hindi/Marathi (mixed-language input accepted).
- [ ] The answer shows a Sources panel with resolved file/tool/rule/conversation/general entries and survives reload; a missing/forbidden source is visible, not hidden; with memory off, no memory source is produced (G-24).
- [ ] Email appears in Mailpit (or the approved Gmail inbox) with a minimal template; SMS uses the configured test provider; staff and patient Slack messages use the correct workspaces; each channel has status/attempts; a failed channel does not roll back the booking.
- [ ] An intentionally missing adapter credential shows `unconfigured`, not a mock success.
- [ ] Red-flag case stops before any model, shows emergency copy, creates a hand-off, creates no slot.
- [ ] Front desk sees the booking and can override with audit.
- [ ] Doctor: synthetic transcript → SOAP draft → edit → sign; the draft shows its source map; unsigned draft is not a note; signed note is immutable.
- [ ] X-01: with flag default-off, no nursing summary action. With `FEATURE_X01_NURSING_SUMMARY=true`, draft + accept/edit/reject works; do **not** sign clinical-quality acceptance without attested clinician grades (G-13).
- [ ] PII gate: `mcp-pii` reports `engine=composite` and `not_clinical_grade=false`; egress stays off (`EXTERNAL_EGRESS_ENABLED=false`) until G-19 sign-off. Do not enable egress for a demo.
- [ ] Local decision/STT: `mcp-decider` reports OpenDecider when Ollama is up (keyword fallback labelled otherwise); `mcp-stt` transcribes when Whisper weights are present; W3 still supports manual transcript entry (G-29/G-05).
- [ ] Analytics/FinOps: snapshots, local-model insights, audit anchors and reconciliation run on the scheduler; `/analytics/finops` shows `matched`/`partial`/`variance` from a real LiteLLM spend import, never a forced match. Encrypted backup proof exists; wire `BACKUP_OUT_DIR` for scheduled runs (G-30). `SahyogFinopsVariance` is loaded; Mailpit is demo paging only (G-31/G-25).
- [ ] Upload malware scanning: in `full`, upload an EICAR document and audio file and confirm rejection/quarantine with an audit event and engine version; upload a clean file and confirm acceptance; stop ClamAV and confirm `503 malware_scan_unavailable` with no object accepted (G-32).
- [ ] Compliance: one filtered audit query returns the trail; chat/note content is not exposed; compliance posture shows unknown/stale honestly.
- [ ] Admin: health/config/model routes/budgets/cost view; analytics Overview/Quality/Evaluations/FinOps/Insights visible with `as_of` freshness. With the scheduler running, insights are persisted local-model drafts (`generator=local_model`) and can be accepted/rejected with audit; without it the deterministic fallback is labelled (G-30); no clinical content; small-cell counts suppressed.
- [ ] FinOps: unit economics show formula/FX/price date; what-if scenario and growth curve load from `config/finops_model.yaml`; LiteLLM spend reconciliation reports matched, partial, variance or insufficient-data from a real gateway import (G-31); showback stays labelled app-record based; 80% alert and 100% action; showback export is aggregate-only and audited.
- [ ] Evaluations: deterministic W1/W2 runs with provenance (framework/version, dataset hash, prompt/graph version, judge alias, git SHA); thresholds pass. The 24-case RAGAS (W3) and 24-case DeepEval (X-01) suites run through the LiteLLM gateway and write reports. The judge is not human-calibrated, so no clinical-quality claim is signed (G-16).
- [ ] Load: isolated run with the `loadtest.*` Keycloak cohort at 500 req/h (R1/R2) and 1,400 req/h with 4× burst (R3); test vs real traffic separated; with real users, approval recorded and the abort guard deliberately tripped once; `reset-test-data.sh` removes the cohort.
- [ ] Engineering: import boundaries, strict types, gitleaks and the flag-mutation test pass. Semgrep/SAST, SBOM and signature verification are not run in this build (G-27); do not claim them.
- [ ] Infrastructure: the P (Mac pilot) footprint is measured; S/M/L projections and capex/opex/TCO are reviewed; `config/finops_model.yaml` matches [infra.md](./infra.md); the gap is recorded if load is unmeasured.
- [ ] OTLP HTTP spans reach the collector and metrics are scraped in `full`; no PHI in logs/spans. Agent spans are exported to Langfuse with content capture off and a trace ID is stored on chat/scribe/audit records (G-23). Verify one trace has null `input`/`output`; do not paste prompt or completion content into evidence.
- [ ] `./scripts/retention.sh --dry-run` shows audio/chat/draft/audit/notification/analytics actions.
- [ ] `./scripts/backup.sh` completes; `./scripts/restore.sh` into an empty environment succeeds within 4 h and validates flags/routes/metrics.
- [ ] `./scripts/test.sh --authz`, `--pii`, `--contracts` and `--i18n` pass; `./scripts/test.sh --e2e` passes 20/20 Playwright/axe tests on a disposable stack (G-26). The axe run is a smoke check, not a WCAG conformance audit.
- [ ] `kubectl kustomize deploy/k8s/overlays/pilot` and `.../production` render; `./scripts/k8s-deploy.sh --overlay pilot` renders; no cluster smoke or kind run has been performed in this build (G-11).
- [ ] Clean-machine log and screenshots attached to the G6 record.
- [ ] Known limitations, [gaps.md](./gaps.md) and the variance register are shared with the product owner.

If any safety item fails, stop and do not sign the gate. If a non-safety item fails, record a variance with the measured result, reason, residual risk, owner and expiry.

## 23. Appendices

### Appendix A — Environment quick reference

Copy `.env.example`, fill the values marked required for the profile, and never commit it. The full reference is §6. The minimum for `minimal`:

```dotenv
APP_ENV=dev
APP_PROFILE=minimal
APP_BASE_URL=http://localhost:5705
API_BASE_URL=http://localhost:5706
APP_SECRET_KEY=<random 32+>
POSTGRES_USER=sahyog
POSTGRES_PASSWORD=<random>
POSTGRES_DB=sahyog
DATABASE_URL=postgresql+asyncpg://sahyog:<password>@postgres:5432/sahyog
REDIS_URL=redis://redis:6379/0
S3_ENDPOINT_URL=http://s3proxy:80
S3_PUBLIC_ENDPOINT_URL=http://localhost:5719
S3_ACCESS_KEY=<random>
S3_SECRET_KEY=<random>
S3_BUCKET_DOCUMENTS=sahyog-documents
S3_BUCKET_AUDIO=sahyog-audio
S3_BUCKET_EXPORTS=sahyog-exports
S3_BUCKET_ANCHORS=sahyog-audit-anchors
S3_BUCKET_EVAL=sahyog-eval
S3_BUCKET_BACKUPS=sahyog-backups
S3_SERVER_SIDE_ENCRYPTION=
S3_USE_PATH_STYLE=true
KEYCLOAK_URL=http://keycloak:8080
KEYCLOAK_PUBLIC_URL=http://localhost:5707
KEYCLOAK_REALM=sahyog
KEYCLOAK_CLIENT_ID=sahyog-api
KEYCLOAK_AUDIENCE=sahyog-api
KEYCLOAK_ADMIN_CLIENT_ID=sahyog-admin
KEYCLOAK_ADMIN_CLIENT_SECRET=<random>
KEYCLOAK_ADMIN_PASSWORD=<random>
KEYCLOAK_CLI_CLIENT_ID=sahyog-cli
KEYCLOAK_CLI_CLIENT_SECRET=<random>
KEYCLOAK_MCP_CLIENT_ID=sahyog-mcp
KEYCLOAK_MCP_CLIENT_SECRET=<random>
SEED_DEMO_PASSWORD=<random 12+>
ADD_USER_PASSWORD=<random 12+>
OLLAMA_BASE_URL=http://host.docker.internal:11434
OLLAMA_CHAT_MODEL=ollama_chat/<pinned>
OLLAMA_SMALL_MODEL=ollama_chat/<pinned>
EMBED_MODEL=bge-m3
EMBEDDING_DIM=1024
LITELLM_BASE_URL=http://litellm:4000
LITELLM_MASTER_KEY=<random>
LITELLM_DB_PASSWORD=<random>
MCP_BROKER_URL=http://mcp-broker:8100
MCP_SERVICE_TOKEN=<random>
MCP_CONTEXT_SECRET=<random 32+>
PII_TOKEN_SECRET=<random 32+>
# PII_ENGINE=composite (proven); keep egress off until G-19 sign-off.
EXTERNAL_EGRESS_ENABLED=false
LANGFUSE_CAPTURE_CONTENT=false
ALLOW_CLOUD_STT=false
EMAIL_ADAPTER=smtp
SMTP_HOST=mailpit
SMTP_PORT=1025
SMTP_AUTH_MODE=none
SMTP_USE_STARTTLS=false
EMAIL_FROM=care@example.invalid
NOTIFICATIONS_ENABLED=true
ANALYTICS_ENABLED=true
ANALYTICS_SMALL_CELL_MINIMUM=5
INSIGHTS_ENABLED=true
SUPPORTED_LOCALES=en-IN,hi-IN,mr-IN
DEFAULT_LOCALE=en-IN
LOAD_TEST_ALLOW_REAL_USERS=false
# SLACK_* / SMS_* left empty => channel shows unconfigured, not a mock
# FHIR_* enable read-only adapter + SPA when FEATURE_FHIR_READ is on (G-08)
# FEATURE_<KEY>=true    # only keys declared in config/features.yaml
```

For `core`, add `LANGFUSE_*` secrets, `LANGFUSE_DATABASE_URL`, `OTEL_EXPORTER_OTLP_ENDPOINT` and Whisper/OpenDecider host settings (G-29/G-05). For `full`, add `GRAFANA_ADMIN_PASSWORD` and the load settings; add `--with-melt` only when demonstrating ClickHouse. Never enable `NOTIFY_SEND_EXTERNAL` for an unapproved audience.

### Appendix B — Script-to-gate map

| Script / evidence | Gate |
|---|---|
| `start.sh`, `status.sh`, images non-root, `flags.sh --validate`, K8s render | G1 |
| `migrate.sh` on Postgres; `load-data.sh --validate`; adapter contract tests | G1/G2 |
| `test.sh --authz`, `--pii`; `smoke.sh` red-flag and sources; i18n fixtures | G3 |
| `test.sh --authz` scope/provenance/broker checks (no IDOR matrix; G-10); consent grant/revoke/expiry/context and patient export/deletion/document-delete tests (`test.sh --postgres`); notification channel status/`unconfigured`; Playwright/axe browser E2E (G-26) | G3/G4 |
| `eval.sh` deterministic W1/W2 provenance; 24-case RAGAS (W3) and DeepEval (X-01) reports; `analytics-refresh.sh`; `export-finops.sh`; `load-test.sh` with guard; `backup.sh`/`restore.sh`; Playwright/axe suite. Judge calibration remains unreviewed (G-16) | G5 |
| R3: `load-test.sh --profile r3`; X-01 20-case eval and external MCP contract are not delivered (G-13/G-14) | G4-R3/G5-R3 |
| `smoke.sh --sources --notifications --analytics --flags --summary`, clean-machine log, memo, demo, AI log | G6 |
| `retention.sh`, `reset-test-data.sh`, alert tests, 48 h observation | G7 |
| Engineering-quality report (imports/types/gitleaks), flag mutation test; no Semgrep/SBOM/signature in this build (G-27) | G1/G5 |
| [infra.md](./infra.md) sizing output, `finops_model.yaml`, capex/opex/TCO and measured-load validation | G0/G5/G6 |

### Appendix C — Ports and URLs summary

See §2.4. Web `http://localhost:5705`; API `http://localhost:5706`; Keycloak `http://localhost:5707`; LiteLLM `http://localhost:5708`; MCP broker `http://localhost:5709`; Mailpit UI `http://localhost:5718` (SMTP capture `:5717`); S3Proxy `http://localhost:5719`; Langfuse `http://localhost:5721`; Prometheus `http://localhost:5722`; Grafana `http://localhost:5723`; ClickHouse `http://localhost:5727` in `melt` (HTTP, loopback).

### Appendix D — Model purpose/alias map

See §8.1. Application code requests purposes; `config/models.yaml` maps them to aliases (`main`, `local_main`, `local_small`, `embed`, `judge`, `title`, `red_flag`, `insights`). Provider model IDs live only in `config/models.yaml`/`config/litellm.yaml`. A route change is a config + eval change, not a code change.

### Appendix E — Test user map

See §7.4 and §7.6. All users are synthetic, `@example.test`, and use `SEED_DEMO_PASSWORD`; no default credentials in acceptance/production. The `loadtest.*` cohort is separate from demo users, tagged `cohort=loadtest`, and removed by `reset-test-data.sh`.

### Appendix F — Source notes

- Baseline brief pp. 17–22: data estate, contracts, sizing.
- Baseline brief pp. 32–36: access, threat model, cost, production concerns.
- [spec.md](./spec.md): requirements, gates, acceptance, retention, D-01–D-28.
- [architecture.md](./architecture.md): containers, profiles, ports, startup, runbooks, hardening.
- [plan.md](./plan.md): eight-week calendar, gates, clean-machine acceptance, handover package.
- [design.md](./design.md): routes, themes, grids, chat, accessibility, i18n.
- [infra.md](./infra.md): parameterized sizing, P/M/L profiles, capex/opex BoM, TCO, what-if and growth.
- [gaps.md](./gaps.md): known language, telemetry and integration gaps and mitigations.
- Slack Web API: <https://api.slack.com/web>.
- Gmail SMTP: <https://support.google.com/a/answer/176600>.

### Appendix G — Sizing and infrastructure quick reference

This appendix maps the setup footprint to the procurement model; [infra.md](./infra.md) is authoritative.

| Setup / deployment | Infra profile | Planning footprint (indicative) | Capex / opex / 3-year TCO |
|---|---|---|---|
| `minimal` developer | Laptop | 4–8 CPU, 16 GB, no GPU | Not a deployment; no TCO claim |
| **Pilot on Mac M4 Pro** | **P laptop pilot** | **14-core CPU, 20-core GPU, 26 GB unified, 1 TB; Docker 14 GB + Ollama ≈7 GB** | **Owned hardware (incremental capex ₹0; replacement ≈₹2.5–3.8L); on-prem opex ≈₹6,300–25,000/month including model/API spend; 3-year TCO ≈₹2.3–9.0L (replacement ≈₹4.8–12.8L); no HA** |
| `core` acceptance host | **S demo/acceptance** | 1 host, 16 vCPU/64 GB, 2 TB, optional 24 GB GPU | ≈₹6–10L capex without GPU (≈₹10–17L with); on-prem opex ≈₹30–70k/month; 3-year TCO ≈₹17–42L (on-prem) or ≈₹32–54L (cloud) |
| Hosted pilot | **M pilot** | 2 app hosts, DB, Redis, storage, 1×48 GB GPU | ≈₹31–45L capex; on-prem opex ≈₹1.3–2.2L/month; cloud opex ≈₹3.2–4.6L/month; 3-year TCO ≈₹78–124L on-prem / ≈₹115–166L cloud |
| Production HA | **L production** | 3 app, DB primary+standby, Redis HA, 3 storage, 2×48 GB GPU, multi-AZ | ≈₹87–120L capex; on-prem opex ≈₹4.5–7.5L/month; cloud opex ≈₹12–17L/month; 3-year TCO ≈₹249–390L on-prem / ≈₹432–612L cloud |

Ranges exclude GST, DR and real vendor quotes; replace with the client's dated rates. The sizing inputs, formulas, BoM, what-if and growth model are in [infra.md](./infra.md#2-sizing-inputs) through [infra.md](./infra.md#10-assumptions-and-exclusions). Re-run at G0 (draft envelope), G5 (measured load) and G6 (handover).
