#!/usr/bin/env python3
"""Capture a timestamped analytics snapshot from the live API.

Analytics in this build are computed at request time; this tool persists the exact live
response for evidence. It is not a database rollup and says so in the output.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ops_client import OpsClient, OpsError  # noqa: E402

ENDPOINTS = {
    "overview": "/api/v1/analytics/overview",
    "quality": "/api/v1/analytics/quality",
    "compliance": "/api/v1/analytics/compliance",
    "evaluations": "/api/v1/analytics/evaluations",
    "finops": "/api/v1/analytics/finops",
    "insights": "/api/v1/analytics/insights",
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=dt.date.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=dt.date.fromisoformat)
    parser.add_argument("--days", type=int)
    parser.add_argument("--live", action="store_true", help="Write the snapshot file")
    parser.add_argument("--metric", action="append", default=[], help="Limit tile ids")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.days is not None:
        days = args.days
    else:
        end = args.date_to or dt.date.today()
        start = args.date_from or (end - dt.timedelta(days=29))
        days = (end - start).days + 1
    if not 1 <= days <= 365:
        raise OpsError("window must be between 1 and 365 days")

    client = OpsClient()
    captured: dict[str, object] = {}
    for name, path in ENDPOINTS.items():
        payload = client.get(f"{path}?days={days}", username="admin.ops")
        if args.metric:
            for key in ("tiles", "metrics"):
                if isinstance(payload, dict) and isinstance(payload.get(key), list):
                    payload[key] = [tile for tile in payload[key] if tile.get("id") in args.metric]
        captured[name] = payload

    if not args.live:
        print(
            json.dumps(
                {
                    "status": "dry_run",
                    "days": days,
                    "sections": list(captured),
                    "note": "Pass --live to write the snapshot file.",
                },
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or Path("docs/evidence") / f"analytics-snapshot-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    document = {
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "mode": "live_computed",
        "window_days": days,
        "sections": captured,
        "note": (
            "Analytics are computed at request time in this build. "
            "This file is a frozen copy, not a scheduled database rollup."
        ),
    }
    out.write_text(json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(
        json.dumps(
            {
                "status": "captured",
                "file": str(out),
                "days": days,
                "sections": {
                    name: payload.get("status")
                    for name, payload in captured.items()
                    if isinstance(payload, dict) and payload.get("status")
                },
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
