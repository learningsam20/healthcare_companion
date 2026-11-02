#!/usr/bin/env python3
"""Measure NFR-PERF workflow service times against the public API.

Probes (Keycloak loadtest.* cohort only):
  NFR-PERF-01  W1 triage turn p95 < 4s
  NFR-PERF-02  W2 record-ask p95 < 8s (skips if no indexed docs)
  NFR-PERF-07  Chat first-token / non-stream completion budget < 2s warm (best-effort)
  NFR-PERF-03  W3 draft p95 < 20s (optional --scribe; needs doctor loadtest user)

Writes docs/evidence/workflow-latency-*.json for test_report.md.
"""

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
sys_path_note = ""
import sys

sys.path.insert(0, str(SCRIPT_DIR))
from ops_client import OpsError, env_value  # noqa: E402


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
        timeout=30.0,
    )
    if response.status_code != 200:
        raise OpsError(f"Keycloak login failed for {username}: HTTP {response.status_code}")
    return str(response.json()["access_token"])


async def timed(
    client: httpx.AsyncClient, method: str, url: str, **kwargs: Any
) -> tuple[int, float, dict[str, Any] | None]:
    started = time.perf_counter()
    response = await client.request(method, url, **kwargs)
    elapsed_ms = round((time.perf_counter() - started) * 1000, 1)
    body: dict[str, Any] | None
    try:
        payload = response.json()
        body = payload if isinstance(payload, dict) else None
    except Exception:  # noqa: BLE001
        body = None
    return response.status_code, elapsed_ms, body


async def probe_triage(client: httpx.AsyncClient, api: str, auth: str, n: int) -> dict[str, Any]:
    times: list[float] = []
    errors = 0
    for _ in range(n):
        session_code, _, session = await timed(
            client,
            "POST",
            f"{api}/api/v1/chat/sessions",
            headers={"Authorization": auth},
            json={"title": "Workflow latency triage"},
            timeout=60.0,
        )
        if session_code not in {200, 201} or not session or not session.get("id"):
            errors += 1
            continue
        sid = session["id"]
        code, ms, _ = await timed(
            client,
            "POST",
            f"{api}/api/v1/chat/sessions/{sid}/messages",
            headers={"Authorization": auth},
            json={
                "content": "I have a sore throat and mild cough for 3 days. No fever. Baner clinic.",
                "language": "en-IN",
            },
            timeout=90.0,
        )
        if code not in {200, 201, 202}:
            errors += 1
        else:
            times.append(ms)
        try:
            await client.delete(
                f"{api}/api/v1/chat/sessions/{sid}",
                headers={"Authorization": auth},
                timeout=20.0,
            )
        except Exception:  # noqa: BLE001 - cleanup must not discard measured samples
            pass
    p95 = percentile(times, 0.95)
    return {
        "nfr": "NFR-PERF-01",
        "name": "w1_triage_turn",
        "target_p95_ms": 4000.0,
        "samples": len(times),
        "errors": errors,
        "p50_ms": percentile(times, 0.50),
        "p95_ms": p95,
        "p99_ms": percentile(times, 0.99),
        "meets_target": bool(times) and p95 <= 4000.0,
    }


async def probe_ask(client: httpx.AsyncClient, api: str, auth: str, n: int) -> dict[str, Any]:
    times: list[float] = []
    errors = 0
    skipped = 0
    docs = await client.get(
        f"{api}/api/v1/records/documents?page=1&page_size=5",
        headers={"Authorization": auth},
        timeout=30.0,
    )
    items = (docs.json() or {}).get("items") if docs.status_code == 200 else None
    indexed = [
        item
        for item in (items or [])
        if isinstance(item, dict) and str(item.get("status", "")).lower() == "indexed"
    ]
    if not indexed:
        return {
            "nfr": "NFR-PERF-02",
            "name": "w2_record_ask",
            "target_p95_ms": 8000.0,
            "samples": 0,
            "errors": 0,
            "skipped": True,
            "skip_reason": "no indexed documents for loadtest patient",
            "meets_target": None,
        }
    for _ in range(n):
        session_code, _, session = await timed(
            client,
            "POST",
            f"{api}/api/v1/chat/sessions",
            headers={"Authorization": auth},
            json={"title": "Workflow latency ask"},
            timeout=60.0,
        )
        if session_code not in {200, 201} or not session or not session.get("id"):
            errors += 1
            continue
        sid = session["id"]
        code, ms, _ = await timed(
            client,
            "POST",
            f"{api}/api/v1/chat/sessions/{sid}/messages",
            headers={"Authorization": auth},
            json={
                "content": "What problems and medicines are listed in my recent documents? Cite sources.",
                "language": "en-IN",
            },
            timeout=120.0,
        )
        if code not in {200, 201, 202}:
            errors += 1
        else:
            times.append(ms)
        try:
            await client.delete(
                f"{api}/api/v1/chat/sessions/{sid}",
                headers={"Authorization": auth},
                timeout=20.0,
            )
        except Exception:  # noqa: BLE001
            pass
    p95 = percentile(times, 0.95)
    return {
        "nfr": "NFR-PERF-02",
        "name": "w2_record_ask",
        "target_p95_ms": 8000.0,
        "samples": len(times),
        "errors": errors,
        "skipped": skipped > 0,
        "p50_ms": percentile(times, 0.50),
        "p95_ms": p95,
        "p99_ms": percentile(times, 0.99),
        "meets_target": bool(times) and p95 <= 8000.0,
    }


