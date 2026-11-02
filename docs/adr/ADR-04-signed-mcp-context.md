# ADR-04: Signed `_context` via single MCP broker

| Field | Value |
|---|---|
| ID | ADR-04 |
| Title | Signed `_context` via single MCP broker |
| Status | Accepted (Q-05) |
| Category | Security / tools |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **signed `_context` via single mcp broker** so boundaries, safety and operability stay reviewable in git.

## Decision

**Signed `_context` via single MCP broker**

## Alternatives considered

Pass patient ID in tool args; trust gateway headers

## Consequences

Strong scope guarantee; broker is critical; IDs never in logs

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-04
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
