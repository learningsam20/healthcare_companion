# ADR-40: OTLP is the telemetry portability contract

| Field | Value |
|---|---|
| ID | ADR-40 |
| Title | OTLP is the telemetry portability contract |
| Status | Accepted (Q-05/Q-08) |
| Category | Telemetry |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **otlp is the telemetry portability contract** so boundaries, safety and operability stay reviewable in git.

## Decision

**OTLP is the telemetry portability contract**

## Alternatives considered

Langfuse-only telemetry

## Consequences

Any MELT backend can consume; redaction work

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-40
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
