# ADR-01: Modular monolith (API) + worker(s)

| Field | Value |
|---|---|
| ID | ADR-01 |
| Title | Modular monolith (API) + worker(s) |
| Status | Accepted |
| Category | Boundary / runtime |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **modular monolith (api) + worker(s)** so boundaries, safety and operability stay reviewable in git.

## Decision

**Modular monolith (API) + worker(s)**

## Alternatives considered

Microservices per domain; separate agent service

## Consequences

Fewer auth/audit surfaces and feasible delivery; extraction later possible

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-01
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
