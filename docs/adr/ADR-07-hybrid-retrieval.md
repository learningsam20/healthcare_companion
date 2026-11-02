# ADR-07: Hybrid pgvector + lexical retrieval; patient filter in SQL

| Field | Value |
|---|---|
| ID | ADR-07 |
| Title | Hybrid pgvector + lexical retrieval; patient filter in SQL |
| Status | Accepted |
| Category | Retrieval |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **hybrid pgvector + lexical retrieval; patient filter in sql** so boundaries, safety and operability stay reviewable in git.

## Decision

**Hybrid pgvector + lexical retrieval; patient filter in SQL**

## Alternatives considered

Vector-only; external vector DB

## Consequences

Better recall for names/Hinglish; two retrieval paths

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-07
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
