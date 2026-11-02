# Load-test datasets (`load_test_*`)

Built by `scripts/load_test_prepare_datasets.py` from checked-in Kaggle extracts under `data/raw/` (no invented public rows).

| File | Source | Purpose |
|---|---|---|
| `load_test_pharmacy_stock.csv` | `medicines` / A-Z Medicine Dataset of India | Pharmacy stock import (`stock_items`) for PERF-05 typeahead/list at volume |
| `load_test_doctors.csv` | `patients` / Healthcare Dataset | Doctor names + clinic/specialty for synthetic load-test appointments |
| `load_test_patients_ref.csv` | same | Reference patient names/conditions (catalogue; Keycloak cohort remains `loadtest.*`) |

Seed into a running stack:

```bash
./scripts/load_test_setup.sh --pharmacy-limit 25000 --doctor-limit 500 --slots 5000 --pdfs 0
```
