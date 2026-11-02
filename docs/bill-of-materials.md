# Bill of materials — Sahyog Care Companion

| Field | Value |
|---|---|
| Product | Sahyog Care Companion |
| Document | Software, platform, and infrastructure bill of materials for handover |
| Date | 2026-11-02 |
| Status | Planning / handover BoM — **not a procurement quote** |
| Price basis | Indicative INR ranges from [infra.md](./infra.md) (2026-10-25 assumptions, excl. GST) |
| Related | [infra.md](./infra.md) · [ADR-30](./adr/ADR-30-parameterized-infra-bom.md) · [cost-sheet.md](./cost-sheet.md) · [diagrams/12-deployment-architecture.md](./diagrams/12-deployment-architecture.md) |

Replace unit costs with vendor quotes and the client finance FX rate before purchase. Profiles: **P** laptop pilot · **S** acceptance · **M** hosted pilot · **L** production HA.

---

## 1. Software bill of materials (delivered in-repo)

### 1.1 First-party components

| Component | Path / unit | Language | Role |
|---|---|---|---|
| Web SPA | `apps/web` | TypeScript · React · Vite | Role-based UI |
| API | `apps/api` | Python · FastAPI | Modular monolith · OpenAPI |
| Workers | `apps/api` ARQ entrypoints | Python | Ingest, notify, insights, retention |
| MCP servers | `services/mcp-*` (Compose) | Python | Scheduling, records, clinical, platform, PII, STT, decider |
| Shared libs | `packages/` / `sahyog_common` | Python | Telemetry, config helpers |
| Config | `config/*.yaml` | YAML | Red flags, FinOps model, prices, stock |
| IaC reference | `docker-compose*.yml` · `deploy/k8s/` | Compose / K8s | Pilot and K8s-ready manifests |
| Scripts | `scripts/` | Bash / Python | start, seed, eval, load, demo reel |

### 1.2 Runtime dependencies (pinned in lockfiles)

| Layer | Representative stack | Lock / pin |
|---|---|---|
| UI | React, Vite, Playwright | `apps/web/package-lock.json` |
| API | FastAPI, SQLAlchemy, LangGraph, ARQ | `uv.lock` / `pyproject.toml` |
| Identity | Keycloak | Compose image tag |
| Data | Postgres 16 + pgvector, Redis, MinIO | Compose image tags |
| AI gateway | LiteLLM | Compose image tag |
| Local models | Ollama + Qwen / bge-m3 aliases | Host models · LiteLLM config |
| Observability | Langfuse, Prometheus, Grafana, OTLP | Compose |
| Safety sidecars | ClamAV, Presidio/GLiNER path, faster-whisper, OpenDecider | Compose / MCP |
| Eval | RAGAS / DeepEval harnesses | `evals/` · `scripts/eval.sh` |

Generate a machine-readable dependency audit from CI (`pip-audit` / npm audit) at release; treat CVEs per [gaps.md](./gaps.md) G-37.

### 1.3 Optional / flag-gated

| Item | Default | Note |
|---|---|---|
| OpenRouter external models | Off | De-identified egress only when enabled |
| External SMS | Often unconfigured | Booking must not roll back |
| X-01 nursing summary | Flag off | Not clinically graded |
| External MCP | Off | ADR / gaps G-14 |

---

## 2. Platform services BoM (Compose `full`)

| Service | Port (host) | Required for acceptance demo |
|---|---|---|
| Web (Vite/`--local`) | 5729 | Yes |
| API | 5706 | Yes |
| Keycloak | 5707 | Yes |
| Postgres + pgvector | internal / mapped | Yes |
| Redis | internal | Yes |
| MinIO | mapped per compose | Yes |
| LiteLLM | internal | Yes |
| MCP broker + domain MCPs | internal | Yes |
| Ollama (host) | 11434 | Yes (local aliases) |
| Mailpit | 5718 | Yes (email proof) |
| ClamAV | internal | Yes under `full` |
| Langfuse | 5721 | Yes (traces) |
| Prometheus | 5722 | Yes (metrics) |
| Grafana | 5723 | Yes (dashboards) |
| Alertmanager | mapped | Recommended |

---

