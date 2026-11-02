#!/usr/bin/env python3
"""G-24: live preference memory put → list → purge against a running API.

Records evidence JSON. Never invents a pass. closes_gap is always false until an
operator confirms Mem0 sync + Settings provenance UI.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from ops_client import OpsClient, OpsError, env_value  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--username", default="patient.priya")
    parser.add_argument(
        "--out",
        type=Path,
        default=ROOT
        / "docs"
        / "evidence"
        / f"mem0-forget-e2e-{datetime.now(UTC).strftime('%Y%m%dT%H%M%SZ')}.json",
    )
    args = parser.parse_args()

    client = OpsClient()
    steps: list[dict[str, Any]] = []
    key = "preferred_clinic"
    # Keep non-clinical; avoid digits/identifiers that trip the memory gate.
    value = "Baner"
    ok = True

    def record(name: str, *, success: bool, detail: Any = None, error: str | None = None) -> None:
        nonlocal ok
        if not success:
            ok = False
        entry: dict[str, Any] = {"name": name, "ok": success}
        if detail is not None:
            entry["detail"] = detail
        if error:
            entry["error"] = error[:500]
        steps.append(entry)

    try:
        put = client._http(  # noqa: SLF001
            "PUT",
            f"{client.api}/api/v1/me/memory",
            token=client.token(args.username),
            body={"key": key, "value": value},
        )
        record("put_preference", success=True, detail={"key": key, "id": getattr(put, "get", lambda *_: None)("id") if isinstance(put, dict) else None})
    except Exception as exc:  # noqa: BLE001
        record("put_preference", success=False, error=str(exc))

    try:
        listed = client.get("/api/v1/me/memory", username=args.username)
        found = isinstance(listed, list) and any(
            isinstance(row, dict) and row.get("key") == key for row in listed
        )
        record("preference_present_after_put", success=found, detail={"count": len(listed) if isinstance(listed, list) else 0})
    except Exception as exc:  # noqa: BLE001
        record("preference_present_after_put", success=False, error=str(exc))

    try:
        client.post("/api/v1/me/memory/purge", {}, username=args.username)
        record("purge_all", success=True)
    except Exception as exc:  # noqa: BLE001
        record("purge_all", success=False, error=str(exc))

    try:
        listed_after = client.get("/api/v1/me/memory", username=args.username)
        gone = isinstance(listed_after, list) and not any(
            isinstance(row, dict) and row.get("key") == key for row in listed_after
        )
        record("preference_absent_after_purge", success=gone)
    except Exception as exc:  # noqa: BLE001
        record("preference_absent_after_purge", success=False, error=str(exc))

    mem0_probe: dict[str, Any] = {
        "env_mem0_url": bool(env_value("MEM0_URL")),
        "reachable": False,
    }
    for candidate in (
        env_value("MEM0_PUBLIC_URL", ""),
        "http://127.0.0.1:5730",
        os.environ.get("MEM0_URL", ""),
    ):
        url = (candidate or "").rstrip("/")
        if not url or "mem0:" in url:
            continue
        try:
            with urllib.request.urlopen(url + "/", timeout=3) as resp:  # noqa: S310
                mem0_probe["reachable"] = resp.status < 500
                mem0_probe["probed"] = url
                mem0_probe["http_status"] = resp.status
                break
        except (urllib.error.URLError, TimeoutError, ValueError) as exc:
            mem0_probe["last_error"] = str(exc)[:200]

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "gap": "G-24",
        "status": "passed" if ok else "failed",
        "username": args.username,
        "closes_gap": False,
        "note": (
            "API put/list/purge exercised. Gap stays Mitigated until live Mem0 store "
            "sync and Settings provenance UI are operator-confirmed."
        ),
        "mem0": mem0_probe,
        "steps": steps,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"out": str(args.out), "status": report["status"]}, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except OpsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
