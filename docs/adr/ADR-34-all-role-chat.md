# ADR-34: All application roles get role-scoped chat/consoles

| Field | Value |
|---|---|
| ID | ADR-34 |
| Title | All application roles get role-scoped chat/consoles |
| Status | Accepted (Q-07) |
| Category | Product surface |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **all application roles get role-scoped chat/consoles** so boundaries, safety and operability stay reviewable in git.

## Decision

**All application roles get role-scoped chat/consoles**

## Alternatives considered

Patient-only chat

## Consequences

Full surface; more policies to test

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-34
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
