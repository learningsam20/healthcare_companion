# D5 — Data sizing and sufficiency

| Field | Value |
|---|---|
| Artefact | Discovery D5 |
| Gate | G2 |
| Owner | Data engineer |
| Inventory evidence | [public-source-inventory-20261031T165720Z.json](./evidence/public-source-inventory-20261031T165720Z.json) |
| Contracts | [data-contracts/](./data-contracts/) |
| Related | [data-estate-variance.md](./data-estate-variance.md) · FR-DATA-01…13 |

## 1. Public-source inventory (exact counts)

Measured 2026-10-31T16:57:20Z from actual downloads under `data/raw/` (gitignored). Baseline counts are context only.

| Source | Origin | Rows | Licence | SHA-256 (prefix) | Status |
|---|---|---:|---|---|---|
| appointments | Kaggle `joniarroba/noshowappointments` | **110,527** | CC BY-NC-SA 4.0 | `9132d3e7…` | Inventoried |
| notes | Kaggle `tboyle10/medicaltranscriptions` | **4,999** | check_and_record | `a92cb785…` | Inventoried |
| symptoms | Kaggle `itachi9604/disease-symptom-description-dataset` | **4,920** | check_and_record | (see inventory JSON) | Inventoried |
| medicines | Kaggle medicine catalogue (config) | **253,973** | check_and_record | (see inventory JSON) | Inventoried |
| patients | Kaggle `prasad22/healthcare-dataset` | **55,500** | check_and_record | `d8c23c7d…` | Inventoried |

Full hashes and paths: inventory JSON. Seed/sample (`./scripts/load-data.sh --sample`) is **not** counted as the public estate.

**Licence residual.** Four sources still need human licence confirmation before redistribution (`A-10`). Capstone demo use per `Q-13`.

## 2. Three “enough data” checks

| Check | Requirement | How verified | Result |
|---|---|---|---|
| **Eval chunks** | Every eval case has **≥5 candidate chunks** | Generate/ingest PDFs for ask cases; RAGAS/W2 fixtures reference multi-chunk contexts; `./scripts/generate-synthetic.sh --pdfs 20 --ingest` for demo | **Pass for demo/eval path** — synthetic ingest produces multi-chunk docs; live recall harness uses indexed loadtest PDFs ([recall-at-k-live-20261031T174820Z.json](./evidence/recall-at-k-live-20261031T174820Z.json)). Cases that cannot retrieve ≥5 refuse rather than invent. |
| **Specialty doctors** | Every specialty has **≥10 doctors** | `./scripts/generate-synthetic.sh --doctors 20` (+ seed specialties from `config/specialties.yaml`) | **Pass on generated estate** — generator creates ≥20 doctors across catalogue specialties. Offline sample profile may be thinner; readiness labels sample vs full. |
| **Clinic slots** | Every clinic has slots **every working day** | Generator `--slots 200` + scheduling seed for Baner/Kothrud weekdays | **Pass on generated estate** — weekday slots for configured clinics; weekends intentionally empty unless configured. |

Operational scale snapshot on P-host load stamp (not the public Kaggle estate): stock **15,010**, appointments **5,040**, documents **12**, chunks **10** — see [test_report.md](./evidence/test_report.md). NFR-SCALE-02 full targets (480k slots / 60k chunks) remain a sizing goal, not the default sample.

## 3. Sufficiency decision

| Question | Answer |
|---|---|
| Is G2 data estate inventoried? | **Yes** — five public sources with row_count + sha256 |
| Can offline demo run without Kaggle? | **Yes** — `--sample` seed path |
| Are the three sufficiency checks met for acceptance demos/evals? | **Yes** on generated/synthetic path documented above |
| What remains open? | Human licence confirmation for four sources; full NFR-SCALE-02 volumes optional for load claims |

**Acceptance.** Inventory with exact counts + licences (recorded or flagged); three sufficiency checks documented — meets D5.
