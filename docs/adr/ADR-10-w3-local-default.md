# ADR-10: W3 identified processing local-only by default

| Field | Value |
|---|---|
| ID | ADR-10 |
| Title | W3 identified processing local-only by default |
| Status | Accepted |
| Category | Egress policy |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **w3 identified processing local-only by default** so boundaries, safety and operability stay reviewable in git.

## Decision

**W3 identified processing local-only by default**

## Alternatives considered

Send identified text externally; always-local forever

## Consequences

Residency-safe; local quality/latency risk

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-10
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
