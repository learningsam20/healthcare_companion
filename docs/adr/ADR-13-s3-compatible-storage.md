# ADR-13: S3-compatible object storage with lifecycle + PRESIGNED URLs

| Field | Value |
|---|---|
| ID | ADR-13 |
| Title | S3-compatible object storage with lifecycle + PRESIGNED URLs |
| Status | Accepted |
| Category | Object storage |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **s3-compatible object storage with lifecycle + presigned urls** so boundaries, safety and operability stay reviewable in git.

## Decision

**S3-compatible object storage with lifecycle + PRESIGNED URLs**

## Alternatives considered

Local disk; cloud-specific SDK

## Consequences

Portability; lifecycle ops required

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-13
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
