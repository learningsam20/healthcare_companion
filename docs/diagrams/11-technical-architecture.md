# Technical architecture — Sahyog Care Companion

| Field | Value |
|---|---|
| Purpose | Runtime technical view: modules, AI path, safety, observability |
| Normative source | [architecture.md](../architecture.md) containers §3 · ADRs under [../adr/](../adr/) |
| Related | [10-data-flow.md](./10-data-flow.md) · [12-deployment-architecture.md](./12-deployment-architecture.md) · [02-container-3-1-container-diagram.md](./02-container-3-1-container-diagram.md) |

## 1. Layered technical view

```mermaid
flowchart TB
  subgraph Presentation["Presentation"]
    SPA["apps/web · Vite · React · TypeScript<br/>role shells · grids · Sources panel · scribe workspace"]
  end

  subgraph EdgeServices["Edge & identity"]
    KC["Keycloak · realm sahyog · OIDC"]
    NG["nginx / Vite dev proxy"]
  end

  subgraph Application["Application — modular monolith"]
    direction TB
    API["apps/api · FastAPI<br/>REST · SSE · OpenAPI"]
    MOD["Domain modules<br/>chat · scheduling · records · scribe<br/>notifications · analytics · governance · admin"]
    RT["Agent runtime<br/>LangGraph W1 / W2 / W3 · checkpointer"]
    WRK["ARQ worker<br/>ingest · STT · notify · export · insights"]
    CRON["ARQ scheduler<br/>retention · snapshots · FinOps reconcile · SLA"]
  end

  subgraph Gateways["Gateways & tools"]
    LL["LiteLLM<br/>model aliases · spend · MCP gateway"]
    BR["mcp-broker<br/>allowlist · signed context · audit"]
    MS["MCP servers<br/>scheduling · records · clinical<br/>platform · pii · stt · decider"]
  end

  subgraph Platforms["Platform services"]
    PII["PII / de-id<br/>Presidio · GLiNER · OPF"]
    STT["STT · faster-whisper"]
    DEC["OpenDecider"]
    CLAM["ClamAV"]
  end

  subgraph Persistence["Persistence"]
    PG[("Postgres 16 + pgvector<br/>OLTP · vectors · checkpoints · audit")]
    RD[("Redis<br/>queues · limits · pub/sub")]
    OBJ[("MinIO / S3<br/>documents · audio · exports")]
  end

  subgraph Models["Models"]
    OLL["Ollama<br/>local_main · local_fast · embeddings"]
    EXT["OpenRouter<br/>de-identified only · optional"]
  end

  subgraph Telemetry["Telemetry & FinOps"]
    OTEL["OTLP"]
    LF["Langfuse"]
    PROM["Prometheus"]
    GRAF["Grafana"]
    FIN["FinOps snapshots · showback"]
  end

  SPA --> NG --> API
  SPA <--> KC
  API --> MOD
  MOD --> RT
  MOD --> PG & RD & OBJ
  RT --> LL
  LL --> OLL
  LL -.-> EXT
  LL --> BR --> MS
  MS --> PG & PII & STT & DEC
  API --> WRK & CRON
  WRK --> CLAM & PII & STT & OBJ & PG
  API & WRK & RT --> OTEL
  OTEL --> LF & PROM
  PROM --> GRAF
  CRON --> FIN
  FIN --> PG
```

## 2. Module map (API)

| Module | Owns | Outbound |
|---|---|---|
| Auth / RBAC | JWT validation, role guards | Keycloak JWKS |
| Chat | sessions, interrupts, provenance UI feed | W1/W2 graphs, MCP |
| Scheduling | appointments, holds, waitlist | MCP scheduling, notifications |
| Records | upload, ingest status, scoped ask | worker, pgvector, W2 |
| Scribe | encounters, transcripts, runs, sign | W3 local path, clinical notes |
| Notifications | in-app + channel dispatch | Mailpit/SMTP, Slack |
| Analytics / FinOps | tiles, compliance, evals, cost | snapshot tables, LiteLLM reconcile |
| Governance / audit | append-only query UI | audit store |
| Admin / ops | health, flags, effective config | readiness probes |

## 3. Safety and control planes

```mermaid
flowchart LR
  REQ[Request] --> AUTH[OIDC + role]
  AUTH --> CTX[Mint signed execution context]
  CTX --> RF{Red-flag rules}
  RF -->|hit| HC[Hand-off · no booking tools]
  RF -->|clear| GRAPH[LangGraph]
  GRAPH --> VAL[Schema / citation / stock validators]
  VAL --> PERSIST[Persist only if gates pass]
  PERSIST --> AUD[Audit + trace id]
  GRAPH --> TOOL[MCP via broker]
  TOOL --> SIG{Signature valid + scope?}
  SIG -->|no| DENY[Deny tool]
  SIG -->|yes| EXEC[Execute]
```

## 4. Technology choices (ADR-backed)

| Concern | Choice | ADR / note |
|---|---|---|
| UI | Vite React TypeScript | stack ADRs |
| API | FastAPI modular monolith | delivery constraint D-07 |
| Agents | LangGraph + Postgres checkpointer | workflow ADRs |
| Models | LiteLLM aliases · Ollama local | FR-GW |
| Tools | MCP broker only | MC-14 |
| Identity | Keycloak OIDC | — |
| DB | Postgres 16 + pgvector | — |
| Objects | S3-compatible MinIO | — |
| Queues | Redis + ARQ | — |
| Telemetry | OTLP · Langfuse · Prometheus · Grafana | FR-OBS |
| Hosting | Compose reference · K8s-ready | ADR-16b |

## 5. Non-functional targets (summary)

| Area | Target (spec) | Evidence locus |
|---|---|---|
| Triage p95 | < 4 s server | load + traces |
| Record-answer p95 | < 8 s | load + traces |
| Note draft p95 | < 20 s after transcript | eval / role-play |
| Peak load | 1,400 req/h · 4× burst | load reports |
| Privacy | identified W3 local; egress de-id only | config + gates |
| Availability | fail closed on safety; degrade on convenience | architecture QA table |
