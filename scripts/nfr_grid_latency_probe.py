#!/usr/bin/env python3
"""NFR-PERF-05 / NFR-PERF-08 grid and analytics latency probe (Keycloak roles)."""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
import sys

sys.path.insert(0, str(SCRIPT_DIR))
from ops_client import OpsError, env_value  # noqa: E402

# Front-desk catalogue / list grids (NFR-PERF-05).
GRID_PATHS = [
    "/api/v1/appointments?page=1&page_size=20",
    "/api/v1/doctors?page=1&page_size=20",
    "/api/v1/patients?page=1&page_size=20",
    "/api/v1/notifications?page=1&page_size=20",
    "/api/v1/chat/sessions?page=1&page_size=20",
    "/api/v1/meta",
]
# Patient-scoped record grids (front desk is denied → 403).
PATIENT_RECORD_PATHS = [
    "/api/v1/records/documents?page=1&page_size=20",
    "/api/v1/records/medications?page=1&page_size=20",
]
# Pharmacist / stock search grids (NFR-PERF-05 companion; volume comes from stock_items).
PHARMACY_PATHS = [
    "/api/v1/pharmacy/stock?page=1&page_size=20",
    "/api/v1/pharmacy/stock/typeahead?q=para",
    "/api/v1/pharmacy/stock/status?drug_name=Amoxicillin&clinic_code=BANER",
]
ANALYTICS_PATHS = [
    "/api/v1/analytics/overview",
    "/api/v1/analytics/finops",
]


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(ratio * len(ordered)) - 1)
    return round(ordered[index], 1)


async def token(client: httpx.AsyncClient, username: str) -> str:
    keycloak = env_value("KEYCLOAK_PUBLIC_URL", "http://localhost:5707").rstrip("/")
    realm = env_value("KEYCLOAK_REALM", "sahyog")
    client_id = env_value("KEYCLOAK_CLI_CLIENT_ID", "sahyog-cli")
    client_secret = env_value("KEYCLOAK_CLI_CLIENT_SECRET")
    password = env_value("SEED_DEMO_PASSWORD")
    if not client_secret or not password:
        raise OpsError("KEYCLOAK_CLI_CLIENT_SECRET and SEED_DEMO_PASSWORD are required")
    for attempt in range(4):
        try:
            response = await client.post(
                f"{keycloak}/realms/{realm}/protocol/openid-connect/token",
                data={
                    "grant_type": "password",
                    "client_id": client_id,
                    "client_secret": client_secret,
                    "username": username,
                    "password": password,
                    "scope": "openid profile email",
                },
                timeout=60.0,
            )
            if response.status_code == 200:
                return str(response.json()["access_token"])
            raise OpsError(f"login {username} HTTP {response.status_code}")
        except (httpx.HTTPError, OpsError):
            if attempt == 3:
                raise
            await asyncio.sleep(1 + attempt)
    raise OpsError(f"login failed for {username}")


async def probe_paths(
    client: httpx.AsyncClient,
    *,
    api: str,
    auth: str,
    paths: list[str],
    repeats: int,
    nfr: str,
    target_p95_ms: float,
) -> dict[str, Any]:
    by_path: dict[str, list[float]] = {path.split("?")[0]: [] for path in paths}
    errors = 0
    for _ in range(repeats):
        for path in paths:
            key = path.split("?")[0]
            started = time.perf_counter()
            try:
                response = await client.get(
                    f"{api}{path}",
                    headers={"Authorization": auth},
                    timeout=30.0,
                )
                elapsed = round((time.perf_counter() - started) * 1000, 1)
                if response.status_code not in {200, 204}:
                    errors += 1
                else:
                    by_path[key].append(elapsed)
            except httpx.HTTPError:
                errors += 1
    endpoints: dict[str, Any] = {}
    all_ok: list[float] = []
    for path, times in sorted(by_path.items()):
        all_ok.extend(times)
        p95 = percentile(times, 0.95)
        endpoints[path] = {
            "requests": len(times),
            "p50_ms": percentile(times, 0.50),
            "p95_ms": p95,
            "meets_target": bool(times) and p95 <= target_p95_ms,
        }
    overall_p95 = percentile(all_ok, 0.95)
    return {
        "nfr": nfr,
        "target_p95_ms": target_p95_ms,
        "samples": len(all_ok),
        "errors": errors,
        "p50_ms": percentile(all_ok, 0.50),
        "p95_ms": overall_p95,
        "meets_target": bool(all_ok) and overall_p95 <= target_p95_ms,
        "endpoints": endpoints,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=20)
    parser.add_argument("--front-desk-user", default="loadtest.frontdesk01")
    parser.add_argument("--patient-user", default="loadtest.patient01")
    parser.add_argument("--pharmacist-user", default="pharmacist.kavita")
    parser.add_argument("--admin-user", default="admin.ops")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    api = env_value("API_BASE_URL", "http://localhost:5706").rstrip("/")
    async with httpx.AsyncClient(follow_redirects=False) as client:
        fd = await token(client, args.front_desk_user)
        grid = await probe_paths(
            client,
            api=api,
            auth=f"Bearer {fd}",
            paths=GRID_PATHS,
            repeats=args.repeats,
            nfr="NFR-PERF-05",
            target_p95_ms=500.0,
        )
        patient = await token(client, args.patient_user)
        records = await probe_paths(
            client,
            api=api,
            auth=f"Bearer {patient}",
            paths=PATIENT_RECORD_PATHS,
            repeats=args.repeats,
            nfr="NFR-PERF-05_records",
            target_p95_ms=500.0,
        )
        pharmacist = await token(client, args.pharmacist_user)
        pharmacy = await probe_paths(
            client,
            api=api,
            auth=f"Bearer {pharmacist}",
            paths=PHARMACY_PATHS,
            repeats=args.repeats,
            nfr="NFR-PERF-05_pharmacy",
            target_p95_ms=500.0,
        )
        admin = await token(client, args.admin_user)
        analytics = await probe_paths(
            client,
            api=api,
            auth=f"Bearer {admin}",
            paths=ANALYTICS_PATHS,
            repeats=args.repeats,
            nfr="NFR-PERF-08",
            target_p95_ms=500.0,
        )
    report = {
        "status": "scored",
        "generated_at": datetime.now(UTC).isoformat(),
        "api_base_url": api,
        "probes": [grid, records, pharmacy, analytics],
        "volume_note": (
            "PERF-05 requires documented SCALE-02 volumes; pharmacy search today is "
            "limited by stock_items / config/stock.csv size unless scaled separately."
        ),
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else ROOT / "docs" / "evidence" / f"nfr-grid-latency-{stamp}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"wrote": str(out), "probes": report["probes"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except OpsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2) from exc
