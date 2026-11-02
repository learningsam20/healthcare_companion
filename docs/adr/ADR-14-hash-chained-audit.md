# ADR-14: Append-only hash-chained audit + daily anchors

| Field | Value |
|---|---|
| ID | ADR-14 |
| Title | Append-only hash-chained audit + daily anchors |
| Status | Accepted |
| Category | Audit |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **append-only hash-chained audit + daily anchors** so boundaries, safety and operability stay reviewable in git.

## Decision

**Append-only hash-chained audit + daily anchors**

## Alternatives considered

Plain table; external log only

## Consequences

Tamper evidence; write/verify cost

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-14
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
