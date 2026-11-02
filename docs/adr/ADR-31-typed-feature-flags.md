# ADR-31: Typed feature-flag registry; safety cannot be flagged off

| Field | Value |
|---|---|
| ID | ADR-31 |
| Title | Typed feature-flag registry; safety cannot be flagged off |
| Status | Accepted |
| Category | Configuration |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **typed feature-flag registry; safety cannot be flagged off** so boundaries, safety and operability stay reviewable in git.

## Decision

**Typed feature-flag registry; safety cannot be flagged off**

## Alternatives considered

Hard-coded env checks; toggles for everything

## Consequences

Predictable enablement; flag hygiene required

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-31
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
