#!/usr/bin/env python3
"""Aggregate-only FinOps showback export.

Uses the live analytics endpoint, which returns app-recorded usage (never prompts or
clinical text) with price, FX and FinOps model provenance.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ops_client import OpsClient, OpsError, env_value  # noqa: E402


def _days(from_date: dt.date | None, to_date: dt.date | None, explicit: int | None) -> int:
    if explicit is not None:
        return explicit
    end = to_date or dt.date.today()
    start = from_date or (end - dt.timedelta(days=29))
    days = (end - start).days + 1
    if days < 1:
        raise OpsError("--from must be on or before --to")
    return min(days, 365)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=dt.date.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=dt.date.fromisoformat)
    parser.add_argument("--days", type=int)
    parser.add_argument("--format", choices=("csv", "json"), default="csv")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    days = _days(args.date_from, args.date_to, args.days)
    client = OpsClient()
    payload = client.get(f"/api/v1/analytics/finops?days={days}", username="admin.ops")
    period = payload.get("period", {})
    rows = payload.get("by_purpose", [])
    record = {
        "status": payload.get("status"),
        "traffic_class": payload.get("traffic_class"),
        "period_start": period.get("start"),
        "period_end": period.get("end"),
        "observed": payload.get("observed"),
        "monthly_run_rate_usd": payload.get("monthly_run_rate_usd"),
        "price_version": payload.get("price_version"),
        "price_basis_date": payload.get("price_basis_date"),
        "fx_usd_inr": payload.get("fx_usd_inr"),
        "finops_model_version": payload.get("finops_model_version"),
        "reconciliation": payload.get("reconciliation"),
        "as_of": payload.get("as_of"),
        "by_purpose": rows,
    }

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or Path("docs/evidence") / f"finops-showback-{stamp}.{args.format}"
    out.parent.mkdir(parents=True, exist_ok=True)

    if args.format == "json":
        out.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(
                [
                    "period_start",
                    "period_end",
                    "status",
                    "traffic_class",
                    "purpose",
                    "model_alias",
                    "calls",
                    "prompt_tokens",
                    "completion_tokens",
                    "cost_usd",
                    "price_version",
                    "price_basis_date",
                    "fx_usd_inr",
                    "finops_model_version",
                    "as_of",
                ]
            )
            if not rows:
                writer.writerow(
                    [
                        period.get("start"),
                        period.get("end"),
                        record["status"],
                        record["traffic_class"],
                        "",
                        "",
                        0,
                        0,
                        0,
                        0,
                        record["price_version"],
                        record["price_basis_date"],
                        record["fx_usd_inr"],
                        record["finops_model_version"],
                        record["as_of"],
                    ]
                )
            for row in rows:
                writer.writerow(
                    [
                        period.get("start"),
                        period.get("end"),
                        record["status"],
                        record["traffic_class"],
                        row.get("purpose"),
                        row.get("model_alias"),
                        row.get("calls"),
                        row.get("prompt_tokens"),
                        row.get("completion_tokens"),
                        row.get("cost_usd"),
                        record["price_version"],
                        record["price_basis_date"],
                        record["fx_usd_inr"],
                        record["finops_model_version"],
                        record["as_of"],
                    ]
                )

    print(
        json.dumps(
            {
                "status": "exported",
                "file": str(out),
                "format": args.format,
                "usage_status": record["status"],
                "calls": (record.get("observed") or {}).get("calls", 0),
                "cost_usd": (record.get("observed") or {}).get("cost_usd", 0),
                "price_version": record["price_version"],
                "fx_usd_inr": record["fx_usd_inr"],
                "note": (
                    "Rolling-window export; use --days for an exact window. "
                    "No prompts, patient identifiers or clinical text are included."
                ),
                "environment": env_value("APP_ENV", "dev"),
            },
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OpsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
