# ADR-03: LiteLLM is the sole model and agent-tool gateway

| Field | Value |
|---|---|
| ID | ADR-03 |
| Title | LiteLLM is the sole model and agent-tool gateway |
| Status | Accepted |
| Category | AI gateway |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **litellm is the sole model and agent-tool gateway** so boundaries, safety and operability stay reviewable in git.

## Decision

**LiteLLM is the sole model and agent-tool gateway**

## Alternatives considered

Direct provider SDKs; custom proxy

## Consequences

Swappable models, spend, MCP gateway; LiteLLM is critical path

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-03
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
