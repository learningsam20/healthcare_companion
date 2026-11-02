# D2 — Discovery questions

| Field | Value |
|---|---|
| Artefact | Discovery D2 |
| Gate | G0 |
| Owner | engineering lead |
| Posted | Answers recorded 2026-10-25 in [spec.md §10](./spec.md#10-open-questions) |
| Question set | Ten questions: three from the baseline brief, seven written for this product |
| Answers land in | [d3-assumptions.md](./d3-assumptions.md) |

Each question names the **decision it unlocks**. Answers are authoritative; defaults retained only for history.

## Ten discovery questions

| # | Source | Question | Decision unlocked | Answer (summary) | Assumption row |
|---|---|---|---|---|---|
| DQ-01 | **Baseline** | Must identified clinical text ever leave the boundary to an external model? | Egress architecture, W3 locality, LiteLLM alias classes | External = de-identified only; W3 identified defaults local (`Q-02`) | A-02 |
| DQ-02 | **Baseline** | Compose-only acceptance, or Kubernetes also required? | Deploy topology, G4 evidence, ops staffing | Compose reference + K8s-ready manifests (`Q-12`) | A-08, A-11 |
| DQ-03 | **Baseline** | On-prem / colo / India cloud / hybrid for pilot vs production? | D6 scoring, capex/opex, hybrid egress boundary | Pilot Mac then on-prem/colo if rack+ops else India cloud; production managed India cloud unless policy forces on-prem (`Q-25`) | A-13, A-15 |
| DQ-04 | Team | Are SMS/email/Slack/FHIR credentials real adapters or mocks? | Integration honesty, notification claims | Real adapters; credentials via env/vault; missing → `unconfigured` (`Q-11`, `D-21`) | A-03, A-14 |
| DQ-05 | Team | Is Slack staff-only, or also opt-in patients? | Notification threat model, dual audiences | Staff + opt-in patients with verified Slack identity (`Q-24`, `Q-31`) | A-14 |
| DQ-06 | Team | English-first with i18n later, or en/hi/mr from R1? | UI, eval sets, model routing | en/hi/mr + mixed input from R1; gaps documented (`Q-14`, `D-10`) | A-16 |
| DQ-07 | Team | May LiteLLM MCP gateway carry signed per-run `_context`? | Broker design, scope-guard integrity | Yes; spike with fallback registry; never remove scope guard (`Q-05`) | A-07 |
| DQ-08 | Team | RAGAS only, DeepEval required, or both behind one runner? | Eval harness, G5 report shape | RAGAS for RAG; DeepEval for non-RAG; shared `EvalRunner` (`Q-20`) | A-01 (judge path) |
| DQ-09 | Team | What host and model footprint is the pilot? | Model aliases, memory budget, STT/decider choice | Mac M4 Pro 26 GB; purpose-specific small models (`Q-10`, `Q-28`) | A-08, A-09, A-16 |
| DQ-10 | Team | Showback or chargeback; which FinOps commercial model? | Analytics/FinOps R1 scope | Configurable prices/budgets; **showback** in R1; chargeback deferred (`Q-23`) | A-15 |

### Baseline vs team mix

| Source | Count | IDs |
|---|---:|---|
| Baseline brief | 3 | DQ-01, DQ-02, DQ-03 |
| Team-authored | 7 | DQ-04 … DQ-10 |

**Acceptance.** Ten questions, each tied to a decision, with answers mirrored into the assumptions register.

## Traceability to the full Q register

The product owner also answered Q-01…Q-32 in [spec.md §10](./spec.md#10-open-questions). Those answers seed product decisions `D-01`…`D-28` and ADRs. D2 deliberately keeps a **ten-question** decision set for the discovery gate; the broader register remains the normative Q&A log.
