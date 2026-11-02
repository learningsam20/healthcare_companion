# D4 — Sensitivity class sign-off

| Field | Value |
|---|---|
| Artefact | Compliance-in-role review of data-contract sensitivity classes |
| Date | 2026-11-02 |
| Role | Compliance officer (demo realm: `compliance.auditor`) |
| Scope | Fourteen contracts under [./](./) |

## Attestation

I have reviewed the **Sensitivity** column on each contract in this folder.

| Class used | Meaning | Approved for demo estate? |
|---|---|---|
| `deidentified_public` | Public/Kaggle-style sources treated as non-PHI for this demo | Yes — still licence-constrained |
| `synthetic_seed` / `generated` / `synthetic_test` | Authored or generated demo rows | Yes |
| `operational` | Scheduling/stock/usage without clinical narrative | Yes |
| `aggregate` | Analytics/FinOps aggregates | Yes |
| `patient-linked` / `patient-linked identifiers` | Consents, FHIR crosswalk, embeddings follow source | Yes — access via AuthZ only |
| `operational (may reference patient ids)` | Audit metadata | Yes — no clinical body text |

**Statement.** Classes are appropriate for a **synthetic/public demonstration**. This is **not** a DPDP/DPA production clearance and does not authorize real patient data or enabling external egress (see G-19).

| Field | Value |
|---|---|
| Reviewer name | Compliance Auditor (seed role) |
| Reviewer role | `compliance` |
| Signed at | 2026-11-02T12:00:00+05:30 |
| Method | In-role review against contracts + [d5-sizing.md](../d5-sizing.md) inventory |

Production redeployment requires a named client compliance officer countersignature.
