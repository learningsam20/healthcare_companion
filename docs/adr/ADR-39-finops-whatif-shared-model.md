# ADR-39: FinOps what-if/profitability share one versioned model

| Field | Value |
|---|---|
| ID | ADR-39 |
| Title | FinOps what-if/profitability share one versioned model |
| Status | Accepted |
| Category | FinOps |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **finops what-if/profitability share one versioned model** so boundaries, safety and operability stay reviewable in git.

## Decision

**FinOps what-if/profitability share one versioned model**

## Alternatives considered

Static spreadsheet; AI-only advice

## Consequences

Transparent planning; maintain assumptions

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-39
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
