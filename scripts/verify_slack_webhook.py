#!/usr/bin/env python3
"""G-07: validate Slack webhook URL shape and optional dry-run POST."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request

SLACK_HOOK_RE = re.compile(r"^https://hooks\.slack\.com/services/[A-Za-z0-9/_-]+$")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default=os.environ.get("SLACK_WEBHOOK_URL", ""))
    parser.add_argument("--post", action="store_true", help="Send a dry-run test message")
    parser.add_argument("--out", type=argparse.FileType("w"), default="-")
    args = parser.parse_args()
    url = (args.url or "").strip()
    report: dict = {
        "configured": bool(url),
        "shape_ok": bool(url and SLACK_HOOK_RE.match(url)),
        "posted": False,
        "http_status": None,
        "error": None,
    }
    if not url:
        report["error"] = "SLACK_WEBHOOK_URL unset"
    elif not report["shape_ok"]:
        report["error"] = "webhook URL does not match hooks.slack.com/services/..."
    elif args.post:
        body = json.dumps({"text": "Sahyog notification dry-run (G-07)"}).encode()
        req = urllib.request.Request(
            url,
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                report["http_status"] = getattr(resp, "status", 200)
                report["posted"] = report["http_status"] in {200, 201}
        except urllib.error.HTTPError as exc:
            report["http_status"] = exc.code
            report["error"] = str(exc)
        except Exception as exc:  # noqa: BLE001
            report["error"] = str(exc)
    payload = json.dumps(report, indent=2, sort_keys=True) + "\n"
    args.out.write(payload)
    if not report["configured"] or not report["shape_ok"]:
        return 2
    if args.post and not report["posted"]:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
