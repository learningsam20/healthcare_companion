"""G-22: prove load-test abort path trips without live load."""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[3]
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

from load_test import (  # noqa: E402
    GuardState,
    decide_guard_abort,
    guard_loop,
    kill_drill_enabled,
    render_markdown_report,
)


def test_decide_aborts_when_real_users_appear_without_approval() -> None:
    reason = decide_guard_abort(
        allow_real_users=False,
        abort_on_real_slo=False,
        prometheus_available=False,
        real_events=3,
        synthetic_cost_delta_usd=0.0,
        budget_usd=5.0,
    )
    assert reason == "real_users_detected"


def test_decide_aborts_on_budget_guard() -> None:
    reason = decide_guard_abort(
        allow_real_users=True,
        abort_on_real_slo=True,
        prometheus_available=True,
        real_events=0,
        synthetic_cost_delta_usd=2.5,
        budget_usd=1.0,
    )
    assert reason == "budget_guard"


def test_decide_aborts_on_real_user_p95() -> None:
    reason = decide_guard_abort(
        allow_real_users=True,
        abort_on_real_slo=True,
        prometheus_available=True,
        real_events=10,
        synthetic_cost_delta_usd=0.1,
        budget_usd=5.0,
        real_p95_ms=2500.0,
        real_error_pct=0.1,
        real_slo_p95_ms=1500,
        real_slo_error_pct=1.0,
    )
    assert reason == "real_user_p95"


def test_decide_aborts_on_real_user_error() -> None:
    reason = decide_guard_abort(
        allow_real_users=True,
        abort_on_real_slo=True,
        prometheus_available=True,
        real_events=10,
        synthetic_cost_delta_usd=0.1,
        budget_usd=5.0,
        real_p95_ms=200.0,
        real_error_pct=5.0,
        real_slo_p95_ms=1500,
        real_slo_error_pct=1.0,
    )
    assert reason == "real_user_error"


def test_decide_aborts_when_slo_sample_unavailable() -> None:
    reason = decide_guard_abort(
        allow_real_users=True,
        abort_on_real_slo=True,
        prometheus_available=True,
        real_events=1,
        synthetic_cost_delta_usd=0.0,
        budget_usd=5.0,
        slo_sample_available=False,
    )
    assert reason == "real_slo_guard_unavailable"


def test_decide_allows_clean_sample() -> None:
    reason = decide_guard_abort(
        allow_real_users=True,
        abort_on_real_slo=True,
        prometheus_available=True,
        real_events=2,
        synthetic_cost_delta_usd=0.2,
        budget_usd=5.0,
        real_p95_ms=400.0,
        real_error_pct=0.2,
        real_slo_p95_ms=1500,
        real_slo_error_pct=1.0,
    )
    assert reason is None


@pytest.mark.asyncio
async def test_guard_loop_trips_budget_abort_without_live_load(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Integration-shaped: one guard poll with mocked HTTP trips budget_guard and stops."""

    async def fake_fetch_guard(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {
            "real_events": 0,
            "real_actors": 0,
            "synthetic_cost_usd": 3.0,
        }

    monkeypatch.setattr("load_test.fetch_guard", fake_fetch_guard)

    class _Tokens:
        async def get(self, _username: str) -> str:
            return "token"

    state = GuardState(
        allow_real_users=True,
        abort_on_real_slo=True,
        real_slo_p95_ms=1500,
        real_slo_error_pct=1.0,
        budget_usd=1.0,
        baseline_cost_usd=0.0,
        prometheus_available=False,
    )
    stop = asyncio.Event()
    client = SimpleNamespace()  # unused once fetch_guard is mocked
    await guard_loop(
        client,  # type: ignore[arg-type]
        api="http://example.test",
        tokens=_Tokens(),  # type: ignore[arg-type]
        admin_username="admin",
        subjects={"loadtest.patient01"},
        state=state,
        stop=stop,
        interval=0.01,
        prometheus_url="",
    )
    assert state.aborts == ["budget_guard"]
    assert stop.is_set()
    assert state.samples[-1]["abort"] == "budget_guard"


@pytest.mark.asyncio
async def test_kill_drill_injects_budget_abort_on_clean_guard(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """LOAD_TEST_KILL=1 path: zero measured cost still trips budget_guard, labelled injected."""

    async def fake_fetch_guard(*_args: Any, **_kwargs: Any) -> dict[str, Any]:
        return {"real_events": 0, "real_actors": 0, "synthetic_cost_usd": 0.0}

    monkeypatch.setattr("load_test.fetch_guard", fake_fetch_guard)

    class _Tokens:
        async def get(self, _username: str) -> str:
            return "token"

    state = GuardState(
        allow_real_users=False,
        abort_on_real_slo=False,
        real_slo_p95_ms=1500,
        real_slo_error_pct=1.0,
        budget_usd=5.0,
        kill_drill=True,
    )
    stop = asyncio.Event()
    await guard_loop(
        SimpleNamespace(),  # type: ignore[arg-type]
        api="http://example.test",
        tokens=_Tokens(),  # type: ignore[arg-type]
        admin_username="admin",
        subjects={"loadtest.patient01"},
        state=state,
        stop=stop,
        interval=0.01,
        prometheus_url="",
    )
    assert state.aborts == ["budget_guard"]
    assert stop.is_set()
    sample = state.samples[-1]
    assert sample["kill_drill_injected"] is True
    assert sample["synthetic_cost_delta_usd"] == 0.0  # measured value is not rewritten


def test_kill_drill_env_flag(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("LOAD_TEST_KILL", "1")
    assert kill_drill_enabled() is True
    monkeypatch.setenv("LOAD_TEST_KILL", "0")
    assert kill_drill_enabled() is False


def test_markdown_report_does_not_upgrade_capacity_claim(tmp_path: Path) -> None:
    report = {
        "status": "passed",
        "host_profile": "P",
        "capacity_accepted": False,
        "profile": "r1",
        "requests": 9,
        "latency_ms": {"p50": 10, "p95": 32, "p99": 40},
        "p95_target_ms": 1500,
        "guard": {"aborts": [], "samples": []},
        "endpoints": {"/api/v1/meta": 9},
        "notes": ["n1"],
    }
    md = render_markdown_report(report, tmp_path / "x.json")
    assert "**Capacity accepted:** `False`" in md
    assert "cannot establish" in md
    assert "LOAD_TEST_KILL=1" in md  # drill instructions when no drill ran
    drill = {
        **report,
        "status": "kill_drill_passed",
        "kill_drill": {
            "injected": True,
            "expected_abort": "budget_guard",
            "observed_abort": True,
            "note": "INJECTED",
        },
    }
    assert "Kill drill" in render_markdown_report(drill, tmp_path / "x.json")
