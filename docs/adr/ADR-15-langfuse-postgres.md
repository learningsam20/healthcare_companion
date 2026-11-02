# ADR-15: Self-hosted Langfuse (Postgres) + OTLP metrics

| Field | Value |
|---|---|
| ID | ADR-15 |
| Title | Self-hosted Langfuse (Postgres) + OTLP metrics |
| Status | Accepted (Q-08) |
| Category | Telemetry |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **self-hosted langfuse (postgres) + otlp metrics** so boundaries, safety and operability stay reviewable in git.

## Decision

**Self-hosted Langfuse (Postgres) + OTLP metrics**

## Alternatives considered

Langfuse Cloud; ClickHouse-backed Langfuse

## Consequences

Clear separation; de-identified content only

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-15
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