## 3. Infrastructure BoM (indicative)

Detail and formulas: [infra.md §4](./infra.md). Summary only.

### 3.1 Capex (on-prem / colo), ₹ lakh excl. GST

| Profile | Indicative capex | Notes |
|---|---:|---|
| **P** laptop pilot | 0 incremental (owned Mac) | Replacement class ≈ 2.5–3.8 if purchased |
| **S** acceptance host | ≈ 6–10 without GPU · 10–17 with 24 GB GPU | Single host · no HA claim |
| **M** hosted pilot | ≈ 31–45 | N+1 app · 1× 48 GB GPU class |
| **L** production HA | ≈ 87–120 | Multi-AZ class · 2× GPU |

### 3.2 Opex (monthly), indicative

| Profile | On-prem/colo ₹/month | India cloud ₹/month |
|---|---:|---:|
| **P** | ≈ 6.3k–25k | ≈ 26k–75k (P-equivalent VM) |
| **S** | ≈ 30k–70k | ≈ 90k–1.5 lakh (+ GPU on demand) |
| **M** | ≈ 1.3–2.2 lakh | ≈ 3.2–4.6 lakh |
| **L** | ≈ 4.5–7.5 lakh | ≈ 12–17 lakh |

Largest variable: **external LLM token spend**, not power.

### 3.3 Line-item checklist (procurement)

| # | Line | P | S | M | L |
|---|---|---|---|---|---|
| 1 | Application compute | owned laptop | 1 host | 2 nodes | 3 nodes |
| 2 | Database | Compose on host | Compose/managed | dedicated/managed | primary+standby |
| 3 | Redis | Compose | Compose | dedicated/managed | HA |
| 4 | Object storage | MinIO/local | MinIO | MinIO/S3 | multi-node/S3 |
| 5 | GPU / unified memory | M4 Pro class | optional 24 GB | 1× 48 GB | 2× 48 GB |
| 6 | Backup target | encrypted external | appliance/cloud | offsite | offsite+DR |
| 7 | Network / LB / firewall | local | basic | firewall+LB | WAF+LB |
| 8 | UPS / power | laptop UPS optional | yes | yes | yes |
| 9 | Observability retention | short | short | medium | policy-driven |
| 10 | IdP | Keycloak Compose | same | hardened | HA Keycloak/SSO |
| 11 | Domain + TLS certs | localhost | yes | yes | yes |
| 12 | SMS/email/Slack contracts | Mailpit local | optional SMS | yes | yes |

---

## 4. Model and skill BoM

| Alias / skill | Typical local artefact | Purpose |
|---|---|---|
| `local_main` | Qwen 2.5 7B-class Q4 | Chat / ask / draft |
| `local_fast` | Qwen 2.5 3B-class Q4 | Light turns |
| Embeddings | `bge-m3` | Document vectors |
| STT | faster-whisper small/medium | Consultation audio |
| PII | Presidio + GLiNER (+ OPF as configured) | De-id / scrub |
| Decider | OpenDecider / tev1 class | Second-pass decisions |
| External `main` | OpenRouter (optional) | De-identified only |

Exact tags: LiteLLM config + host `ollama list`. Do not ship unpinned “latest” into acceptance.

---

## 5. Evidence and document BoM (handover pack)

| Artefact | Path |
|---|---|
| Spec / architecture / plan | `docs/spec.md` · `docs/architecture.md` · `docs/plan.md` |
| Diagrams | `docs/diagrams/` including data-flow, technical, deployment |
| ADRs | `docs/adr/` |
| Infra + FinOps model | `docs/infra.md` · `config/finops_model.yaml` |
| Cost sheet | `docs/cost-sheet.md` |
| Eval report | `evals/report.md` |
| Gates / release | `docs/gates/` · `RELEASE.md` |
| Demo reel | `docs/evidence/demo-recording/sahyog-demo-6min.mp4` |
| Gaps / caveats | `docs/gaps.md` · `docs/evidence/ship-caveats.md` |

---

## 6. Recompute triggers

Re-run this BoM when any of the following change: peak `R` / burst, local vs external model share, retention, HA topology, GPU class, FX rate, or measured load (`capacity_accepted`). Owner: platform team + client finance.
