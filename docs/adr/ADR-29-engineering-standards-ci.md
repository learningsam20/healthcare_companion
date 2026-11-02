# ADR-29: Standards enforced by types, dependency rules, CI budgets

| Field | Value |
|---|---|
| ID | ADR-29 |
| Title | Standards enforced by types, dependency rules, CI budgets |
| Status | Accepted |
| Category | Engineering |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **standards enforced by types, dependency rules, ci budgets** so boundaries, safety and operability stay reviewable in git.

## Decision

**Standards enforced by types, dependency rules, CI budgets**

## Alternatives considered

Review-only standards

## Consequences

Secure/modular/efficient becomes testable

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-29
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
