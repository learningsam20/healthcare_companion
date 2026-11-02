# ADR-30: Parameterized infra sizing + capex/opex BoM

| Field | Value |
|---|---|
| ID | ADR-30 |
| Title | Parameterized infra sizing + capex/opex BoM |
| Status | Accepted — see infra.md |
| Category | Infrastructure |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **parameterized infra sizing + capex/opex bom** so boundaries, safety and operability stay reviewable in git.

## Decision

**Parameterized infra sizing + capex/opex BoM**

## Alternatives considered

Fixed hardware list; cloud-only

## Consequences

Honest right-sizing; needs measured re-runs

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-30
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
