# ADR-25: FinOps as first-class product surface

| Field | Value |
|---|---|
| ID | ADR-25 |
| Title | FinOps as first-class product surface |
| Status | Accepted |
| Category | FinOps |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **finops as first-class product surface** so boundaries, safety and operability stay reviewable in git.

## Decision

**FinOps as first-class product surface**

## Alternatives considered

Monthly spreadsheet; LiteLLM spend only

## Consequences

Daily attribution; needs price catalogues

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-25
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
