# Contract: patients (public)

| Field | Value |
|---|---|
| Source id | `patients` |
| Name | Healthcare Dataset (Kaggle; the upstream dataset is labelled synthetic) |
| Origin | Kaggle `prasad22/healthcare-dataset` |
| Licence | Check and record on download |
| Sensitivity | deidentified_public |
| Owner | Data owner |
| Schema version | 1 |
| Freshness | On each `--download` |
| Consumers | Patient/encounter master for demo scale |
| Checks | Row count; discharge-before-admission = 0 |
| Exact row count | 55500 |
| SHA-256 | `d8c23c7dddaf0e1f5daf26182eb908c219d28a63bb574377c3ba6cb09be8a342` |
| Checked at | 2026-10-31T16:57:20Z |
| Note | Upstream “synthetic” label is the public dataset’s own classification; it still counts as a public source under FR-DATA-01, not as Sahyog seed data. |
