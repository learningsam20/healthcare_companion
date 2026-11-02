# ADR-33: en/hi/mr + mixed-language from R1

| Field | Value |
|---|---|
| ID | ADR-33 |
| Title | en/hi/mr + mixed-language from R1 |
| Status | Accepted (Q-14) |
| Category | i18n |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **en/hi/mr + mixed-language from r1** so boundaries, safety and operability stay reviewable in git.

## Decision

**en/hi/mr + mixed-language from R1**

## Alternatives considered

English-first i18n readiness

## Consequences

Wider reach; translation/eval work

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-33
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
