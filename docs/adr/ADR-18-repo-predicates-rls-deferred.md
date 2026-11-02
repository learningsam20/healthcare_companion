# ADR-18: Repository scope predicates as R1 authz; RLS deferred

| Field | Value |
|---|---|
| ID | ADR-18 |
| Title | Repository scope predicates as R1 authz; RLS deferred |
| Status | Accepted |
| Category | Authorization |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **repository scope predicates as r1 authz; rls deferred** so boundaries, safety and operability stay reviewable in git.

## Decision

**Repository scope predicates as R1 authz; RLS deferred**

## Alternatives considered

RLS everywhere; encrypt all clinical text

## Consequences

Implementable/testable; RLS gap documented

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-18
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
