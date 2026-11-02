# Data contracts (FR-DATA-06)

Fourteen contracts are filed here: five public sources (`appointments`, `notes`,
`symptoms`, `medicines`, `patients`) plus nine application contracts
(`scheduling`, `stock`, `embeddings`, `audit`, `notifications`, `usage`,
`consent`, `fhir_crosswalk`, `loadtest_cohort`).

**Sensitivity classes.** Each contract has a Sensitivity column. Compliance-in-role
sign-off: [COMPLIANCE-SIGNOFF.md](./COMPLIANCE-SIGNOFF.md) (demo estate — not a
production DPA).

**Rule.** Exact row counts, licences and SHA-256 hashes are written only after an
actual download/inventory run (`scripts/load_public_sources.py`). Baseline counts in
[setup.md](../setup.md) §9.1 are context, not verification. Seed/sample data is
separate (`kind: seed`) and must never be reported as the public estate (G-35).
Sizing sufficiency: [d5-sizing.md](../d5-sizing.md).
