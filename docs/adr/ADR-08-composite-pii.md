# ADR-08: Composite local PII/PHI + reversible tokenisation

| Field | Value |
|---|---|
| ID | ADR-08 |
| Title | Composite local PII/PHI + reversible tokenisation |
| Status | Accepted (Q-03) |
| Category | Privacy |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **composite local pii/phi + reversible tokenisation** so boundaries, safety and operability stay reviewable in git.

## Decision

**Composite local PII/PHI + reversible tokenisation**

## Alternatives considered

Single model; cloud PII API

## Consequences

Defence in depth and residency; false-negative residual

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-08
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
