# ADR-26: RAGAS + DeepEval via one EvalRunner; deterministic safety gate

| Field | Value |
|---|---|
| ID | ADR-26 |
| Title | RAGAS + DeepEval via one EvalRunner; deterministic safety gate |
| Status | Accepted (Q-20) |
| Category | Evaluation |
| Date | 2026-10-25 (baselined); filed 2026-11-02 |
| Deciders | Platform pod / engineering lead |
| Related | [architecture.md §13](../architecture.md#13-architecture-decision-records) · [infra.md](../infra.md) · [spec.md](../spec.md) |

## Context

Sahyog Care Companion needs an explicit technical choice for **ragas + deepeval via one evalrunner; deterministic safety gate** so boundaries, safety and operability stay reviewable in git.

## Decision

**RAGAS + DeepEval via one EvalRunner; deterministic safety gate**

## Alternatives considered

Single framework; judge-only evals

## Consequences

Comparable evals without diluting safety

## Revisit trigger

Re-open this ADR if a safety control weakens, a store/boundary changes, a mandatory check cannot be met, or measured load/privacy evidence falsifies the assumption behind this choice.

## Links

- Index row: architecture §13 ADR-26
- Implementation: repository modules and Compose/`deploy/k8s` as applicable
