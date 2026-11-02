# G-21 analytics small-cell suppression

| Field | Value |
|---|---|
| Config key | `analytics.small_cell_minimum` |
| Default | `5` |
| Behaviour | Values below the minimum are suppressed (never rendered as zero) |
| Code | `apps/api/app/modules/analytics/router.py`, `jobs.py` |
| Status | Documented for compliance review; threshold change requires privacy owner |

This closes the “document thresholds to compliance” control for G-21. Changing the
minimum still needs a privacy review before production.