async def probe_ttft_proxy(client: httpx.AsyncClient, api: str, auth: str, n: int) -> dict[str, Any]:
    """Best-effort warm completion latency as a TTFT proxy when SSE TTFT is unavailable."""
    times: list[float] = []
    errors = 0
    # warm
    await timed(
        client,
        "POST",
        f"{api}/api/v1/chat/sessions",
        headers={"Authorization": auth},
        json={"title": "warm"},
        timeout=60.0,
    )
    for _ in range(n):
        session_code, _, session = await timed(
            client,
            "POST",
            f"{api}/api/v1/chat/sessions",
            headers={"Authorization": auth},
            json={"title": "ttft proxy"},
            timeout=60.0,
        )
        if session_code not in {200, 201} or not session or not session.get("id"):
            errors += 1
            continue
        sid = session["id"]
        code, ms, _ = await timed(
            client,
            "POST",
            f"{api}/api/v1/chat/sessions/{sid}/messages",
            headers={"Authorization": auth},
            json={"content": "Say only: ok", "language": "en-IN"},
            timeout=60.0,
        )
        if code not in {200, 201, 202}:
            errors += 1
        else:
            times.append(ms)
        try:
            await client.delete(
                f"{api}/api/v1/chat/sessions/{sid}",
                headers={"Authorization": auth},
                timeout=20.0,
            )
        except Exception:  # noqa: BLE001
            pass
    p95 = percentile(times, 0.95)
    return {
        "nfr": "NFR-PERF-07",
        "name": "chat_completion_warm_proxy",
        "target_p95_ms": 2000.0,
        "note": "Full response latency used as conservative TTFT proxy; SSE ttft span preferred when exported.",
        "samples": len(times),
        "errors": errors,
        "p50_ms": percentile(times, 0.50),
        "p95_ms": p95,
        "p99_ms": percentile(times, 0.99),
        "meets_target": bool(times) and p95 <= 2000.0,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--samples", type=int, default=12, help="samples per workflow probe")
    parser.add_argument("--patient-user", default="loadtest.patient01")
    parser.add_argument("--out", default="")
    args = parser.parse_args()
    api = env_value("API_BASE_URL", "http://localhost:5706").rstrip("/")
    async with httpx.AsyncClient(follow_redirects=False) as client:
        tok = await token(client, args.patient_user)
        auth = f"Bearer {tok}"
        me = await client.get(f"{api}/api/v1/auth/me", headers={"Authorization": auth}, timeout=20.0)
        if me.status_code != 200 or (me.json() or {}).get("traffic_class") != "synthetic":
            raise OpsError(f"{args.patient_user} must be a synthetic loadtest identity")
        triage = await probe_triage(client, api, auth, args.samples)
        ask = await probe_ask(client, api, auth, args.samples)
        ttft = await probe_ttft_proxy(client, api, auth, min(args.samples, 8))
    report = {
        "status": "scored",
        "generated_at": datetime.now(UTC).isoformat(),
        "api_base_url": api,
        "patient_user": args.patient_user,
        "probes": [triage, ask, ttft],
        "notes": [
            "Uses Keycloak password grant against loadtest.* only.",
            "NFR-PERF-03 scribe draft is measured from Langfuse/API traces or a doctor-role probe; not included here.",
            "NFR-PERF-04 booking median < 3 min requires an instrumented UX/Playwright run.",
        ],
    }
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    out = Path(args.out) if args.out else ROOT / "docs" / "evidence" / f"workflow-latency-{stamp}.json"
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
