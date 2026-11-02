# Data flow — Sahyog Care Companion

| Field | Value |
|---|---|
| Purpose | End-to-end data movement for the six workflows and platform services |
| Normative source | [architecture.md](../architecture.md) · [spec.md](../spec.md) |
| Related | [11-technical-architecture.md](./11-technical-architecture.md) · [12-deployment-architecture.md](./12-deployment-architecture.md) |

## 1. System data flow (C4-style)

```mermaid
flowchart TB
  subgraph Actors["Actors"]
    PAT[Patient / caregiver]
    DOC[Doctor]
    FD[Front desk]
    CMP[Compliance]
    ADM[Admin]
  end

  subgraph Edge["Edge"]
    WEB[Web SPA<br/>Vite React · OIDC]
  end

  subgraph ControlPlane["Control plane"]
    KC[Keycloak<br/>OIDC · roles]
    API[API<br/>FastAPI modular monolith]
    WG[ARQ worker]
    SCH[ARQ scheduler]
  end

  subgraph AIPath["AI path — gated"]
    LG[LangGraph runtimes<br/>W1 triage · W2 records · W3 scribe]
    LL[LiteLLM<br/>aliases · spend]
    BRK[MCP broker<br/>signed context]
    MCP[MCP servers<br/>scheduling · records · clinical · platform · PII · STT · decider]
    OLL[Ollama<br/>local models]
    OR[OpenRouter<br/>de-identified only]
  end

  subgraph DataPlane["Data plane"]
    PG[(Postgres 16<br/>OLTP · pgvector · checkpoints · audit)]
    RD[(Redis<br/>queues · rate limits · run events)]
    S3[(MinIO / S3<br/>documents · audio · exports)]
  end

  subgraph Safety["Deterministic safety"]
    RF[Red-flag rules]
    PII[Composite PII / de-id]
    DEC[OpenDecider]
    STT[faster-whisper STT]
  end

  subgraph Observe["Observability — no PHI content"]
    OTEL[OTLP collector]
    LF[Langfuse traces]
    PROM[Prometheus]
    GRAF[Grafana]
  end

  subgraph Notify["Notifications"]
    MAIL[Mailpit / SMTP]
    SLK[Slack allowlist]
  end

  PAT & DOC & FD & CMP & ADM --> WEB
  WEB <--> KC
  WEB --> API
  API --> PG & RD & S3
  API --> LG
  API --> RF
  LG --> LL
  LL --> OLL
  LL -. egress off by default .-> OR
  LL --> BRK
  BRK --> MCP
  MCP --> PG
  MCP --> PII & DEC & STT
  API --> WG & SCH
  WG --> PG & RD & S3 & PII & STT & MAIL & SLK
  SCH --> PG & RD & S3
  API & WG --> OTEL
  OTEL --> LF & PROM
  PROM --> GRAF
  LG --> LF
```

## 2. Workflow data paths

### W1 — Find doctor / book

```mermaid
sequenceDiagram
  participant U as Patient UI
  participant A as API
  participant R as Red-flag rules
  participant G as W1 graph
  participant M as MCP scheduling
  participant P as Postgres
  U->>A: chat turn + session
  A->>R: evaluate symptoms before model
  alt red flag
    R-->>A: fail closed · hand-off
    A-->>U: emergency guidance · no slots
  else routine
    A->>G: run with signed execution context
    G->>M: specialty / doctors / slots
    M->>P: read catalogue + availability
    G-->>A: cards + typed provenance
    A->>P: checkpoint · audit
    A-->>U: shortlist / booking interrupt
    U->>A: confirm hold
    A->>P: appointment row · idempotent
    A-->>U: confirmation · in-app notify
  end
```

### W2 — Records ingest and ask

```mermaid
flowchart LR
  U[Patient] --> WEB[Web]
  WEB --> API[API]
  API --> S3[(Object store bytes)]
  API --> Q[Redis ingest queue]
  Q --> W[Worker]
  W --> CLAM[ClamAV]
  W --> CHUNK[Chunk · embed via Ollama bge-m3]
  CHUNK --> PG[(document_chunk + vectors)]
  WEB --> ASK[Ask my record]
  ASK --> API
  API --> W2[W2 graph]
  W2 --> RET[Scoped retrieval SQL predicate]
  RET --> PG
  W2 --> LL[LiteLLM local_main]
  W2 --> SRC[Provenance resolver]
  SRC --> UI[Sources panel]
```

### W3 — Scribe draft and sign

```mermaid
flowchart TB
  D[Doctor] --> SCR[Scribe UI]
  SCR --> API[API]
  API --> ENC[(encounter · transcript)]
  SCR --> GEN[Generate draft]
  GEN --> W3[W3 graph · local aliases only for identified text]
  W3 --> SOAP[SOAP schema validate]
  W3 --> STOCK[Stock / formulary flags]
  SOAP --> RUN[(scribe_run draft)]
  D --> SIGN[Attest + sign]
  SIGN --> NOTE[(clinical_note locked)]
  SIGN --> AUD[(audit · hash · trace)]
```

## 3. Data classification and stores

| Class | Examples | Store | Leaves boundary? |
|---|---|---|---|
| Identity | subjects, roles | Keycloak + app user map | No |
| Clinical content | notes, transcripts, chat bodies | Postgres | No (W3 local) |
| Document bytes | PDFs, audio | S3-compatible | No |
| Vectors | chunk embeddings | Postgres pgvector | No |
| Checkpoints | LangGraph state | Postgres | No |
| Queues / run events | jobs, SSE tips | Redis | No |
| Spend / metrics | tokens, latency | LiteLLM + Prometheus | Aggregates only |
| Traces | spans, tool names | Langfuse via OTLP | De-identified metadata only |
| Notifications | email/SMS/Slack | providers | Neutral templates; no clinical body |

## 4. Cross-cutting flows

| Flow | Path |
|---|---|
| AuthN/Z | Browser → Keycloak → SPA → API JWT → role scopes |
| Tool calls | Graph → LiteLLM MCP → broker verifies signed `_context` → MCP server → DB |
| Egress | PII scrub → policy gate → OpenRouter only if `EXTERNAL_EGRESS_ENABLED` |
| Audit | Every patient-data read/write → append-only audit with actor, purpose, trace |
| FinOps | LiteLLM spend → reconciliation job → analytics FinOps tiles / export |
| Retention | Scheduler deletes audio ≤24h; chat/checkpoint per policy; audit retained |
