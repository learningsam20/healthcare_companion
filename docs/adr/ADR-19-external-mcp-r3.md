# ADR-19: External MCP server in R3, isolated, off by default

| Field | Value |
|---|---|
| ID | ADR-19 |
| Title | External MCP server in R3, isolated, off by default |
| Status | Accepted |
| Category | Integrations |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **external mcp server in r3, isolated, off by default** so boundaries, safety and operability stay reviewable in git.

## Decision

**External MCP server in R3, isolated, off by default**

## Alternatives considered

Enable in R1; direct partner APIs

## Consequences

Contains third-party risk; needs kill switch

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-19
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
