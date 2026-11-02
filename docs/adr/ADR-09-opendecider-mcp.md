# ADR-09: OpenDecider as local MCP typed-decision service

| Field | Value |
|---|---|
| ID | ADR-09 |
| Title | OpenDecider as local MCP typed-decision service |
| Status | Accepted (Q-04) |
| Category | Local models |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **opendecider as local mcp typed-decision service** so boundaries, safety and operability stay reviewable in git.

## Decision

**OpenDecider as local MCP typed-decision service**

## Alternatives considered

Ollama chat alias; in-process classifier

## Consequences

Correct prompt/calibration; fallback required

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-09
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
