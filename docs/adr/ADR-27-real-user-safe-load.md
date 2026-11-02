# ADR-27: Real-user-safe load via public APIs + tagged cohort + abort

| Field | Value |
|---|---|
| ID | ADR-27 |
| Title | Real-user-safe load via public APIs + tagged cohort + abort |
| Status | Accepted |
| Category | Assurance |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **real-user-safe load via public apis + tagged cohort + abort** so boundaries, safety and operability stay reviewable in git.

## Decision

**Real-user-safe load via public APIs + tagged cohort + abort**

## Alternatives considered

Internal endpoints; DB seeding

## Consequences

Realistic evidence without touching real users

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-27
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
