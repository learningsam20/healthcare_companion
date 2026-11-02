# ADR-35: Slack for staff and opt-in verified patients

| Field | Value |
|---|---|
| ID | ADR-35 |
| Title | Slack for staff and opt-in verified patients |
| Status | Accepted (Q-24) |
| Category | Notifications |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **slack for staff and opt-in verified patients** so boundaries, safety and operability stay reviewable in git.

## Decision

**Slack for staff and opt-in verified patients**

## Alternatives considered

Staff-only Slack; no Slack

## Consequences

Meets channel ask; dual-audience governance

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-35
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
