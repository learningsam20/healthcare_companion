# ADR-17: SQLite adapters (superseded)

| Field | Value |
|---|---|
| ID | ADR-17 |
| Title | SQLite adapters (superseded) |
| Status | Superseded |
| Category | Data store |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **sqlite adapters (superseded)** so boundaries, safety and operability stay reviewable in git.

## Decision

**SQLite adapters (superseded)**

## Alternatives considered

Pretend parity

## Consequences

Superseded by ADR-02 — SQLite cannot provide parity

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-17
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
