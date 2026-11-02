# ADR-38: Tagged synthetic data + idempotent reset

| Field | Value |
|---|---|
| ID | ADR-38 |
| Title | Tagged synthetic data + idempotent reset |
| Status | Accepted (Q-21) |
| Category | Data ops |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **tagged synthetic data + idempotent reset** so boundaries, safety and operability stay reviewable in git.

## Decision

**Tagged synthetic data + idempotent reset**

## Alternatives considered

Manual cleanup; shared dataset

## Consequences

Repeatable benchmarks; careful scoping

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-38
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
