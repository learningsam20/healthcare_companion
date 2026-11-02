# Evaluation report

| Field | Value |
|---|---|
| Artefact | G5 / G6 evaluation report |
| Generated | 2026-11-02 |
| Companion stamp | `evals/reports/latest.md` · evidence under `docs/evidence/eval-*` |
| Safety rule | Deterministic red-flag / provenance / scope failures **block release**. Judge scores cannot override them. |
| Judge | `unreviewed` — human κ not attested (G-16) |

## 1. Targets table (spec §8.3)

| Workflow | Metric | Threshold | Measured | Verdict | Evidence |
|---|---|---|---|---|---|
| W1 triage | Red-flag recall | **100%** | **1.000** (30/30) | **Pass** | [eval-w1-deterministic-20261101T170120Z.json](../docs/evidence/eval-w1-deterministic-20261101T170120Z.json) |
| W1 triage | Red-flag false positive rate | 0 on negatives | **0.000** | **Pass** | same |
| W1 triage | Specialty accuracy (top-1 golden) | ≥ 85% | Not separately scored in deterministic suite | **Missing — variance** | Specialty path covered by tool-truth booking tests; golden specialty suite not filed as distinct metric |
| W1 triage | Candidate doctors/slots match tools | 100% | Enforced by design (cards from MCP only) | **Pass (by construction + API tests)** | MCP scheduling tests; UI cards refuse invented doctors |
| W1 triage | p95 response | < 4 s | **1216.7 ms** (n=6) | **Pass** | [load_test_chat_latency_20261102T004206Z.json](../docs/evidence/load_test_chat_latency_20261102T004206Z.json) |
| W2 ask | Faithfulness (calibrated judge) | ≥ 0.90 | RAGAS mean **0.801** (judge unreviewed) | **Miss — variance** | [eval-ragas-w3-20261025T083908Z.json](../docs/evidence/eval-ragas-w3-20261025T083908Z.json); safety gate still passed |
| W2 ask | Answer relevancy | ≥ 0.90 provisional | RAGAS **0.454** | **Miss — variance** | same; hi/mr/mixed drag mean (G-04/G-16) |
| W2 ask | Context precision | ≥ 0.85 | RAGAS **0.958** | **Pass** | same |
| W2 ask | Context recall | ≥ 0.85 | RAGAS **0.958** | **Pass** | same |
| W2 ask | Citation / provenance integrity | ≥ 0.95 / resolvable | Deterministic provenance **1.000** (30/30) | **Pass** | [eval-w2-deterministic-20261101T170120Z.json](../docs/evidence/eval-w2-deterministic-20261101T170120Z.json) |
| W2 ask | Scope leaks / foreign doc IDs | **0** | **0** in deterministic + IDOR corpus | **Pass** | W2 suite + [cross_patient_idor.json](./red_team/cross_patient_idor.json) |
| W2 ask | p95 response | < 8 s | **161.8 ms** (n=6) | **Pass** | chat latency JSON above |
| W3 scribe | SOAP field-level F1 | ≥ 0.85 provisional | Not measured with clinical grader | **Missing — variance** | Live draft probe exists; clinician grades open (G-13) |
| W3 scribe | Medicine precision / invented molecules | ≥ 0.95 / **0** | Deterministic grounding + formulary checks in code | **Partial** | Unit/integration; no 40-case clinical F1 report |
| W3 scribe | Doctor review time median | < 90 s | Not measured in role-play cohort | **Missing — variance** | Needs timed clinical role-play |
| W3 scribe | Draft p95 after transcript | < 20 s | **6.23 s** (n=1 Langfuse) | **Indicative pass** | [langfuse-trace-scribe-20261025.json](../docs/evidence/langfuse-trace-scribe-20261025.json) |
| Platform | Error rate under load | < 1% | R1/R3 matched runs **0%** on P | **Pass (rate); capacity not accepted** | [test_report.md](../docs/evidence/test_report.md); `capacity_accepted=false` (G-17) |
| Platform | Judge calibration κ | ≥ 0.6 | κ **null** / unreviewed | **Missing — blocked** | G-16 |
| Red-team | PDF prompt injection | Zero scope/tool bypass | Cases filed in eval set | **Harness present** | [prompt_inject_pdf.json](./red_team/prompt_inject_pdf.json) |

## 2. Suite roll-up

| Suite | Framework | Cases | Status | Headline metrics |
|---|---|---|---|---|
| w1 | deterministic | 30/30 | passed | red_flag_recall=1.0, FP=0.0 |
| w2 | deterministic | 30/30 | passed | provenance_integrity=1.0 |
| rag_w3 | RAGAS 0.4.x | 24 | scored | faith=0.801, relevancy=0.454, ctx_p=0.958, ctx_r=0.958 |
| qa_x01 | DeepEval | 14/24 pass | scored | faith=0.728, relevancy=0.647; failures retained per case |
| safety gate (combined) | deterministic | 60/60 | **passed** | release_gate uses this basis only |

## 3. Honest limitations

- Answer-quality scores use **synthetic authored fixtures**, not live pipeline transcripts (except where live probes are separately linked).
- Judge is **untrusted** until human calibration (G-16).
- Clinical hi/mr copy remains **unreviewed** (G-01/G-02).
- Load evidence on host profile **P** must not be labelled clinic capacity (G-17).

## 4. Gate recommendation

| Gate | Recommendation |
|---|---|
| Safety (MC-10/11/12/25 safety half) | **Proceed** — deterministic gate green |
| Quality thresholds (faithfulness/relevancy) | **Variance accepted for pilot demo** — numbers recorded; not claimed as clinical validation |
| G6 handover | Include this report + [gaps.md](../docs/gaps.md) residuals; do not waive safety rows |

Mirror: [reports/latest.md](./reports/latest.md).
