# ADR-21: Every profile runs Postgres and Keycloak

| Field | Value |
|---|---|
| ID | ADR-21 |
| Title | Every profile runs Postgres and Keycloak |
| Status | Accepted |
| Category | Runtime profile |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **every profile runs postgres and keycloak** so boundaries, safety and operability stay reviewable in git.

## Decision

**Every profile runs Postgres and Keycloak**

## Alternatives considered

Dev auth/SQLite shortcut

## Consequences

Local matches acceptance; footprint accepted

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-21
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
