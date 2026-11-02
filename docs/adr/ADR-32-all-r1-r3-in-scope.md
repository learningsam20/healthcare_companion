# ADR-32: All R1–R3 features in delivery scope

| Field | Value |
|---|---|
| ID | ADR-32 |
| Title | All R1–R3 features in delivery scope |
| Status | Accepted (Q-01) |
| Category | Scope |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **all r1–r3 features in delivery scope** so boundaries, safety and operability stay reviewable in git.

## Decision

**All R1–R3 features in delivery scope**

## Alternatives considered

R1+R2 only; R3 stretch

## Consequences

Complete product; larger plan

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-32
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
