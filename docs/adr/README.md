# Architecture decision records

Canonical ADR files for tech-stack and platform choices. The summary index remains in [architecture.md §13](../architecture.md#13-architecture-decision-records).

| ADR | File | Status | Category |
|---|---|---|---|
| ADR-01 | [ADR-01-modular-monolith.md](./ADR-01-modular-monolith.md) | Accepted | Boundary / runtime |
| ADR-02 | [ADR-02-postgres-only.md](./ADR-02-postgres-only.md) | Accepted (Q-09) | Data store |
| ADR-03 | [ADR-03-litellm-gateway.md](./ADR-03-litellm-gateway.md) | Accepted | AI gateway |
| ADR-04 | [ADR-04-signed-mcp-context.md](./ADR-04-signed-mcp-context.md) | Accepted (Q-05) | Security / tools |
| ADR-05 | [ADR-05-langgraph-in-api.md](./ADR-05-langgraph-in-api.md) | Accepted | Agent runtime |
| ADR-06 | [ADR-06-mem0-preferences.md](./ADR-06-mem0-preferences.md) | Accepted | Memory |
| ADR-07 | [ADR-07-hybrid-retrieval.md](./ADR-07-hybrid-retrieval.md) | Accepted | Retrieval |
| ADR-08 | [ADR-08-composite-pii.md](./ADR-08-composite-pii.md) | Accepted (Q-03) | Privacy |
| ADR-09 | [ADR-09-opendecider-mcp.md](./ADR-09-opendecider-mcp.md) | Accepted (Q-04) | Local models |
| ADR-10 | [ADR-10-w3-local-default.md](./ADR-10-w3-local-default.md) | Accepted | Egress policy |
| ADR-11 | [ADR-11-sse-not-websocket.md](./ADR-11-sse-not-websocket.md) | Accepted | API transport |
| ADR-12 | [ADR-12-keycloak-oidc.md](./ADR-12-keycloak-oidc.md) | Accepted | Identity |
| ADR-13 | [ADR-13-s3-compatible-storage.md](./ADR-13-s3-compatible-storage.md) | Accepted | Object storage |
| ADR-14 | [ADR-14-hash-chained-audit.md](./ADR-14-hash-chained-audit.md) | Accepted | Audit |
| ADR-15 | [ADR-15-langfuse-postgres.md](./ADR-15-langfuse-postgres.md) | Accepted (Q-08) | Telemetry |
| ADR-16 | [ADR-16-compose-and-k8s.md](./ADR-16-compose-and-k8s.md) | Accepted (Q-12) | Deployment |
| ADR-17 | [ADR-17-sqlite-superseded.md](./ADR-17-sqlite-superseded.md) | Superseded | Data store |
| ADR-18 | [ADR-18-repo-predicates-rls-deferred.md](./ADR-18-repo-predicates-rls-deferred.md) | Accepted | Authorization |
| ADR-19 | [ADR-19-external-mcp-r3.md](./ADR-19-external-mcp-r3.md) | Accepted | Integrations |
| ADR-20 | [ADR-20-arq-redis-outbox.md](./ADR-20-arq-redis-outbox.md) | Accepted | Async jobs |
| ADR-21 | [ADR-21-every-profile-postgres-keycloak.md](./ADR-21-every-profile-postgres-keycloak.md) | Accepted | Runtime profile |
| ADR-22 | [ADR-22-typed-provenance.md](./ADR-22-typed-provenance.md) | Accepted | Provenance |
| ADR-23 | [ADR-23-notifications-inapp-truth.md](./ADR-23-notifications-inapp-truth.md) | Accepted | Notifications |
| ADR-24 | [ADR-24-metric-registry-snapshots.md](./ADR-24-metric-registry-snapshots.md) | Accepted | Analytics |
| ADR-25 | [ADR-25-finops-product-surface.md](./ADR-25-finops-product-surface.md) | Accepted | FinOps |
| ADR-26 | [ADR-26-ragas-deepeval-evalrunner.md](./ADR-26-ragas-deepeval-evalrunner.md) | Accepted (Q-20) | Evaluation |
| ADR-27 | [ADR-27-real-user-safe-load.md](./ADR-27-real-user-safe-load.md) | Accepted | Assurance |
| ADR-28 | [ADR-28-advisory-ai-insights.md](./ADR-28-advisory-ai-insights.md) | Accepted | Analytics |
| ADR-29 | [ADR-29-engineering-standards-ci.md](./ADR-29-engineering-standards-ci.md) | Accepted | Engineering |
| ADR-30 | [ADR-30-parameterized-infra-bom.md](./ADR-30-parameterized-infra-bom.md) | Accepted — see infra.md | Infrastructure |
| ADR-31 | [ADR-31-typed-feature-flags.md](./ADR-31-typed-feature-flags.md) | Accepted | Configuration |
| ADR-32 | [ADR-32-all-r1-r3-in-scope.md](./ADR-32-all-r1-r3-in-scope.md) | Accepted (Q-01) | Scope |
| ADR-33 | [ADR-33-multilingual-r1.md](./ADR-33-multilingual-r1.md) | Accepted (Q-14) | i18n |
| ADR-34 | [ADR-34-all-role-chat.md](./ADR-34-all-role-chat.md) | Accepted (Q-07) | Product surface |
| ADR-35 | [ADR-35-slack-staff-and-patients.md](./ADR-35-slack-staff-and-patients.md) | Accepted (Q-24) | Notifications |
| ADR-36 | [ADR-36-purpose-model-routing.md](./ADR-36-purpose-model-routing.md) | Accepted (Q-10) | AI routing |
| ADR-37 | [ADR-37-real-adapters-only.md](./ADR-37-real-adapters-only.md) | Accepted (Q-11) | Integrations |
| ADR-38 | [ADR-38-tagged-synthetic-reset.md](./ADR-38-tagged-synthetic-reset.md) | Accepted (Q-21) | Data ops |
| ADR-39 | [ADR-39-finops-whatif-shared-model.md](./ADR-39-finops-whatif-shared-model.md) | Accepted | FinOps |
| ADR-40 | [ADR-40-otlp-portability.md](./ADR-40-otlp-portability.md) | Accepted (Q-05/Q-08) | Telemetry |

## Also in this folder

- [ADR-16b-deployment-hosting.md](./ADR-16b-deployment-hosting.md) — **D6** hosting matrix, chosen option, switch trigger
- [ADR-41-change-request.md](./ADR-41-change-request.md) — sealed day-8 change request
