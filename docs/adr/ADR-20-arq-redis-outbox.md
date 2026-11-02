# ADR-20: ARQ + Redis queues/cron; outbox for external effects

| Field | Value |
|---|---|
| ID | ADR-20 |
| Title | ARQ + Redis queues/cron; outbox for external effects |
| Status | Accepted |
| Category | Async jobs |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **arq + redis queues/cron; outbox for external effects** so boundaries, safety and operability stay reviewable in git.

## Decision

**ARQ + Redis queues/cron; outbox for external effects**

## Alternatives considered

Celery; cloud queue; sync side effects

## Consequences

Lightweight Python stack; Redis critical

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-20
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
