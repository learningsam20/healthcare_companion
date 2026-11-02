# ADR-02: Postgres 16+ / pgvector only — no SQLite

| Field | Value |
|---|---|
| ID | ADR-02 |
| Title | Postgres 16+ / pgvector only — no SQLite |
| Status | Accepted (Q-09) |
| Category | Data store |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **postgres 16+ / pgvector only — no sqlite** so boundaries, safety and operability stay reviewable in git.

## Decision

**Postgres 16+ / pgvector only — no SQLite**

## Alternatives considered

SQLite dev/demo; separate vector DB

## Consequences

One migration path and full feature parity; higher laptop footprint

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-02
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
