#!/usr/bin/env python3
"""Export audit events through the compliance-scoped API.

The audit endpoint returns IDs, actions, roles and non-clinical metadata. This export
refuses to include clinical text because the API never records it there.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import sys
from pathlib import Path
from urllib.parse import urlencode

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ops_client import OpsClient, OpsError  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--from", dest="date_from", type=dt.date.fromisoformat)
    parser.add_argument("--to", dest="date_to", type=dt.date.fromisoformat)
    parser.add_argument("--actor", help="Search actor subject")
    parser.add_argument("--action", help="Filter by exact audit action")
    parser.add_argument("--format", choices=("json", "csv"), default="json")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()

    if args.date_from and args.date_to and args.date_from > args.date_to:
        raise OpsError("--from must be on or before --to")

    params: dict[str, str] = {}
    if args.date_from:
        params["date_from"] = args.date_from.isoformat()
    if args.date_to:
        params["date_to"] = args.date_to.isoformat()
    if args.actor:
        params["q"] = args.actor
    if args.action:
        params["action"] = args.action
    query = f"?{urlencode(params)}" if params else ""

    client = OpsClient()
    items = client.paged(f"/api/v1/admin/audit{query}", username="compliance.auditor")

    stamp = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    out = args.out or Path("docs/evidence") / f"audit-export-{stamp}.{args.format}"
    out.parent.mkdir(parents=True, exist_ok=True)
    if args.format == "json":
        out.write_text(json.dumps(items, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    else:
        fields = sorted({key for item in items for key in item})
        with out.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(handle, fieldnames=fields)
            writer.writeheader()
            for item in items:
                writer.writerow(
                    {
                        key: json.dumps(value) if isinstance(value, (dict, list)) else value
                        for key, value in item.items()
                    }
                )

    print(
        json.dumps(
            {
                "status": "exported",
                "file": str(out),
                "events": len(items),
                "format": args.format,
                "filters": params,
                "note": "No clinical text or prompts are present in audit records.",
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
