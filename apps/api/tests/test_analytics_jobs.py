from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace
from typing import Any

from app.modules.analytics.jobs import _deterministic_candidates, insight_out
from app.modules.analytics.reconciliation import (
    _async_url,
    _naive,
    _status,
    reconciliation_out,
)
from app.repositories.models import Insight


def test_unconfigured_reconciliation_is_unavailable() -> None:
    payload = reconciliation_out(None)
    assert payload.status == "unavailable"
    assert "No reconciliation" in payload.note


def test_litellm_url_is_rewritten_for_asyncpg() -> None:
    url = _async_url("postgresql://user:secret@postgres:5432/litellm")
    assert url.startswith("postgresql+asyncpg://")
    assert url.endswith("/litellm")
    assert ":secret@" in url
    assert "***" not in url


def test_naive_timestamp_is_utc() -> None:
    value = dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.timezone(dt.timedelta(hours=5, minutes=30)))
    assert _naive(value) == dt.datetime(2026, 10, 25, 6, 30)


def test_status_never_calls_a_total_mismatch_matched() -> None:
    assert (
        _status(
            configured=True,
            app_calls=7,
            gateway_calls=20,
            matched_calls=0,
            unmatched_app_calls=7,
            unmatched_gateway_calls=20,
            variance_pct=0.0,
            tolerance=2.0,
        )
        == "variance"
    )
    assert (
        _status(
            configured=True,
            app_calls=10,
            gateway_calls=10,
            matched_calls=10,
            unmatched_app_calls=0,
            unmatched_gateway_calls=0,
            variance_pct=0.1,
            tolerance=2.0,
        )
        == "matched"
    )
    assert (
        _status(
            configured=True,
            app_calls=10,
            gateway_calls=10,
            matched_calls=10,
            unmatched_app_calls=0,
            unmatched_gateway_calls=0,
            variance_pct=2.1,
            tolerance=2.0,
        )
        == "variance"
    )
    assert (
        _status(
            configured=False,
            app_calls=10,
            gateway_calls=10,
            matched_calls=10,
            unmatched_app_calls=0,
            unmatched_gateway_calls=0,
            variance_pct=0.0,
            tolerance=2.0,
        )
        == "insufficient_data"
    )
    assert (
        _status(
            configured=True,
            app_calls=0,
            gateway_calls=0,
            matched_calls=0,
            unmatched_app_calls=0,
            unmatched_gateway_calls=0,
            variance_pct=0.0,
            tolerance=2.0,
        )
        == "insufficient_data"
    )
    assert (
        _status(
            configured=True,
            app_calls=15,
            gateway_calls=28,
            matched_calls=8,
            unmatched_app_calls=7,
            unmatched_gateway_calls=20,
            variance_pct=0.0,
            tolerance=2.0,
        )
        == "partial"
    )


def _candidates() -> list[dict[str, Any]]:
    services = SimpleNamespace(
        finops_model={
            "profiles": {"P": {"inputs": {"external_llm_share": 0.1}}},
            "what_if_defaults": {"profile": "P"},
        }
    )
    return _deterministic_candidates(
        services,  # type: ignore[arg-type]
        counts={"chat_sessions": 0},
        actions={},
        consents={"expired": 2},
        usage={"calls": 0},
        latest_eval=None,
        latest_reconciliation=None,
        window_end=dt.datetime(2026, 10, 25, 12, 0, tzinfo=dt.UTC),
    )


def test_candidates_have_daily_dedupe_and_evidence() -> None:
    items = _candidates()
    by_key = {item["dedupe_key"]: item for item in items}
    assert "no-observed-usage:2026-10-25" in by_key
    assert "cost-baseline-missing:2026-10-25" in by_key
    assert "consent-expiry-review:2026-10-25" in by_key
    assert "evaluation-baseline-missing:2026-10-25" in by_key
    assert "local-routing:2026-10-25" in by_key
    for item in items:
        assert item["evidence"]
        assert item["owner"]
        assert item["confidence"] in {"low", "medium", "high"}


def test_insight_output_keeps_ai_flag_explicit() -> None:
    insight = Insight(
        id=uuid.uuid4(),
        dedupe_key="local-routing:2026-10-25",
        area="finops",
        title="Keep record-bearing prompts local",
        recommendation="Use local aliases for identified text.",
        impact="Lower egress",
        confidence="high",
        effort="low",
        owner="platform",
        evidence=["config/models.yaml egress classes"],
        generator="deterministic_rules",
        model_alias=None,
        ai_generated=False,
        status="proposed",
        window_start=dt.datetime(2026, 10, 1, tzinfo=dt.UTC),
        window_end=dt.datetime(2026, 10, 25, tzinfo=dt.UTC),
    )
    payload = insight_out(insight)
    assert payload["ai_generated"] is False
    assert payload["generator"] == "deterministic_rules"
    assert payload["evidence"] == ["config/models.yaml egress classes"]
