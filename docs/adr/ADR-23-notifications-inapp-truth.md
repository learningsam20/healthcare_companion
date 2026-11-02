# ADR-23: In-app notification SoT; SMS/email/Slack best-effort adapters

| Field | Value |
|---|---|
| ID | ADR-23 |
| Title | In-app notification SoT; SMS/email/Slack best-effort adapters |
| Status | Accepted |
| Category | Notifications |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **in-app notification sot; sms/email/slack best-effort adapters** so boundaries, safety and operability stay reviewable in git.

## Decision

**In-app notification SoT; SMS/email/Slack best-effort adapters**

## Alternatives considered

Transactional SMS/email only; staff-only Slack

## Consequences

Channel flexibility without rollback coupling

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-23
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
