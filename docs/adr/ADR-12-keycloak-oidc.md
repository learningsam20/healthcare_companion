# ADR-12: Keycloak OIDC Authorization Code + PKCE

| Field | Value |
|---|---|
| ID | ADR-12 |
| Title | Keycloak OIDC Authorization Code + PKCE |
| Status | Accepted |
| Category | Identity |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **keycloak oidc authorization code + pkce** so boundaries, safety and operability stay reviewable in git.

## Decision

**Keycloak OIDC Authorization Code + PKCE**

## Alternatives considered

Custom auth; social-only

## Consequences

Standards-based roles/MFA; operational dependency

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-12
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
