#!/usr/bin/env python3
"""Real-user-safe synthetic load test over the public API.

Authenticates the tagged `loadtest.*` Keycloak cohort with the real password grant,
drives the same HTTP endpoints as the SPA and never writes to the database directly.
The admin load-guard endpoint supplies real-activity and synthetic-cost counters; the
full profile adds Prometheus p95/error guardrails for real traffic.

Outputs (G-17): the JSON evidence file plus ``docs/evidence/load_test_report.md`` (override
with ``--report-md``; skipped for ``--dry-run`` so a preflight never overwrites the last
real report). Re-render without load: ``--render-from docs/evidence/<run>.json``.

G-22 drill: ``LOAD_TEST_KILL=1`` injects an over-budget cost into the first guard sample
so ``decide_guard_abort`` stops the run with ``budget_guard``. The report is labelled
``kill_drill_*`` and never counts as capacity evidence.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import math
import os
import random
import sys
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(SCRIPT_DIR))

from ops_client import OpsError, env_value  # noqa: E402

PROFILE_RATES = {"r1": 500, "r2": 500, "r3": 1400, "ml": 1400}
TARGET_P95_MS = {"r1": 1500.0, "r2": 1500.0, "r3": 2000.0, "ml": 2000.0}
VALID_STATUS = {200, 201, 202, 204}
_RNG = random.SystemRandom()
DEFAULT_REPORT_MD = ROOT / "docs" / "evidence" / "load_test_report.md"
DEFAULT_TEST_REPORT_MD = ROOT / "docs" / "evidence" / "test_report.md"

# Map public API paths exercised by the load driver to NFR latency buckets.
# Workflow p95 targets (triage 4s / ask 8s / draft 20s / TTFT 2s) require
# --include-llm or separate graph probes — they are not claimed from CRUD GETs.
ENDPOINT_NFR: dict[str, str] = {
    "/api/v1/appointments": "NFR-PERF-05",
    "/api/v1/chat/sessions": "NFR-PERF-05",
    "/api/v1/doctors": "NFR-PERF-05",
    "/api/v1/doctors/Dr.%20Ananya%20Rao/slots": "NFR-PERF-05",
    "/api/v1/me/memory": "NFR-PERF-05",
    "/api/v1/meta": "NFR-PERF-05",
    "/api/v1/notifications": "NFR-PERF-05",
    "/api/v1/patients": "NFR-PERF-05",
    "/api/v1/records/documents": "NFR-PERF-05",
    "/api/v1/records/medications": "NFR-PERF-05",
    "/api/v1/analytics/overview": "NFR-PERF-08",
    "/api/v1/analytics/finops": "NFR-PERF-08",
    "/api/v1/chat/sessions/{session_id}/messages": "NFR-PERF-01/02/07",
}


@dataclass
class Sample:
    endpoint: str
    status: int
    elapsed_ms: float


@dataclass
class GuardState:
    allow_real_users: bool
    abort_on_real_slo: bool
    real_slo_p95_ms: int
    real_slo_error_pct: float
    budget_usd: float
    baseline_cost_usd: float = 0.0
    aborts: list[str] = field(default_factory=list)
    samples: list[dict[str, Any]] = field(default_factory=list)
    prometheus_available: bool = False
    # G-22 drill: LOAD_TEST_KILL=1 injects a budget overrun into the first guard
    # sample so the real decide_guard_abort -> stop-traffic path is exercised.
    kill_drill: bool = False
    kill_injected: bool = False


def kill_drill_enabled() -> bool:
    raw = os.environ.get("LOAD_TEST_KILL") or env_value("LOAD_TEST_KILL", "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def parse_duration(value: str) -> float:
    raw = value.strip().lower()
    try:
        if raw.endswith("h"):
            return float(raw[:-1]) * 3600
        if raw.endswith("m"):
            return float(raw[:-1]) * 60
        if raw.endswith("s"):
            return float(raw[:-1])
        return float(raw)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("duration must look like 30s, 60m or 1h") from exc


def percentile(values: list[float], ratio: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(ratio * len(ordered)) - 1)
    return round(ordered[index], 1)


async def password_token(
    client: httpx.AsyncClient,
    *,
    keycloak: str,
    realm: str,
    client_id: str,
    client_secret: str,
    username: str,
    password: str,
    attempts: int = 4,
) -> str:
    last_error: Exception | None = None
    for attempt in range(1, attempts + 1):
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
            if response.status_code != 200:
                raise OpsError(
                    f"Keycloak login failed for {username}: HTTP {response.status_code}"
                )
            payload = response.json()
            token = payload.get("access_token")
            if not isinstance(token, str) or not token:
                raise OpsError(f"Keycloak returned no access token for {username}")
            return token
        except (httpx.TimeoutException, httpx.TransportError, OpsError) as exc:
            last_error = exc
            if attempt >= attempts:
                break
            await asyncio.sleep(min(2**attempt, 8))
    raise OpsError(f"Keycloak login failed for {username} after {attempts} attempts: {last_error}")


class TokenCache:
    """Short-lived Keycloak access tokens, refreshed well before expiry."""

    def __init__(
        self,
        client: httpx.AsyncClient,
        *,
        keycloak: str,
        realm: str,
        client_id: str,
        client_secret: str,
        password: str,
        max_age_seconds: int = 240,
    ) -> None:
        self._client = client
        self._keycloak = keycloak
        self._realm = realm
        self._client_id = client_id
        self._client_secret = client_secret
        self._password = password
        self._max_age = max_age_seconds
        self._tokens: dict[str, tuple[str, float]] = {}
        self._lock = asyncio.Lock()

    async def get(self, username: str) -> str:
        cached = self._tokens.get(username)
        if cached and time.monotonic() - cached[1] < self._max_age:
            return cached[0]
        async with self._lock:
            cached = self._tokens.get(username)
            if cached and time.monotonic() - cached[1] < self._max_age:
                return cached[0]
            token = await password_token(
                self._client,
                keycloak=self._keycloak,
                realm=self._realm,
                client_id=self._client_id,
                client_secret=self._client_secret,
                username=username,
                password=self._password,
            )
            self._tokens[username] = (token, time.monotonic())
            return token


async def prometheus_value(client: httpx.AsyncClient, base: str, query: str) -> float | None:
    response = await client.get(f"{base}/api/v1/query", params={"query": query}, timeout=10.0)
    response.raise_for_status()
    payload = response.json()
    result = payload.get("data", {}).get("result", [])
    if not result:
        return None
    try:
        value = float(result[0]["value"][1])
    except (KeyError, IndexError, TypeError, ValueError):
        return None
    return None if math.isnan(value) or math.isinf(value) else value


async def real_traffic_slo(
    client: httpx.AsyncClient, base: str
) -> tuple[float | None, float | None]:
    p95 = await prometheus_value(
        client,
        base,
        (
            "histogram_quantile(0.95, sum by (le) (rate("
            '{__name__=~"http_server_duration.*_bucket", sahyog_traffic_class="real"}[2m])))'
        ),
    )
    errors = await prometheus_value(
        client,
        base,
        (
            '100 * sum(rate(http_server_errors_total{sahyog_traffic_class="real"}[2m]))'
            " / clamp_min(sum(rate("
            '{__name__=~"http_server_duration.*_count", sahyog_traffic_class="real"}[2m])), 0.001)'
        ),
    )
    return p95, errors


async def fetch_guard(
    client: httpx.AsyncClient,
    *,
    api: str,
    admin_token: str,
    subjects: set[str],
    window_minutes: int,
) -> dict[str, Any]:
    params: list[tuple[str, str | int | float | bool | None]] = [
        ("window_minutes", str(window_minutes))
    ]
    params.extend(("exclude_subjects", subject) for subject in sorted(subjects))
    response = await client.get(
        f"{api}/api/v1/analytics/load-guard",
        params=params,
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=20.0,
    )
    if response.status_code != 200:
        raise OpsError(f"load guard returned HTTP {response.status_code}")
    payload = response.json()
    if not isinstance(payload, dict):
        raise OpsError("load guard returned an unexpected payload")
    return payload


def decide_guard_abort(
    *,
    allow_real_users: bool,
    abort_on_real_slo: bool,
    prometheus_available: bool,
    real_events: int,
    synthetic_cost_delta_usd: float,
    budget_usd: float,
    real_p95_ms: float | None = None,
    real_error_pct: float | None = None,
    real_slo_p95_ms: int = 0,
    real_slo_error_pct: float = 0.0,
    slo_sample_available: bool = True,
) -> str | None:
    """Return an abort reason when a real-user / budget guard trips, else None.

    Pure decision helper so G-22 can unit-test the abort path without live load.
    """
    if not allow_real_users and real_events > 0:
        return "real_users_detected"
    if synthetic_cost_delta_usd > budget_usd:
        return "budget_guard"
    if allow_real_users and abort_on_real_slo and prometheus_available:
        if not slo_sample_available:
            return "real_slo_guard_unavailable"
        if real_p95_ms is not None and real_p95_ms > real_slo_p95_ms:
            return "real_user_p95"
        if real_error_pct is not None and real_error_pct > real_slo_error_pct:
            return "real_user_error"
    return None


async def guard_loop(
    client: httpx.AsyncClient,
    *,
    api: str,
    tokens: TokenCache,
    admin_username: str,
    subjects: set[str],
    state: GuardState,
    stop: asyncio.Event,
    interval: float,
    prometheus_url: str,
) -> None:
    while not stop.is_set():
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval)
            return
        except TimeoutError:
            pass
        try:
            admin_token = await tokens.get(admin_username)
            payload = await fetch_guard(
                client, api=api, admin_token=admin_token, subjects=subjects, window_minutes=15
            )
        except Exception as exc:  # noqa: BLE001 - guard failures are reported, then aborted
            state.samples.append({"at": datetime.now(UTC).isoformat(), "error": str(exc)})
            state.aborts.append("guard_unavailable")
            stop.set()
            return
        cost = float(payload.get("synthetic_cost_usd", 0.0))
        delta = max(0.0, cost - state.baseline_cost_usd)
        sample: dict[str, Any] = {
            "at": datetime.now(UTC).isoformat(),
            "real_events": payload.get("real_events", 0),
            "real_actors": payload.get("real_actors", 0),
            "synthetic_cost_usd": round(cost, 6),
            "synthetic_cost_delta_usd": round(delta, 6),
        }
        p95: float | None = None
        error_pct: float | None = None
        slo_ok = True
        if state.allow_real_users and state.abort_on_real_slo and state.prometheus_available:
            try:
                p95, error_pct = await real_traffic_slo(client, prometheus_url)
            except Exception as exc:  # noqa: BLE001 - losing the guard is fail-closed
                sample["guard_error"] = str(exc)
                slo_ok = False
            else:
                sample["real_p95_ms"] = p95
                sample["real_error_pct"] = error_pct
        decision_delta = delta
        if state.kill_drill and not state.kill_injected:
            # Injected, not measured: always labelled in the sample and the report.
            state.kill_injected = True
            decision_delta = state.budget_usd + 0.01
            sample["kill_drill_injected"] = True
            sample["injected_synthetic_cost_delta_usd"] = round(decision_delta, 6)
        reason = decide_guard_abort(
            allow_real_users=state.allow_real_users,
            abort_on_real_slo=state.abort_on_real_slo,
            prometheus_available=state.prometheus_available,
            real_events=int(payload.get("real_events", 0)),
            synthetic_cost_delta_usd=decision_delta,
            budget_usd=state.budget_usd,
            real_p95_ms=p95,
            real_error_pct=error_pct,
            real_slo_p95_ms=state.real_slo_p95_ms,
            real_slo_error_pct=state.real_slo_error_pct,
            slo_sample_available=slo_ok,
        )
        if reason is not None:
            sample["abort"] = reason
            state.aborts.append(reason)
            state.samples.append(sample)
            stop.set()
            return
        state.samples.append(sample)


def pick_endpoint(role: str, include_llm: bool) -> tuple[str, str, dict[str, Any] | None]:
    choices: list[tuple[str, str, dict[str, Any] | None]]
    if role == "front_desk":
        choices = [
            ("GET", "/api/v1/patients?page=1&page_size=10", None),
            ("GET", "/api/v1/doctors?page=1&page_size=10", None),
            ("GET", "/api/v1/appointments?page=1&page_size=10", None),
            ("GET", "/api/v1/notifications?page=1&page_size=10", None),
            ("GET", "/api/v1/meta", None),
            (
                "GET",
                "/api/v1/doctors/Dr.%20Ananya%20Rao/slots?clinic=BANER&days=3",
                None,
            ),
            # Analytics/FinOps (NFR-PERF-08) require admin/compliance — probed outside
            # the patient/front_desk cohort; see docs/evidence/test_report.md.
        ]
        return _RNG.choice(choices)
    choices = [
        ("GET", "/api/v1/chat/sessions?page=1&page_size=10", None),
        ("GET", "/api/v1/records/documents?page=1&page_size=10", None),
        ("GET", "/api/v1/records/medications", None),
        ("GET", "/api/v1/notifications?page=1&page_size=10", None),
        ("GET", "/api/v1/appointments?page=1&page_size=10", None),
        ("GET", "/api/v1/doctors?page=1&page_size=10", None),
        ("GET", "/api/v1/me/memory", None),
        ("GET", "/api/v1/meta", None),
        ("POST", "/api/v1/chat/sessions", {"title": "Synthetic load session"}),
    ]
    if include_llm:
        choices.append(
            (
                "POST",
                "/api/v1/chat/sessions/{session_id}/messages",
                {"content": "What appointments do I have?", "language": "en-IN"},
            )
        )
    return _RNG.choice(choices)


async def run_scenario(args: argparse.Namespace) -> dict[str, Any]:
    api = env_value("API_BASE_URL", "http://localhost:5706").rstrip("/")
    keycloak = env_value("KEYCLOAK_PUBLIC_URL", "http://localhost:5707").rstrip("/")
    realm = env_value("KEYCLOAK_REALM", "sahyog")
    client_id = env_value("KEYCLOAK_CLI_CLIENT_ID", "sahyog-cli")
    client_secret = env_value("KEYCLOAK_CLI_CLIENT_SECRET")
    password = env_value("SEED_DEMO_PASSWORD")
    if not client_secret or not password:
        raise OpsError("KEYCLOAK_CLI_CLIENT_SECRET and SEED_DEMO_PASSWORD are required")
    allow_env = env_value("LOAD_TEST_ALLOW_REAL_USERS", "false").lower() == "true"
    approval_ref = env_value("LOAD_TEST_APPROVAL_REF", "")
    if args.allow_real_users and not allow_env:
        raise OpsError(
            "real-user load testing requires LOAD_TEST_ALLOW_REAL_USERS=true and an approval"
        )
    if args.allow_real_users and not approval_ref:
        raise OpsError("LOAD_TEST_APPROVAL_REF is required when real users are allowed")
    if args.allow_real_users and not args.abort_on_real_slo:
        raise OpsError("--abort-on-real-slo is required when --allow-real-users is set")
    prometheus_url = (args.prometheus_url or env_value("PROMETHEUS_URL", "")).rstrip("/")
    if args.allow_real_users and args.abort_on_real_slo and not prometheus_url:
        raise OpsError(
            "the real-user SLO guard needs --prometheus-url (full profile) or PROMETHEUS_URL"
        )

    state = GuardState(
        allow_real_users=args.allow_real_users,
        abort_on_real_slo=args.abort_on_real_slo,
        real_slo_p95_ms=args.real_slo_p95_ms,
        real_slo_error_pct=args.real_slo_error_pct,
        budget_usd=args.budget_usd,
        kill_drill=kill_drill_enabled(),
    )
    started_at = datetime.now(UTC)
    samples: list[Sample] = []
    abort_event = asyncio.Event()

    async with httpx.AsyncClient(follow_redirects=False) as client:
        tokens = TokenCache(
            client,
            keycloak=keycloak,
            realm=realm,
            client_id=client_id,
            client_secret=client_secret,
            password=password,
        )
        admin_token = await tokens.get(args.admin_user)
        admin_me = await client.get(
            f"{api}/api/v1/auth/me",
            headers={"Authorization": f"Bearer {admin_token}"},
            timeout=20.0,
        )
        if admin_me.status_code != 200:
            raise OpsError(f"{args.admin_user} cannot read /auth/me: HTTP {admin_me.status_code}")
        admin_subject = str((admin_me.json() or {}).get("subject") or "")
        cohort: list[dict[str, Any]] = []
        roles = ["patient"]
        if not args.patients_only:
            roles.append("front_desk")
        usernames = {"patient": "patient", "front_desk": "frontdesk"}
        for role in roles:
            for index in range(1, args.cohort_size + 1):
                username = f"loadtest.{usernames[role]}{index:02d}"
                token = await tokens.get(username)
                me = await client.get(
                    f"{api}/api/v1/auth/me",
                    headers={"Authorization": f"Bearer {token}"},
                    timeout=20.0,
                )
                if me.status_code != 200:
                    raise OpsError(f"{username} cannot read /auth/me: HTTP {me.status_code}")
                profile = me.json()
                if profile.get("traffic_class") != "synthetic":
                    raise OpsError(f"{username} is not tagged synthetic; refusing to load")
                cohort.append(
                    {
                        "username": username,
                        "role": role,
                        "subject": str(profile.get("subject")),
                    }
                )
        subjects = {str(item["subject"]) for item in cohort}
        if not subjects:
            raise OpsError("no load-test identities were authenticated")
        # Exclude the load-guard operator so its own polls/smoke admin calls are not
        # counted as clinic "real user" traffic on an isolated lab host.
        if admin_subject:
            subjects.add(admin_subject)

        baseline = await fetch_guard(
            client, api=api, admin_token=admin_token, subjects=subjects, window_minutes=15
        )
        state.baseline_cost_usd = float(baseline.get("synthetic_cost_usd", 0.0))
        if not args.allow_real_users and int(baseline.get("real_events", 0)) > 0:
            raise OpsError(
                "real-user activity was detected in the guard window; rerun off-peak or use "
                "--allow-real-users with LOAD_TEST_ALLOW_REAL_USERS=true and an approval reference"
            )
        if args.allow_real_users and args.abort_on_real_slo:
            try:
                p95, errors = await real_traffic_slo(client, prometheus_url)
            except Exception as exc:  # noqa: BLE001
                raise OpsError(f"Prometheus real-user guard is not reachable: {exc}") from exc
            if p95 is None and errors is None:
                raise OpsError(
                    "Prometheus has no real-traffic series yet; the SLO guard cannot be proven"
                )
            state.prometheus_available = True

        if args.dry_run:
            return {
                "status": "dry_run",
                "host_profile": args.host_profile,
                "capacity_accepted": False,
                "cohort": len(cohort),
                "subjects": len(subjects),
                "allow_real_users": args.allow_real_users,
                "approval_ref_present": bool(approval_ref),
                "budget_usd": args.budget_usd,
                "prometheus_guard": state.prometheus_available,
                "kill_drill_requested": state.kill_drill,
                "real_activity": bool(baseline.get("real_events", 0)),
            }

        guard_task = asyncio.create_task(
            guard_loop(
                client,
                api=api,
                tokens=tokens,
                admin_username=args.admin_user,
                subjects=subjects,
                state=state,
                stop=abort_event,
                interval=args.guard_interval,
                prometheus_url=prometheus_url,
            )
        )
        semaphore = asyncio.Semaphore(args.concurrency)
        tasks: set[asyncio.Task[None]] = set()
        sessions: dict[str, str] = {}
        started = time.monotonic()
        end_at = started + args.duration
        burst_until = min(end_at, started + min(60.0, args.duration * 0.1))
        next_at = started
        issued = 0

        async def issue() -> None:
            nonlocal issued
            actor = _RNG.choice(cohort)
            method, path, body = pick_endpoint(str(actor["role"]), args.include_llm)
            if "{session_id}" in path:
                session_id = sessions.get(str(actor["username"]))
                if session_id is None:
                    return
                path = path.format(session_id=session_id)
            async with semaphore:
                if abort_event.is_set():
                    return
                issued += 1
                request_started = time.perf_counter()
                try:
                    token = await tokens.get(str(actor["username"]))
                    response = await client.request(
                        method,
                        f"{api}{path}",
                        headers={"Authorization": f"Bearer {token}"},
                        json=body,
                        timeout=60.0,
                    )
                    elapsed = round((time.perf_counter() - request_started) * 1000, 1)
                    samples.append(Sample(path.split("?")[0], response.status_code, elapsed))
                    if method == "POST" and path == "/api/v1/chat/sessions":
                        payload = response.json() if response.status_code == 201 else {}
                        session_id = payload.get("id") if isinstance(payload, dict) else None
                        if session_id:
                            sessions[str(actor["username"])] = str(session_id)
                except Exception:  # noqa: BLE001 - client errors count as failed samples
                    samples.append(
                        Sample(
                            path.split("?")[0],
                            0,
                            round((time.perf_counter() - request_started) * 1000, 1),
                        )
                    )

        try:
            while time.monotonic() < end_at and not abort_event.is_set():
                now = time.monotonic()
                if now < next_at:
                    await asyncio.sleep(min(next_at - now, 0.5))
                    continue
                rate = args.rate * (args.burst if now < burst_until else 1)
                interval = 3600.0 / max(rate, 0.001)
                next_at = now + interval * _RNG.uniform(0.85, 1.15)
                task = asyncio.create_task(issue())
                tasks.add(task)
                task.add_done_callback(tasks.discard)
            if tasks:
                await asyncio.gather(*tasks)
        finally:
            abort_event.set()
            await guard_task
            # Best-effort cleanup of sessions created by this run.
            for username, session_id in sessions.items():
                try:
                    token = await tokens.get(username)
                    await client.delete(
                        f"{api}/api/v1/chat/sessions/{session_id}",
                        headers={"Authorization": f"Bearer {token}"},
                        timeout=20.0,
                    )
                except Exception:  # noqa: BLE001, S112 - reset-test-data is the authoritative cleanup
                    continue

    elapsed = max(0.001, time.monotonic() - started)
    failed = [sample for sample in samples if sample.status not in VALID_STATUS]
    p95 = percentile([sample.elapsed_ms for sample in samples], 0.95)
    endpoint_counts = Counter(sample.endpoint for sample in samples)
    endpoint_latency: dict[str, dict[str, Any]] = {}
    by_endpoint: dict[str, list[Sample]] = {}
    for sample in samples:
        by_endpoint.setdefault(sample.endpoint, []).append(sample)
    for endpoint, group in sorted(by_endpoint.items()):
        times = [item.elapsed_ms for item in group]
        errs = sum(1 for item in group if item.status not in VALID_STATUS)
        nfr = ENDPOINT_NFR.get(endpoint, "unclassified")
        grid_target = 500.0 if nfr in {"NFR-PERF-05", "NFR-PERF-08"} else None
        endpoint_p95 = percentile(times, 0.95)
        endpoint_latency[endpoint] = {
            "nfr": nfr,
            "requests": len(group),
            "errors": errs,
            "error_rate_pct": round(100 * errs / len(group), 3) if group else 0.0,
            "p50_ms": percentile(times, 0.50),
            "p95_ms": endpoint_p95,
            "p99_ms": percentile(times, 0.99),
            "target_p95_ms": grid_target,
            "meets_target": (endpoint_p95 <= grid_target) if grid_target is not None else None,
        }
    # Aggregate grid-class endpoints against NFR-PERF-05 / NFR-PERF-08 (500 ms).
    grid_samples = [
        sample
        for sample in samples
        if ENDPOINT_NFR.get(sample.endpoint) in {"NFR-PERF-05", "NFR-PERF-08"}
    ]
    grid_p95 = percentile([sample.elapsed_ms for sample in grid_samples], 0.95) if grid_samples else None
    error_pct = round(100 * len(failed) / len(samples), 3) if samples else 0.0
    target = TARGET_P95_MS[args.profile]
    passed = not state.aborts and error_pct < 1.0 and p95 <= target and len(samples) > 0
    kill_drill: dict[str, Any] | None = None
    if state.kill_drill:
        observed = state.kill_injected and "budget_guard" in state.aborts
        kill_drill = {
            "enabled": True,
            "injected": state.kill_injected,
            "expected_abort": "budget_guard",
            "observed_abort": observed,
            "aborts": list(state.aborts),
            "requests_sent_before_stop": len(samples),
            "note": (
                "LOAD_TEST_KILL=1: the budget overrun was INJECTED into the first guard "
                "sample to exercise decide_guard_abort; it is a drill, not a measured "
                "breach, and the run cannot establish capacity."
            ),
        }
        passed = False  # a drill never counts as a capacity pass
    capacity_accepted = passed and args.host_profile in {"M", "L"}
    drill_ok = bool(kill_drill and kill_drill["observed_abort"])
    return {
        "status": ("kill_drill_passed" if drill_ok else "kill_drill_failed")
        if kill_drill
        else ("passed" if passed else "failed"),
        **({"kill_drill": kill_drill} if kill_drill else {}),
        "host_profile": args.host_profile,
        "capacity_accepted": capacity_accepted,
        "capacity_acceptance_note": (
            "Accepted only for a passing M/L host-profile run."
            if capacity_accepted
            else "P/S host profiles and non-passing runs cannot establish M/L capacity."
        ),
        "mode": "client_side_public_api",
        "auth": "keycloak_password_grant",
        "traffic_class": "synthetic",
        "cohort": {
            "identities": len(cohort),
            "subjects": len(subjects),
            "users": [item["username"] for item in cohort],
        },
        "profile": args.profile,
        "requested_rate_per_hour": args.rate,
        "burst": args.burst,
        "duration_seconds": round(args.duration, 1),
        "actual_requests_per_hour": round(len(samples) / elapsed * 3600, 1),
        "requests": len(samples),
        "issued": issued,
        "error_rate_pct": error_pct,
        "latency_ms": {
            "p50": percentile([sample.elapsed_ms for sample in samples], 0.50),
            "p95": p95,
            "p99": percentile([sample.elapsed_ms for sample in samples], 0.99),
        },
        "p95_target_ms": target,
        "endpoints": dict(sorted(endpoint_counts.items())),
        "endpoint_latency_ms": endpoint_latency,
        "nfr_slices": {
            "NFR-PERF-05_grid": {
                "description": "Form/list grid and catalogue GETs",
                "target_p95_ms": 500.0,
                "requests": len(grid_samples),
                "p95_ms": grid_p95,
                "meets_target": (grid_p95 <= 500.0) if grid_p95 is not None else None,
            },
            "NFR-SCALE-01_peak": {
                "description": "Peak API load (profile rate + burst)",
                "target_req_per_hour": PROFILE_RATES.get(args.profile, args.rate),
                "actual_req_per_hour": round(len(samples) / elapsed * 3600, 1),
                "error_rate_pct": error_pct,
                "error_rate_target_pct": 1.0,
                "overall_p95_ms": p95,
                "overall_p95_target_ms": target,
                "duration_seconds": round(args.duration, 1),
                "duration_note": (
                    "Spec expects a morning-window proof (prefer >= 60m). Short smokes are "
                    "plumbing only and cannot set capacity_accepted on P/S hosts."
                ),
            },
            "NFR-PERF-01_02_03_07_workflows": {
                "description": "Triage / record-ask / scribe-draft / TTFT",
                "measured_in_this_run": bool(args.include_llm),
                "note": (
                    "Requires --include-llm plus graph-specific probes; CRUD GETs do not "
                    "satisfy NFR-PERF-01/02/03/07. See docs/evidence/test_report.md."
                ),
            },
        },
        "guard": {
            "allow_real_users": args.allow_real_users,
            "approval_ref_present": bool(approval_ref),
            "abort_on_real_slo": args.abort_on_real_slo,
            "budget_usd": args.budget_usd,
            "baseline_synthetic_cost_usd": round(state.baseline_cost_usd, 6),
            "samples": state.samples,
            "aborts": state.aborts,
            "prometheus_available": state.prometheus_available,
        },
        "started_at": started_at.isoformat(),
        "finished_at": datetime.now(UTC).isoformat(),
        "notes": [
            "No dev-auth bypass, direct database seed or disabled audit/PII check was used.",
            "Only tagged loadtest.* identities and public API paths were used.",
            "Synthetic cost comes from analytics/load-guard (usage_records), not LiteLLM spend.",
            "Real-user p95/error requires the full profile Prometheus exporter.",
            "Per-endpoint latency and NFR slices are in endpoint_latency_ms / nfr_slices; "
            "full NFR matrix is docs/evidence/test_report.md.",
        ],
        "include_llm": bool(args.include_llm),
    }


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def render_markdown_report(report: dict[str, Any], json_path: Path) -> str:
    """Human-readable companion to the JSON evidence (G-17 / G-22).

    Mirrors the JSON; adds no numbers of its own and never upgrades a claim: capacity
    is only "accepted" when the JSON says so (passing run on an M/L host).
    """
    status = str(report.get("status"))
    host = report.get("host_profile")
    lat = report.get("latency_ms") or {}
    guard = report.get("guard") or {}
    drill = report.get("kill_drill")
    lines = [
        "# Load test report",
        "",
        f"_Generated by `scripts/load_test.py` at {datetime.now(UTC).isoformat()}; "
        f"machine-readable evidence: `{_rel(json_path)}`._",
        "",
        "## Verdict",
        "",
        f"- **Status:** `{status}`",
        f"- **Host profile:** `{host}`",
        f"- **Capacity accepted:** `{report.get('capacity_accepted')}` "
        f"- {report.get('capacity_acceptance_note', 'only a passing M/L run can set this')}",
        f"- **Profile:** `{report.get('profile')}` "
        f"({report.get('requested_rate_per_hour')} req/h requested, burst x{report.get('burst')}, "
        f"{report.get('duration_seconds')} s)",
        "",
        "## Results",
        "",
        "| Metric | Value | Target |",
        "|---|---|---|",
        f"| Requests completed | {report.get('requests')} | >0 |",
        f"| Actual req/h | {report.get('actual_requests_per_hour')} | "
        f"{report.get('requested_rate_per_hour')} |",
        f"| Error rate % | {report.get('error_rate_pct')} | < 1.0 |",
        f"| p50 ms | {lat.get('p50')} | - |",
        f"| p95 ms | {lat.get('p95')} | <= {report.get('p95_target_ms')} |",
        f"| p99 ms | {lat.get('p99')} | - |",
        "",
        "## Endpoints",
        "",
        "| Endpoint | Requests |",
        "|---|---|",
    ]
    endpoints = report.get("endpoints") or {}
    endpoint_latency = report.get("endpoint_latency_ms") or {}
    if endpoint_latency:
        lines += [
            "| Endpoint | NFR | n | p50 ms | p95 ms | Target p95 | Meet? |",
            "|---|---|---|---|---|---|---|",
        ]
        for name, stats in endpoint_latency.items():
            meet = stats.get("meets_target")
            meet_s = "—" if meet is None else ("yes" if meet else "no")
            target = stats.get("target_p95_ms")
            target_s = "—" if target is None else str(target)
            lines.append(
                f"| `{name}` | {stats.get('nfr')} | {stats.get('requests')} | "
                f"{stats.get('p50_ms')} | {stats.get('p95_ms')} | {target_s} | {meet_s} |"
            )
    else:
        lines += [f"| `{name}` | {count} |" for name, count in endpoints.items()] or [
            "| _none_ | 0 |"
        ]
    nfr_slices = report.get("nfr_slices") or {}
    if nfr_slices:
        lines += ["", "## NFR slices (this run)", ""]
        grid = nfr_slices.get("NFR-PERF-05_grid") or {}
        scale = nfr_slices.get("NFR-SCALE-01_peak") or {}
        workflows = nfr_slices.get("NFR-PERF-01_02_03_07_workflows") or {}
        lines += [
            f"- **NFR-PERF-05 grids:** n={grid.get('requests')}, "
            f"p95={grid.get('p95_ms')} ms (target ≤ {grid.get('target_p95_ms')} ms), "
            f"meets=`{grid.get('meets_target')}`",
            f"- **NFR-SCALE-01 peak:** actual={scale.get('actual_req_per_hour')} req/h "
            f"(requested {scale.get('target_req_per_hour')}), "
            f"error={scale.get('error_rate_pct')}% (target < {scale.get('error_rate_target_pct')}%), "
            f"overall p95={scale.get('overall_p95_ms')} ms "
            f"(gate ≤ {scale.get('overall_p95_target_ms')} ms); "
            f"{scale.get('duration_note')}",
            f"- **Workflow latencies (NFR-PERF-01/02/03/07):** "
            f"measured_in_this_run=`{workflows.get('measured_in_this_run')}` — "
            f"{workflows.get('note')}",
            "",
            "Authoritative NFR matrix (volume, service times, response times, gaps): "
            "[`docs/evidence/test_report.md`](./test_report.md).",
            "",
        ]
    lines += [
        "",
        "## Guard (G-22)",
        "",
        f"- Real users allowed: `{guard.get('allow_real_users')}` "
        f"(approval ref present: `{guard.get('approval_ref_present')}`)",
        f"- Abort on real-user SLO: `{guard.get('abort_on_real_slo')}`; "
        f"Prometheus guard available: `{guard.get('prometheus_available')}`",
        f"- Synthetic budget: {guard.get('budget_usd')} USD "
        f"(baseline {guard.get('baseline_synthetic_cost_usd')} USD)",
        f"- Guard samples: {len(guard.get('samples') or [])}",
        f"- Aborts: `{guard.get('aborts')}`",
        "",
    ]
    if drill:
        lines += [
            "### Kill drill (`LOAD_TEST_KILL=1`)",
            "",
            f"- Injected: `{drill.get('injected')}`; "
            f"expected abort `{drill.get('expected_abort')}`; "
            f"observed: `{drill.get('observed_abort')}`",
            f"- Requests sent before stop: {drill.get('requests_sent_before_stop')}",
            f"- {drill.get('note')}",
            "",
        ]
    else:
        lines += [
            "### Exercising the abort path (G-22)",
            "",
            "No kill drill in this run, so `aborts` is empty by construction, not by test. "
            "To exercise `decide_guard_abort` end to end against a running stack, run in an "
            "approved window:",
            "",
            "```bash",
            "LOAD_TEST_KILL=1 scripts/load-test.sh --profile r1 --host-profile P \\",
            "  --duration 120s --cohort-size 2 --rate 60",
            "```",
            "",
            "The first guard sample is given an injected over-budget cost; the run must stop "
            "with `aborts=['budget_guard']` and status `kill_drill_passed`. The drill is "
            "labelled in JSON and here and never counts as capacity evidence. Pure-logic "
            "coverage lives in `apps/api/tests/test_load_abort_guard.py`; see "
            "`docs/runbooks/load-abort.md`.",
            "",
        ]
    lines += ["## Caveats", ""]
    lines += [f"- {note}" for note in report.get("notes") or []]
    if host in {"P", "S"}:
        lines.append(
            f"- Host profile `{host}` is below the M/L target; this run cannot establish "
            "M/L capacity (G-17 remains open until an M/L run is committed)."
        )
    if status == "dry_run":
        lines.append("- Dry run: authenticated and preflighted only; no traffic was sent.")
    lines.append(f"- Release: `{report.get('release')}`; started `{report.get('started_at')}`.")
    return "\n".join(lines) + "\n"


def render_from_json(source: Path, destination: Path) -> int:
    """Re-render the markdown report from an existing JSON evidence file (no load run)."""
    try:
        report = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        print(f"error: cannot read {source}: {exc}", file=sys.stderr)
        return 2
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(render_markdown_report(report, source), encoding="utf-8")
    print(f"wrote {destination}")
    return 0


def main() -> int:
    pre = argparse.ArgumentParser(add_help=False)
    pre.add_argument("--render-from", default="")
    pre.add_argument("--report-md", default="")
    known, _ = pre.parse_known_args()
    if known.render_from:
        return render_from_json(
            Path(known.render_from),
            Path(known.report_md) if known.report_md else DEFAULT_REPORT_MD,
        )
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=sorted(PROFILE_RATES), default="r1")
    parser.add_argument(
        "--host-profile",
        choices=["P", "S", "M", "L"],
        required=True,
        help="host size under test; P/S runs cannot set capacity_accepted=true",
    )
    parser.add_argument("--rate", type=int, help="requests per hour (defaults per profile)")
    parser.add_argument("--burst", type=int, help="burst multiplier (default 4 for r3/ml, else 1)")
    parser.add_argument(
        "--duration",
        type=parse_duration,
        default=None,
        help="test duration; ml hints 300s, other profiles default to 60m",
    )
    parser.add_argument("--cohort-size", type=int, default=20)
    parser.add_argument("--concurrency", type=int, default=32)
    parser.add_argument("--include-llm", action="store_true", help="also send chat messages")
    parser.add_argument("--patients-only", action="store_true")
    parser.add_argument("--allow-real-users", action="store_true")
    parser.add_argument("--abort-on-real-slo", action="store_true")
    parser.add_argument("--real-slo-p95-ms", type=int, default=1500)
    parser.add_argument("--real-slo-error-pct", type=float, default=1.0)
    parser.add_argument("--budget-usd", type=float, default=5.0)
    parser.add_argument("--guard-interval", type=float, default=15.0)
    parser.add_argument("--prometheus-url", default="")
    parser.add_argument("--admin-user", default="admin.ops")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--summary", default="")
    parser.add_argument(
        "--report-md",
        default="",
        help="Markdown report path (default docs/evidence/load_test_report.md; not written for "
        "--dry-run unless given explicitly)",
    )
    parser.add_argument(
        "--render-from",
        default="",
        help="only re-render the markdown report from an existing JSON evidence file",
    )
    parser.add_argument("--no-report-md", action="store_true", help="skip the markdown report")
    args = parser.parse_args()
    if args.rate is None:
        args.rate = PROFILE_RATES[args.profile]
    if args.burst is None:
        args.burst = 4 if args.profile in {"r3", "ml"} else 1
    if args.duration is None:
        args.duration = parse_duration("300s" if args.profile == "ml" else "60m")
    if args.burst < 1:
        parser.error("--burst must be at least 1")
    if args.rate < 1:
        parser.error("--rate must be at least 1 request per hour")
    if not 1 <= args.cohort_size <= 20:
        parser.error("--cohort-size must be between 1 and 20")

    try:
        report = asyncio.run(run_scenario(args))
    except OpsError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    report["tool"] = "scripts/load_test.py"
    report["release"] = env_value("APP_VERSION", "0.1.0")
    stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    output = (
        Path(args.summary)
        if args.summary
        else ROOT / "docs" / "evidence" / f"load_test_{args.profile}_{stamp}.json"
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    md_path: Path | None = None
    if not args.no_report_md and (args.report_md or report["status"] != "dry_run"):
        # Dry runs must not overwrite the last real load report with a no-traffic stub.
        md_path = Path(args.report_md) if args.report_md else DEFAULT_REPORT_MD
        md_path.parent.mkdir(parents=True, exist_ok=True)
        md_path.write_text(render_markdown_report(report, output), encoding="utf-8")
    if report["status"] == "dry_run":
        summary = {
            "status": report["status"],
            "host_profile": report["host_profile"],
            "capacity_accepted": report["capacity_accepted"],
            "cohort": report["cohort"],
            "subjects": report["subjects"],
            "real_activity": report["real_activity"],
            "prometheus_guard": report["prometheus_guard"],
            "report": str(output),
        }
    else:
        summary = {
            "status": report["status"],
            "host_profile": report["host_profile"],
            "capacity_accepted": report["capacity_accepted"],
            "requests": report["requests"],
            "actual_requests_per_hour": report["actual_requests_per_hour"],
            "error_rate_pct": report["error_rate_pct"],
            "p95_ms": report["latency_ms"]["p95"],
            "p95_target_ms": report["p95_target_ms"],
            "aborts": report["guard"]["aborts"],
            "report": str(output),
        }
    if md_path is not None:
        summary["report_md"] = str(md_path)
    print(json.dumps(summary, indent=2, sort_keys=True))
    return 0 if report["status"] in {"passed", "dry_run", "kill_drill_passed"} else 1


if __name__ == "__main__":
    raise SystemExit(main())
