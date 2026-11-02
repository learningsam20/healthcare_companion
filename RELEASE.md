# Release notes — Sahyog Care Companion

| Field | Value |
|---|---|
| Product | Sahyog Care Companion |
| Version | **0.1.0** (pilot-shipable demo) |
| Date | 2026-11-02 |
| Tier | Pilot demo on Compose (`minimal` / `core` / `full`) |
| Git SHA | _not applicable — delivery tree has no `.git` history in this workspace_ |
| Gate | [docs/gates/G6.md](docs/gates/G6.md) |

## Summary

Pilot-shipable care companion: Keycloak auth, W1 triage/booking, W2 cited records ask, W3 scribe with human sign, notifications (email/Slack staff), analytics/FinOps showback, MCP tool broker, eval harness, Compose start path, Kubernetes manifests ready.

## What changed in this package

- Canonical discovery pack D1–D7 filed under `docs/`.
- Tech-stack ADRs under `docs/adr/` (including D6 hosting and ADR-41 change request).
- Architecture pack diagrams under `docs/diagrams/`.
- Evaluation report with §8.3 targets: `evals/report.md`.
- Cost sheet, gate records, executive memo, silent demo recording package.
- Application residuals and honesty register remain in `docs/gaps.md` v1.16+.

## Migrations / config / flags

| Area | Notes |
|---|---|
| Migrations | Alembic head includes `0023_w1_w3_innovations` (no-show risk, scribe/review columns, etc.) |
| Config | `config/*.yaml` versioned; secrets via `.env` / vault (`SECRETS_BACKEND`) |
| Safety flags | Locked: egress, auto-sign, Langfuse content capture, PII gate disable — see `config/features.yaml` / env |
| Default egress | `EXTERNAL_EGRESS_ENABLED=false` |

## How to run

```bash
cp .env.example .env   # fill credentials; change defaults
./scripts/start.sh --profile minimal
# or host app + Docker deps:
./scripts/start.sh --profile full --local
./scripts/seed-users.sh
./scripts/load-data.sh --sample
./scripts/smoke.sh
```

Web (Compose): http://localhost:5705 · Host Vite: http://localhost:5729 · API: http://localhost:5706

## Rollback

1. `./scripts/stop.sh` — stop containers; volumes retained unless explicitly removed.
2. Do **not** downgrade past a migration that added clinical/audit constraints without a written plan; prefer forward fix.
3. Feature flags: disable non-safety product flags via env; safety flags cannot be turned off to “roll back” controls.
4. Restore: `scripts` backup/restore path + [docs/runbooks/restore.md](docs/runbooks/restore.md); encrypted backup evidence under `docs/evidence/`.

## Known limitations

See [docs/gaps.md](docs/gaps.md) and [docs/evidence/ship-caveats.md](docs/evidence/ship-caveats.md). Not a validated medical device. No production capacity claim on laptop host profile P.
