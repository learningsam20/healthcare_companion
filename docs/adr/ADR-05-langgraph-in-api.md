# ADR-05: LangGraph in API + durable checkpoints + Redis run buffer

| Field | Value |
|---|---|
| ID | ADR-05 |
| Title | LangGraph in API + durable checkpoints + Redis run buffer |
| Status | Accepted |
| Category | Agent runtime |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **langgraph in api + durable checkpoints + redis run buffer** so boundaries, safety and operability stay reviewable in git.

## Decision

**LangGraph in API + durable checkpoints + Redis run buffer**

## Alternatives considered

Separate agent runtime; in-memory state

## Consequences

Simple SSE/deploy; crash loses in-flight task not checkpoint

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-05
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
