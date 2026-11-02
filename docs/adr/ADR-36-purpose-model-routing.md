# ADR-36: Provider/model resolved per business purpose

| Field | Value |
|---|---|
| ID | ADR-36 |
| Title | Provider/model resolved per business purpose |
| Status | Accepted (Q-10) |
| Category | AI routing |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **provider/model resolved per business purpose** so boundaries, safety and operability stay reviewable in git.

## Decision

**Provider/model resolved per business purpose**

## Alternatives considered

One model for every purpose

## Consequences

Better cost/quality fit; routing surface

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-36
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
