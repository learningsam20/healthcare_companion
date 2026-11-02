# ADR-37: Real SMS/SMTP/Slack/FHIR adapters; doubles only in tests

| Field | Value |
|---|---|
| ID | ADR-37 |
| Title | Real SMS/SMTP/Slack/FHIR adapters; doubles only in tests |
| Status | Accepted (Q-11) |
| Category | Integrations |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **real sms/smtp/slack/fhir adapters; doubles only in tests** so boundaries, safety and operability stay reviewable in git.

## Decision

**Real SMS/SMTP/Slack/FHIR adapters; doubles only in tests**

## Alternatives considered

Runtime mocks

## Consequences

Honest integration path; credential burden

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-37
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
