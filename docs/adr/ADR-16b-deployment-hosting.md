# ADR-16b: Deployment hosting choice (D6)

| Field | Value |
|---|---|
| ID | ADR-16b (D6) |
| Title | Hosting model — pilot vs production |
| Status | **Accepted** |
| Gate | G4 (rescored with Gate 2 / Q answers) |
| Owner | Platform & assurance |
| Related | [infra.md §6](../infra.md) · [architecture.md §14](../architecture.md#14-deployment-and-operations) · ADR-16 · DQ-03 |

## Context

Gate 2 answered residency, peak load, FX/power assumptions and the pilot host (`Q-25`…`Q-30`, `Q-28`). D6 requires the hosting matrix to be **rescored** with those answers, **one option defended**, and a **switch trigger** named.

## Options (rescored)

| Criterion | On-prem (hospital) | Colo | India cloud | Hybrid |
|---|---|---|---|---|
| Data residency | Strongest if site-controlled | Strong; colo is subprocessor | Region-pinned; verify subprocessors | Local PHI plane + cloud control/analytics |
| Capex vs opex | High capex | Medium / medium | Low capex, higher opex | Split |
| GPU | Procurement lead time | Procurement lead time | Elastic but scarce | Local GPU + cloud burst |
| HA/DR | Needs second site | Second site or provider DR | Managed multi-AZ easier | Design-dependent |
| Ops ownership | Hospital IT | Shared | App team + cloud provider | Shared — boundary must be explicit |
| Fit to Q-25/Q-28 | Strong if rack+ops exist | Strong if rack without owning facility | Strong for speed/HA | Strong if PHI must stay local |
| Fit to Mac pilot (Q-28) | Not the pilot host | Not the pilot host | Optional P-equivalent VM | Optional |
| 3y TCO (indicative) | See infra.md S/M/L tables | See infra.md | Cloud premium buys elasticity | Between on-prem and cloud |

Scores use Gate 2 inputs: peak **1,400 req/h** with 4× burst, RPO 24 h / RTO 4 h single-site pilot, India residency, Mac M4 Pro as **current** pilot host.

## Decision

1. **Now (acceptance / demo):** Compose on the product-owner **Mac M4 Pro 26 GB** (`laptop_pilot` / profile P). Reference path: `./scripts/start.sh`.
2. **Hosted pilot:** **On-prem or colo** *if* the hospital provides power, rack, backup and a named ops owner; **otherwise India cloud** (single region).
3. **Production default:** **Managed India cloud** with reserved compute, unless DPDP/security policy mandates on-prem — then on-prem/colo with an explicit DR plan.

Compose remains the **acceptance** path; Kubernetes manifests stay ready (ADR-16) without claiming a cluster was production-proven in this build (G-11).

Hybrid egress boundary: identified processing and primary stores stay in-boundary; only de-identified text may reach an external model provider (`Q-02`, ADR-10).

## Consequences

- Capex/opex what-if UI and [infra.md](../infra.md) share one model (`ADR-39`).
- P-host load evidence must not be labelled `capacity_accepted` (G-17).
- Switching hosting changes BoM, NetworkPolicy/ingress, secret injection and backup drill evidence.

## Switch trigger

Revisit and re-score within **ten working days** if any of:

- Hospital confirms a rack + 24/7 ops owner (prefer on-prem/colo for pilot).
- India-region GPU quota unavailable for required STT/eval load (shift hybrid GPU or resize models).
- Legal/security mandates on-prem for all subprocessors (drop public cloud control plane).
- Measured load on M/L falsifies the S/M/L BoM by >25% on opex or latency SLOs.
- Multi-region RPO/RTO tighter than 24 h / 4 h is contracted (adds second-site cost).

## Rejected for this engagement

- Cloud-only without an on-prem/colo option in the FinOps what-if matrix.
- Claiming Kubernetes multi-region HA as delivered without restore/DR drill evidence.
