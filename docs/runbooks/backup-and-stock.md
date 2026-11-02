# Backup and pharmacy stock-import jobs (G-30)

| Field | Value |
|---|---|
| Alert | Failed/stale `ops.backup` or `ops.stock_import` in `job_runs`; missing nightly archive; stale pharmacy inventory |
| Severity | S2 (S1 if restore point is missing after a data incident) |
| Owner | E2 + platform |
| Last reviewed | 2026-10-31 |

## Symptom

`job_runs` shows `ops.backup` with detail `backup_unconfigured`, or `ops.stock_import` with `stock_drop_unconfigured` / failed file rows. Pharmacy stock looks stale relative to an HIS extract. No encrypted backup directory exists for the current day.

## Scheduled jobs (ARQ)

| Job | Process / queue | Schedule | Behaviour when unconfigured |
|---|---|---|---|
| `ops.backup` (`scheduled_backup_job`) | scheduler / `sahyog:scheduler` | daily 04:05 UTC | Raises `backup_unconfigured` when `BACKUP_OUT_DIR` is empty; `job_runs.status=failed` |
| `ops.stock_import` (`import_pharmacy_stock`) | worker / `sahyog:worker` | every 15 minutes | Raises `stock_drop_unconfigured` when `config/stock.yaml` `drop_dir` is empty; otherwise imports `*.csv` from the drop folder into `stock_items` |

The Compose scheduler/worker image includes `scripts/backup.sh`, but a successful backup usually needs Docker access and a host path **outside** the repository. Treat the ARQ backup job as a stub that fails closed until operators set `BACKUP_OUT_DIR` and provide a runnable backup environment (often host cron instead of in-container Docker).

## Manual backup (preferred until host wiring exists)

```bash
./scripts/backup.sh --out /backups/care-$(date +%Y%m%d-%H%M) \
  --encrypt <age-recipient> \
  --note "manual-$(hostname)"
```

- Never write `--out` inside the git tree.
- Encrypt before the archive leaves the host.
- Restore: `./scripts/restore.sh` and [restore.md](./restore.md).

Optional: set `BACKUP_OUT_DIR=/backups/care-scheduled` in `.env` so the 04:05 job attempts the same script. If the container cannot run Docker, the job remains failed with stderr in `job_runs.detail` — that is intentional visibility, not a silent skip.

## Manual stock import

1. Drop a CSV into the configured incoming directory (default `data/stock/incoming`, see `config/stock.yaml`).
2. Wait for the next worker cron (≤15 min), or call `POST /api/v1/pharmacy/stock/import` with an authorized staff token.
3. Confirm pharmacy UI freshness; failed files land under `data/stock/failed`.

Configure `STOCK_ADAPTER` / `STOCK_SOURCE_PATH` as needed. Staleness is surfaced on medicine flags (`STOCK_STALE_AFTER_MINUTES` / `stale_after_minutes`). Do not invent stock rows.

## First five minutes

1. `SELECT job_name, status, error_code, detail, started_at FROM job_runs WHERE job_name IN ('ops.backup','ops.stock_import') ORDER BY started_at DESC LIMIT 20;`
2. If `backup_unconfigured`: run the manual backup command; open a ticket to set `BACKUP_OUT_DIR` or host cron.
3. If stock failed: inspect `data/stock/failed`, fix schema/codes, re-drop CSV.

## Evidence

- `job_runs.detail` tails (no PHI), backup manifest path/hash, stock import `row_count` / file names only.
