# ADR-16: Compose profiles + Kubernetes-ready manifests

| Field | Value |
|---|---|
| ID | ADR-16 |
| Title | Compose profiles + Kubernetes-ready manifests |
| Status | Accepted (Q-12) |
| Category | Deployment |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **compose profiles + kubernetes-ready manifests** so boundaries, safety and operability stay reviewable in git.

## Decision

**Compose profiles + Kubernetes-ready manifests**

## Alternatives considered

Kubernetes-first; single compose file

## Consequences

Fits laptop acceptance; HA still needs validation

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-16
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
