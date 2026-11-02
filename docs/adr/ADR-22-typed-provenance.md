# ADR-22: Typed SourceRef provenance resolved by code

| Field | Value |
|---|---|
| ID | ADR-22 |
| Title | Typed SourceRef provenance resolved by code |
| Status | Accepted |
| Category | Provenance |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **typed sourceref provenance resolved by code** so boundaries, safety and operability stay reviewable in git.

## Decision

**Typed SourceRef provenance resolved by code**

## Alternatives considered

Model-written citations only

## Consequences

Auditable source panel; resolver work

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-22
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
