# Deployment architecture — Sahyog Care Companion

| Field | Value |
|---|---|
| Purpose | How the stack is deployed for pilot (Compose) and production-ready (Kubernetes) |
| Normative source | [ADR-16b](../adr/ADR-16b-deployment-hosting.md) · [architecture.md](../architecture.md) §14 · [setup.md](../setup.md) · [infra.md](../infra.md) |
| Related | [11-technical-architecture.md](./11-technical-architecture.md) · [bill-of-materials.md](../bill-of-materials.md) |

## 1. Reference pilot — Docker Compose (`full` profile, local app)

```mermaid
flowchart TB
  subgraph Host["Pilot host — loopback published ports"]
    subgraph HostProcs["Host processes --local"]
      API["API :5706<br/>uvicorn"]
      WEB["Web :5729<br/>Vite"]
      WRK["ARQ worker"]
      SCH["ARQ scheduler"]
      OLL["Ollama :11434<br/>host models"]
    end

    subgraph Compose["Docker Compose network sahyog"]
      KC["keycloak :5707"]
      PG["postgres :5432"]
      RD["redis"]
      MINIO["minio / S3"]
      LL["litellm"]
      BR["mcp-broker"]
      MCP["mcp-* servers"]
      PII["mcp-pii / PII"]
      STT["mcp-stt"]
      DEC["mcp-decider"]
      CLAM["clamav"]
      MAIL["mailpit :5718"]
      LF["langfuse :5721"]
      PROM["prometheus :5722"]
      GRAF["grafana :5723"]
      AM["alertmanager"]
    end
  end

  Users((Operators / personas)) --> WEB
  WEB --> API
  WEB --> KC
  API --> PG & RD & MINIO & LL & BR & LF
  WRK --> PG & RD & MINIO & CLAM & MAIL
  LL --> OLL
  LL --> BR
  BR --> MCP
  MCP --> PG & PII & STT & DEC
  API --> PROM
  PROM --> GRAF
```

**Start:** `./scripts/start.sh --profile full --local`  
**Invariant:** `EXTERNAL_EGRESS_ENABLED=false` for acceptance demos unless a reviewed de-id path is intentionally shown.

## 2. Production-oriented — Kubernetes

```mermaid
flowchart TB
  subgraph Edge["Edge"]
    LB["Load balancer / Ingress<br/>TLS · WAF optional"]
  end

  subgraph Cluster["Kubernetes cluster"]
    subgraph NSApp["namespace: sahyog"]
      WEB_D["Deployment web<br/>nginx + static SPA"]
      API_D["Deployment api<br/>HPA on CPU / in-flight"]
      WRK_D["Deployment worker"]
      SCH_D["Deployment scheduler<br/>single replica"]
      LL_D["Deployment litellm"]
      BR_D["Deployment mcp-broker"]
      MCP_D["Deployments mcp-*"]
    end

    subgraph NSData["Data services — managed or in-cluster"]
      PG_STS["Postgres + pgvector<br/>primary · standby"]
      RD_STS["Redis"]
      S3_EXT["S3-compatible bucket"]
    end

    subgraph NSObs["Observability"]
      OTEL_D["otel-collector"]
      LF_D["Langfuse"]
      PROM_S["Prometheus"]
      GRAF_S["Grafana"]
    end

    subgraph NSId["Identity"]
      KC_D["Keycloak"]
    end
  end

  subgraph GPU["Optional GPU node pool"]
    OLL_D["Ollama / vLLM<br/>local aliases"]
  end

  Users((Users)) --> LB --> WEB_D & API_D & KC_D
  API_D --> PG_STS & RD_STS & S3_EXT & LL_D & BR_D
  WRK_D --> PG_STS & RD_STS & S3_EXT
  LL_D --> OLL_D
  LL_D --> BR_D --> MCP_D
  API_D & WRK_D --> OTEL_D --> LF_D & PROM_S --> GRAF_S
```

Manifests: `deploy/k8s/` (Kubernetes-ready; Compose remains the reference acceptance path per ADR-16b).

## 3. Environment matrix

| Concern | P laptop pilot | S acceptance | M hosted pilot | L production |
|---|---|---|---|---|
| Orchestration | Compose + host app | Compose on VM | Compose or K8s | Kubernetes |
| DB | Compose Postgres | Compose / managed | Managed preferred | Primary + standby |
| Models | Host Ollama | Ollama ± GPU | 48 GB GPU class | 2× GPU / HA |
| Observability | Langfuse + Prom + Grafana | same | same + retention | same + alerting |
| HA claim | none | none | N+1 app | Multi-AZ |
| Secrets | `.env` local | `.env` / sealed | secret manager | secret manager |

## 4. Network and trust boundaries

| Boundary | Rule |
|---|---|
| Browser → SPA/API | HTTPS in deployed envs; OIDC via Keycloak |
| API → model egress | Denied unless de-identified + flag on |
| MCP tools | Only through broker with signed short-lived context |
| Object store | Private bucket; app credentials; no public ACLs |
| Observability | Loopback or private network; no clinical content in spans |
| Admin UIs | Grafana/Langfuse not exposed publicly without SSO |

## 5. Release unit

| Artefact | Role |
|---|---|
| `apps/web` image / static | UI |
| `apps/api` image | API + worker entrypoints |
| MCP / LiteLLM / sidecars | Compose or K8s deployments |
| Migration job | Alembic against Postgres |
| Config | env + `config/*.yaml` mounts |
| Evidence | gates, eval report, demo reel, BoM |
