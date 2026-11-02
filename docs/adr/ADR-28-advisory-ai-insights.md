# ADR-28: AI insights advisory, local model default

| Field | Value |
|---|---|
| ID | ADR-28 |
| Title | AI insights advisory, local model default |
| Status | Accepted |
| Category | Analytics |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **ai insights advisory, local model default** so boundaries, safety and operability stay reviewable in git.

## Decision

**AI insights advisory, local model default**

## Alternatives considered

Auto-tune prompts/budgets; external by default

## Consequences

Improvement loop without autonomous change

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-28
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
