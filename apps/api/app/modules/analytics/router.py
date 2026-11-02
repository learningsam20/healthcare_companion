from __future__ import annotations

import csv
import datetime as dt
import io
import uuid
from typing import Annotated, Any

from app.core.db import get_session
from app.core.security import AuthContext, Role, require_roles
from app.core.services import Services, get_services
from app.modules.analytics.finops import calculate_what_if
from app.modules.analytics.jobs import decide_insight, insight_out
from app.modules.analytics.reconciliation import reconcile_spend, reconciliation_out
from app.modules.analytics.schemas import (
    FinopsBudgetUpsert,
    FinopsSavingCreate,
    InsightDecisionRequest,
    ReconcileRequest,
    ReconciliationOut,
    WhatIfRequest,
    WhatIfResponse,
)
from app.modules.handoffs.service import mtta_summary
from app.repositories.analytics import AnalyticsRepository
from app.repositories.audit import AuditRepository
from app.repositories.models import (
    AnalyticsSnapshot,
    AuditEvent,
    EvalMetricResult,
    EvalRun,
    FinopsBudget,
    FinopsSaving,
    Insight,
    SafetyIncident,
    SpendReconciliation,
)
from app.repositories.usage import UsageRepository
from fastapi import APIRouter, Depends, Query, Request, Response
from sahyog_common.errors import ProblemError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/analytics", tags=["analytics"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[Services, Depends(get_services)]
AdminOrCompliance = Annotated[AuthContext, Depends(require_roles(Role.ADMIN, Role.COMPLIANCE))]
AdminOnly = Annotated[AuthContext, Depends(require_roles(Role.ADMIN))]


def _definitions(services: Services) -> dict[str, dict[str, Any]]:
    return {item["id"]: item for item in services.metrics.get("metrics", [])}


def _tile(
    definitions: dict[str, dict[str, Any]],
    metric_id: str,
    *,
    value: float | int | None,
    unit: str,
    status: str = "ok",
    suppressed: bool = False,
    note: str | None = None,
    as_of: dt.datetime | None = None,
) -> dict[str, Any]:
    definition = definitions.get(metric_id)
    if definition is None:
        raise ProblemError(
            500,
            "metric_undefined",
            "Metric not defined",
            f"Metric {metric_id} has no registry entry and must not be displayed.",
        )
    tile = {
        "id": metric_id,
        "version": definition["version"],
        "label": definition["label"],
        "description": definition["description"],
        "source": definition["source"],
        "formula": definition["formula"],
        "dimensions": definition["dimensions"],
        "freshness_hours": definition["freshness_hours"],
        "unit": unit,
        "value": None if suppressed else value,
        "status": status,
        "suppressed": suppressed,
        "as_of": (as_of or dt.datetime.now(dt.UTC)).isoformat(),
    }
    if note:
        tile["note"] = note
    return tile


def _suppress(
    value: float | int, minimum: int, suppression: str = "small_cell"
) -> tuple[float | int, bool]:
    if suppression != "small_cell":
        return value, False
    if isinstance(value, int) and 0 < value < minimum:
        return value, True
    return value, False


def _period(days: int) -> tuple[dt.datetime, dt.datetime]:
    end = dt.datetime.now(dt.UTC)
    return end - dt.timedelta(days=days), end


def _month_period(period: str) -> tuple[dt.datetime, dt.datetime]:
    try:
        year, month = (int(item) for item in period.split("-", 1))
        start = dt.datetime(year, month, 1, tzinfo=dt.UTC)
    except (TypeError, ValueError) as exc:
        raise ProblemError(422, "period_invalid", "Invalid period", "Use YYYY-MM.") from exc
    end = (
        dt.datetime(year + 1, 1, 1, tzinfo=dt.UTC)
        if month == 12
        else dt.datetime(year, month + 1, 1, tzinfo=dt.UTC)
    )
    return start, end


def _age_hours(value: dt.datetime | None) -> float | None:
    if value is None:
        return None
    return round((dt.datetime.now(dt.UTC) - value).total_seconds() / 3600, 2)


async def _latest_snapshot(session: AsyncSession) -> AnalyticsSnapshot | None:
    return await session.scalar(
        select(AnalyticsSnapshot).order_by(AnalyticsSnapshot.captured_at.desc()).limit(1)
    )


async def _latest_reconciliation(session: AsyncSession) -> SpendReconciliation | None:
    return await session.scalar(
        select(SpendReconciliation).order_by(SpendReconciliation.created_at.desc()).limit(1)
    )


def _require_analytics(services: Services) -> None:
    if not services.features.enabled("analytics_dashboard"):
        raise ProblemError(
            403,
            "feature_disabled",
            "Analytics unavailable",
            "Analytics is disabled by configuration.",
        )


@router.get("/overview")
async def overview(
    context: AdminOrCompliance,
    services: ServicesDep,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    _require_analytics(services)
    definitions = _definitions(services)
    minimum = int(services.app_config.get("analytics", {}).get("small_cell_minimum", 5))
    start, end = _period(days)
    repo = AnalyticsRepository(session)
    counts = await repo.overview_counts(start=start, end=end)
    actions = await repo.audit_action_counts(start=start, end=end)
    roles = await repo.role_activity(start=start, end=end)

    tiles = []
    for metric_id, value, unit in (
        ("active_users_30d", counts["active_users"], "users"),
        ("chat_sessions_created", counts["chat_sessions"], "sessions"),
        ("chat_messages", counts["chat_messages"], "messages"),
        ("bookings_confirmed", counts["bookings_confirmed"], "bookings"),
        ("red_flag_triggers", actions.get("safety.red_flag_triggered", 0), "events"),
    ):
        safe_value, suppressed = _suppress(value, minimum)
        tiles.append(
            _tile(
                definitions,
                metric_id,
                value=safe_value,
                unit=unit,
                suppressed=suppressed,
                status="ok",
                as_of=end,
            )
        )

    from app.repositories.models import Appointment, ScribeRun

    no_show_high = int(
        await session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.no_show_band == "high",
                Appointment.created_at >= start,
                Appointment.created_at < end,
                Appointment.traffic_class == "real",
            )
        )
        or 0
    )
    no_show_obs = int(
        await session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.status == "no_show",
                Appointment.created_at >= start,
                Appointment.created_at < end,
                Appointment.traffic_class == "real",
            )
        )
        or 0
    )
    waitlist_n = int(
        await session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.waitlist_suggested.is_(True),
                Appointment.created_at >= start,
                Appointment.created_at < end,
                Appointment.traffic_class == "real",
            )
        )
        or 0
    )
    for metric_id, value, unit in (
        ("no_show_predicted_high", no_show_high, "bookings"),
        ("no_show_observed", no_show_obs, "bookings"),
        ("waitlist_suggestions", waitlist_n, "bookings"),
        ("citation_failures", actions.get("safety.citation_failed", 0), "events"),
    ):
        safe_value, suppressed = _suppress(value, minimum)
        tiles.append(
            _tile(
                definitions,
                metric_id,
                value=safe_value,
                unit=unit,
                suppressed=suppressed,
                status="ok",
                as_of=end,
            )
        )

    from sqlalchemy import Float, cast

    edit_mean = await session.scalar(
        select(func.avg(cast(ScribeRun.edit_distance["total"].astext, Float))).where(
            ScribeRun.edit_distance.is_not(None),
            ScribeRun.completed_at.is_not(None),
            ScribeRun.completed_at >= start,
            ScribeRun.completed_at < end,
        )
    )
    review_p50 = await session.scalar(
        select(func.percentile_cont(0.5).within_group(ScribeRun.review_seconds)).where(
            ScribeRun.review_seconds.is_not(None),
            ScribeRun.completed_at.is_not(None),
            ScribeRun.completed_at >= start,
            ScribeRun.completed_at < end,
        )
    )
    tiles.append(
        _tile(
            definitions,
            "scribe_edit_distance_mean",
            value=round(float(edit_mean), 1) if edit_mean is not None else None,
            unit="edits",
            status="ok" if edit_mean is not None else "no_runs",
            note=None if edit_mean is not None else "No signed scribe runs with edit distance yet.",
            as_of=end,
        )
    )
    tiles.append(
        _tile(
            definitions,
            "scribe_review_seconds_p50",
            value=round(float(review_p50), 1) if review_p50 is not None else None,
            unit="seconds",
            status="ok" if review_p50 is not None else "no_runs",
            note=None if review_p50 is not None else "No signed scribe runs with review time yet.",
            as_of=end,
        )
    )

    # Ops MTTA + FinOps key metrics on the same overview grid (G-25 / FinOps).
    mtta = await mtta_summary(session, window_hours=days * 24)
    mtta_status = (
        "ok"
        if mtta["acknowledged_count"] and mtta["target_met"]
        else ("watch" if mtta["acknowledged_count"] else "no_runs")
    )
    tiles.append(
        _tile(
            definitions,
            "handoff_mtta_p50_seconds",
            value=mtta["p50_seconds"],
            unit="seconds",
            status=mtta_status,
            note=(
                None
                if mtta["acknowledged_count"]
                else "No acknowledged handoffs in this window — assign on Escalations to record MTTA."
            ),
            as_of=end,
        )
    )
    within_pct = (
        round(float(mtta["within_sla_ratio"]) * 100, 1)
        if mtta["within_sla_ratio"] is not None
        else None
    )
    tiles.append(
        _tile(
            definitions,
            "handoff_mtta_within_sla_pct",
            value=within_pct,
            unit="percent",
            status=mtta_status,
            note=(
                f"n={mtta['acknowledged_count']} · emergency SLA {mtta['sla_seconds_emergency']}s"
                if mtta["acknowledged_count"]
                else "Awaiting first assign acknowledgements."
            ),
            as_of=end,
        )
    )
    usage = await UsageRepository(session).summary(start=start, end=end)
    monthly_run_rate = (
        round(float(usage["cost_usd"]) / days * 30, 4) if usage["calls"] else 0.0
    )
    finops_status = "ok" if usage["calls"] else "no_usage"
    tiles.append(
        _tile(
            definitions,
            "finops_observed_cost_usd",
            value=round(float(usage["cost_usd"]), 4),
            unit="usd",
            status=finops_status,
            note=None if usage["calls"] else "No usage_records in this window.",
            as_of=end,
        )
    )
    tiles.append(
        _tile(
            definitions,
            "finops_monthly_run_rate_usd",
            value=monthly_run_rate,
            unit="usd",
            status=finops_status,
            as_of=end,
        )
    )

    snapshot = await _latest_snapshot(session)
    snapshot_age = _age_hours(snapshot.captured_at) if snapshot else None
    return {
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "as_of": end.isoformat(),
        "small_cell_minimum": minimum,
        "tiles": tiles,
        "active_users_by_role": roles,
        "traffic_class": "real",
        "snapshot": (
            {
                "id": str(snapshot.id),
                "captured_at": snapshot.captured_at.isoformat(),
                "age_hours": snapshot_age,
                "metric_version": snapshot.metric_version,
                "stale": snapshot_age is None or snapshot_age > 26,
            }
            if snapshot
            else None
        ),
    }


@router.get("/quality")
async def quality(
    context: AdminOrCompliance,
    services: ServicesDep,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    _require_analytics(services)
    definitions = _definitions(services)
    minimum = int(services.app_config.get("analytics", {}).get("small_cell_minimum", 5))
    start, end = _period(days)
    actions = await AnalyticsRepository(session).audit_action_counts(start=start, end=end)
    open_incidents = int(
        await session.scalar(
            select(func.count())
            .select_from(SafetyIncident)
            .where(SafetyIncident.status != "closed")
        )
        or 0
    )
    tiles = []
    red_flag_value, red_flag_suppressed = _suppress(
        actions.get("safety.red_flag_triggered", 0), minimum
    )
    tiles.append(
        _tile(
            definitions,
            "red_flag_triggers",
            value=red_flag_value,
            unit="events",
            suppressed=red_flag_suppressed,
            as_of=end,
        )
    )
    egress_value, egress_suppressed = _suppress(actions.get("chat.reply_blocked", 0), minimum)
    tiles.append(
        _tile(
            definitions,
            "egress_blocks",
            value=egress_value,
            unit="events",
            suppressed=egress_suppressed,
            as_of=end,
        )
    )
    mtta = await mtta_summary(session, window_hours=days * 24)
    mtta_status = (
        "ok"
        if mtta["acknowledged_count"] and mtta["target_met"]
        else ("watch" if mtta["acknowledged_count"] else "no_runs")
    )
    tiles.append(
        _tile(
            definitions,
            "handoff_mtta_p50_seconds",
            value=mtta["p50_seconds"],
            unit="seconds",
            status=mtta_status,
            note=(
                f"mean={mtta['mean_seconds']}s · p95={mtta['p95_seconds']}s · n={mtta['acknowledged_count']}"
                if mtta["acknowledged_count"]
                else "No acknowledgements yet — MTTA starts when staff assign on Escalations."
            ),
            as_of=end,
        )
    )
    tiles.append(
        _tile(
            definitions,
            "handoff_mtta_within_sla_pct",
            value=(
                round(float(mtta["within_sla_ratio"]) * 100, 1)
                if mtta["within_sla_ratio"] is not None
                else None
            ),
            unit="percent",
            status=mtta_status,
            as_of=end,
        )
    )
    tiles.extend(
        [
            {
                "id": "gateway_failures",
                "label": "Model gateway failures",
                "value": actions.get("chat.reply_failed", 0),
                "unit": "events",
                "status": "ok",
                "suppressed": False,
                "source": "audit_events",
                "formula": "count(action = 'chat.reply_failed')",
                "as_of": end.isoformat(),
            },
            {
                "id": "open_incidents",
                "label": "Open safety incidents",
                "value": open_incidents,
                "unit": "incidents",
                "status": "ok",
                "suppressed": False,
                "source": "safety_incidents",
                "formula": "count(status != 'closed')",
                "as_of": end.isoformat(),
            },
            {
                "id": "review_sla",
                "label": "Review queue SLA",
                "value": None,
                "unit": "percent",
                "status": "not_configured",
                "suppressed": False,
                "source": "review_queue_item",
                "formula": "within SLA / resolved",
                "note": "The review queue is not part of the current build.",
                "as_of": end.isoformat(),
            },
        ]
    )
    return {
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "tiles": tiles,
        "zero_tolerance_note": (
            "Zero-tolerance measures are shown as counts, never averaged into a score."
        ),
    }


@router.get("/compliance")
async def compliance(
    context: AdminOrCompliance,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_analytics(services)
    definitions = _definitions(services)
    repo = AnalyticsRepository(session)
    consents = await repo.consent_counts()
    audit_total = await repo.audit_total()
    latest = await repo.latest_audit_at()
    anchor = await session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "audit.anchor_created")
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    now = dt.datetime.now(dt.UTC)
    tiles = [
        _tile(
            definitions,
            "consent_active",
            value=consents.get("active", 0),
            unit="consents",
            as_of=now,
        ),
        {
            "id": "consent_expired",
            "label": "Expired caregiver consents",
            "value": consents.get("expired", 0),
            "unit": "consents",
            "status": "ok",
            "suppressed": False,
            "source": "consents",
            "formula": "count(status = 'expired')",
            "as_of": now.isoformat(),
        },
        _tile(
            definitions,
            "audit_events",
            value=audit_total,
            unit="events",
            as_of=now,
        ),
        {
            "id": "audit_chain",
            "label": "Audit anchor",
            "value": (str(anchor.event_metadata.get("digest_sha256", ""))[:16] if anchor else None),
            "unit": "digest",
            "status": "ok" if anchor else "no_runs",
            "suppressed": False,
            "source": "audit_events",
            "formula": "sha256(canonical audit rows), stored in the anchors bucket",
            "note": (
                "Point-in-time anchor with a previous-digest link. This is not a per-row "
                "hash chain and does not prove completeness."
                if anchor
                else "No audit anchor has been recorded yet."
            ),
            "as_of": anchor.created_at.isoformat() if anchor else now.isoformat(),
        },
        {
            "id": "retention_runs",
            "label": "Retention and deletion jobs",
            "value": None,
            "unit": "status",
            "status": "not_configured",
            "suppressed": False,
            "source": "retention_run",
            "formula": "latest run per job",
            "note": "The scheduled retention worker is not part of the current build.",
            "as_of": now.isoformat(),
        },
        {
            "id": "mfa_coverage",
            "label": "MFA coverage",
            "value": None,
            "unit": "percent",
            "status": "unknown",
            "suppressed": False,
            "source": "keycloak",
            "formula": "users with MFA / active users",
            "note": "Keycloak MFA enrolment is not queried by this build.",
            "as_of": now.isoformat(),
        },
        {
            "id": "egress_policy",
            "label": "External model egress",
            "value": "disabled" if not services.settings.external_egress_enabled else "enabled",
            "unit": "status",
            "status": "ok",
            "suppressed": False,
            "source": "runtime settings",
            "formula": "EXTERNAL_EGRESS_ENABLED",
            "note": "External egress stays disabled until the PII gate is healthy.",
            "as_of": now.isoformat(),
        },
    ]
    return {
        "tiles": tiles,
        "as_of": now.isoformat(),
        "latest_audit_event_at": latest.isoformat() if latest else None,
    }


@router.get("/evaluations")
async def evaluations(
    context: AdminOrCompliance,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_analytics(services)
    definitions = _definitions(services)
    now = dt.datetime.now(dt.UTC)
    rows = list(
        await session.scalars(select(EvalRun).order_by(EvalRun.created_at.desc()).limit(20))
    )
    safety_run = next((row for row in rows if "red_flag_recall" in (row.metrics or {})), None)
    rag_run = next(
        (row for row in rows if row.framework == "ragas" and "faithfulness" in (row.metrics or {})),
        None,
    )

    def _run_tile(row: EvalRun | None, metric_id: str, key: str) -> dict[str, Any]:
        if row is None:
            return _tile(
                definitions,
                metric_id,
                value=None,
                unit="ratio",
                status="no_runs",
                note="No matching evaluation run has been recorded.",
                as_of=now,
            )
        value = float(row.metrics[key])
        return _tile(
            definitions,
            metric_id,
            value=value,
            unit="ratio",
            status="ok" if row.status == "passed" else row.status,
            note=f"{row.framework} run {row.id} recorded {row.created_at.isoformat()}.",
            as_of=row.created_at,
        )

    metrics = [
        _run_tile(safety_run, "red_flag_recall", "red_flag_recall"),
        _run_tile(rag_run, "rag_faithfulness", "faithfulness"),
    ]
    return {
        "runs": [
            {
                "id": str(row.id),
                "suite": row.suite,
                "framework": row.framework,
                "framework_version": row.framework_version,
                "status": row.status,
                "dataset_hash": row.dataset_hash,
                "git_sha": row.git_sha,
                "prompt_version": row.prompt_version,
                "graph_version": row.graph_version,
                "judge_alias": row.judge_alias,
                "case_count": row.case_count,
                "passed_cases": row.passed_cases,
                "failed_cases": row.failed_cases,
                "metrics": row.metrics,
                "artifact_key": row.artifact_key,
                "error_message": row.error_message,
                "created_at": row.created_at.isoformat(),
            }
            for row in rows
        ],
        "metrics": metrics,
        "frameworks": {"rag": "ragas", "non_rag": "deepeval"},
        "status": (
            "no_runs"
            if not rows
            else "failed"
            if any(row.status == "failed" for row in rows)
            else "ok"
        ),
        "as_of": now.isoformat(),
    }


@router.get("/eval-runs/{run_id}")
async def eval_run_detail(
    run_id: uuid.UUID,
    context: AdminOrCompliance,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_analytics(services)
    run = await session.get(EvalRun, run_id)
    if run is None:
        raise ProblemError(404, "eval_run_not_found", "Not found", "No such evaluation run.")
    metric_rows = list(
        await session.scalars(
            select(EvalMetricResult)
            .where(EvalMetricResult.run_id == run.id)
            .order_by(EvalMetricResult.metric_key)
        )
    )
    return {
        "id": str(run.id),
        "suite": run.suite,
        "framework": run.framework,
        "framework_version": run.framework_version,
        "status": run.status,
        "dataset_hash": run.dataset_hash,
        "git_sha": run.git_sha,
        "prompt_version": run.prompt_version,
        "graph_version": run.graph_version,
        "judge_alias": run.judge_alias,
        "case_count": run.case_count,
        "passed_cases": run.passed_cases,
        "failed_cases": run.failed_cases,
        "metrics": run.metrics,
        "thresholds": run.thresholds,
        "case_results": run.case_results,
        "metric_results": [
            {
                "id": str(row.id),
                "metric_key": row.metric_key,
                "value": row.value,
                "unit": row.unit,
                "framework": row.framework,
                "dimensions": row.dimensions,
                "created_at": row.created_at.isoformat(),
            }
            for row in metric_rows
        ],
        "artifact_key": run.artifact_key,
        "error_message": run.error_message,
        "created_at": run.created_at.isoformat(),
    }


@router.get("/metrics")
async def metric_registry(
    context: AdminOrCompliance,
    services: ServicesDep,
) -> dict[str, Any]:
    _require_analytics(services)
    return {
        "version": services.metrics.get("version"),
        "metrics": services.metrics.get("metrics", []),
    }


@router.get("/load-guard")
async def load_guard(
    context: AdminOnly,
    session: SessionDep,
    window_minutes: Annotated[int, Query(ge=1, le=120)] = 15,
    exclude_subjects: Annotated[list[str] | None, Query()] = None,
) -> dict[str, Any]:
    subjects = {value[:200] for value in (exclude_subjects or []) if value}
    if len(subjects) > 200:
        raise ProblemError(
            422, "cohort_too_large", "Cohort too large", "Exclude at most 200 subjects."
        )
    end = dt.datetime.now(dt.UTC)
    start = end - dt.timedelta(minutes=window_minutes)
    guard = await AnalyticsRepository(session).load_guard(
        start=start, end=end, exclude_subjects=subjects
    )
    return {
        "window_minutes": window_minutes,
        "start": start.isoformat(),
        "end": end.isoformat(),
        "traffic_class": "synthetic",
        "real_activity": guard["real_events"] > 0,
        **guard,
    }


@router.get("/finops")
async def finops(
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
) -> dict[str, Any]:
    _require_analytics(services)
    start, end = _period(days)
    usage = UsageRepository(session)
    summary = await usage.summary(start=start, end=end)
    by_purpose = await usage.by_purpose(start=start, end=end)
    reconciliation = await _latest_reconciliation(session)
    reconciliation_age = _age_hours(reconciliation.created_at) if reconciliation else None
    daily_run_rate = summary["cost_usd"] / days * 30 if summary["calls"] else 0.0
    return {
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "status": "observed" if summary["calls"] else "no_usage",
        "traffic_class": "real",
        "observed": summary,
        "by_purpose": by_purpose,
        "monthly_run_rate_usd": round(daily_run_rate, 4),
        "budgets_usd": services.prices.get("budgets", {}),
        "price_version": services.prices.get("version"),
        "price_basis_date": services.prices.get("effective_from"),
        "fx_usd_inr": services.prices.get("fx_usd_inr"),
        "finops_model_version": services.finops_model.get("model_version"),
        "reconciliation": reconciliation_out(reconciliation).model_dump(mode="json"),
        "reconciliation_age_hours": reconciliation_age,
        "reconciliation_stale": (reconciliation_age is None or reconciliation_age > 26),
        "as_of": end.isoformat(),
    }


@router.get("/finops/budgets")
async def finops_budgets(
    context: AdminOrCompliance,
    services: ServicesDep,
    session: SessionDep,
    period: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> list[dict[str, Any]]:
    _require_analytics(services)
    query = select(FinopsBudget).order_by(FinopsBudget.period.desc(), FinopsBudget.scope_type)
    if period:
        query = query.where(FinopsBudget.period == period)
    rows = list(await session.scalars(query.limit(500)))
    return [
        {
            "id": str(row.id),
            "scope_type": row.scope_type,
            "scope_id": row.scope_id,
            "period": row.period,
            "limit_usd": row.limit_usd,
            "alert_pct": row.alert_pct,
            "hard_stop": row.hard_stop,
            "owner": row.owner,
            "created_by": row.created_by,
            "updated_at": row.updated_at.isoformat(),
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.put("/finops/budgets")
async def upsert_finops_budget(
    body: FinopsBudgetUpsert,
    request: Request,
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_analytics(services)
    budget = await session.scalar(
        select(FinopsBudget).where(
            FinopsBudget.scope_type == body.scope_type,
            FinopsBudget.scope_id == body.scope_id,
            FinopsBudget.period == body.period,
        )
    )
    if budget is None:
        budget = FinopsBudget(**body.model_dump(), created_by=context.subject)
        session.add(budget)
    else:
        for key, value in body.model_dump().items():
            setattr(budget, key, value)
        budget.updated_at = dt.datetime.now(dt.UTC)
    await session.flush()
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="finops.budget_upserted",
        resource_type="finops_budget",
        resource_id=str(budget.id),
        trace_id=getattr(request.state, "trace_id", None),
        metadata={
            "scope_type": budget.scope_type,
            "scope_id": budget.scope_id,
            "period": budget.period,
        },
    )
    await session.commit()
    return {
        "id": str(budget.id),
        **body.model_dump(),
        "created_by": budget.created_by,
        "updated_at": budget.updated_at.isoformat(),
    }


@router.get("/finops/savings")
async def finops_savings(
    context: AdminOrCompliance,
    services: ServicesDep,
    session: SessionDep,
    period: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> list[dict[str, Any]]:
    _require_analytics(services)
    query = select(FinopsSaving).order_by(FinopsSaving.created_at.desc())
    if period:
        query = query.where(FinopsSaving.period_month == period)
    rows = list(await session.scalars(query.limit(500)))
    return [
        {
            "id": str(row.id),
            "title": row.title,
            "amount_usd": row.amount_usd,
            "period_month": row.period_month,
            "notes": row.notes,
            "created_by": row.created_by,
            "created_at": row.created_at.isoformat(),
        }
        for row in rows
    ]


@router.post("/finops/savings", status_code=201)
async def create_finops_saving(
    body: FinopsSavingCreate,
    request: Request,
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    _require_analytics(services)
    saving = FinopsSaving(**body.model_dump(), created_by=context.subject)
    session.add(saving)
    await session.flush()
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="finops.saving_created",
        resource_type="finops_saving",
        resource_id=str(saving.id),
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"period": saving.period_month, "amount_usd": saving.amount_usd},
    )
    await session.commit()
    return {
        "id": str(saving.id),
        **body.model_dump(),
        "created_by": saving.created_by,
        "created_at": saving.created_at.isoformat(),
    }


@router.get("/finops/export")
async def export_finops(
    context: AdminOrCompliance,
    services: ServicesDep,
    session: SessionDep,
    format: Annotated[str, Query(pattern="^(csv|json)$")] = "json",
    period: Annotated[str | None, Query(pattern=r"^\d{4}-(0[1-9]|1[0-2])$")] = None,
) -> Any:
    _require_analytics(services)
    selected_period = period or dt.datetime.now(dt.UTC).strftime("%Y-%m")
    start, end = _month_period(selected_period)
    usage = UsageRepository(session)
    summary = await usage.summary(start=start, end=end)
    by_purpose = await usage.by_purpose(start=start, end=end)
    budgets = list(
        await session.scalars(
            select(FinopsBudget)
            .where(FinopsBudget.period == selected_period)
            .order_by(FinopsBudget.scope_type)
        )
    )
    savings = list(
        await session.scalars(
            select(FinopsSaving)
            .where(FinopsSaving.period_month == selected_period)
            .order_by(FinopsSaving.created_at)
        )
    )
    payload = {
        "period": selected_period,
        "usage": {"summary": summary, "by_purpose": by_purpose},
        "budgets": [
            {
                "scope_type": row.scope_type,
                "scope_id": row.scope_id,
                "limit_usd": row.limit_usd,
                "alert_pct": row.alert_pct,
                "hard_stop": row.hard_stop,
                "owner": row.owner,
            }
            for row in budgets
        ],
        "savings": [
            {"title": row.title, "amount_usd": row.amount_usd, "notes": row.notes}
            for row in savings
        ],
    }
    if format == "json":
        return payload
    output = io.StringIO()
    writer = csv.DictWriter(
        output,
        fieldnames=["record_type", "name", "scope", "calls", "tokens", "amount_usd", "detail"],
    )
    writer.writeheader()
    writer.writerow(
        {
            "record_type": "usage_summary",
            "calls": summary["calls"],
            "tokens": summary["prompt_tokens"] + summary["completion_tokens"],
            "amount_usd": summary["cost_usd"],
        }
    )
    for row in by_purpose:
        writer.writerow(
            {
                "record_type": "usage_purpose",
                "name": row["purpose"],
                "scope": row["model_alias"],
                "calls": row["calls"],
                "tokens": row["prompt_tokens"] + row["completion_tokens"],
                "amount_usd": row["cost_usd"],
            }
        )
    for budget_row in budgets:
        writer.writerow(
            {
                "record_type": "budget",
                "name": budget_row.owner,
                "scope": f"{budget_row.scope_type}:{budget_row.scope_id}",
                "amount_usd": budget_row.limit_usd,
                "detail": (f"alert={budget_row.alert_pct}%; hard_stop={budget_row.hard_stop}"),
            }
        )
    for saving_row in savings:
        writer.writerow(
            {
                "record_type": "saving",
                "name": saving_row.title,
                "amount_usd": saving_row.amount_usd,
                "detail": saving_row.notes or "",
            }
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f"attachment; filename=finops-{selected_period}.csv"},
    )


@router.post("/finops/what-if")
async def finops_what_if(
    body: WhatIfRequest,
    context: AdminOnly,
    services: ServicesDep,
) -> WhatIfResponse:
    if not services.features.enabled("finops_what_if"):
        raise ProblemError(
            403,
            "feature_disabled",
            "FinOps what-if unavailable",
            "FinOps what-if is disabled by configuration.",
        )
    return calculate_what_if(services.finops_model, body)


@router.get("/finops/reconciliation")
async def finops_reconciliation(
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
) -> ReconciliationOut:
    _require_analytics(services)
    return reconciliation_out(await _latest_reconciliation(session))


@router.post("/finops/reconcile")
async def finops_reconcile(
    body: ReconcileRequest,
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
) -> ReconciliationOut:
    _require_analytics(services)
    if not services.settings.litellm_database_url:
        raise ProblemError(
            503,
            "reconciliation_unconfigured",
            "Reconciliation unavailable",
            "LITELLM_DATABASE_URL is not configured; no spend log can be read.",
        )
    record = await reconcile_spend(
        services,
        session,
        window_hours=body.window_hours,
        lag_minutes=body.lag_minutes,
    )
    await session.commit()
    return reconciliation_out(record)


@router.get("/insights")
async def insights(
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=365)] = 30,
    insight_status: Annotated[str | None, Query(alias="status")] = None,
) -> dict[str, Any]:
    _require_analytics(services)
    query = select(Insight).order_by(Insight.created_at.desc()).limit(200)
    if insight_status:
        query = query.where(Insight.status == insight_status)
    rows = list(await session.scalars(query))
    latest_snapshot = await _latest_snapshot(session)
    snapshot_age = _age_hours(latest_snapshot.captured_at) if latest_snapshot else None
    return {
        "generator": "scheduled_job",
        "ai_generated": any(row.ai_generated for row in rows),
        "note": (
            "Advisory only. Persisted insights are generated by the scheduled analytics job. "
            "A local model may rewrite wording; evidence stays deterministic. "
            "No insight changes config, prompts, models, budgets or clinical behaviour."
        ),
        "as_of": dt.datetime.now(dt.UTC).isoformat(),
        "status": "ok" if rows else "no_records",
        "snapshot": (
            {
                "captured_at": latest_snapshot.captured_at.isoformat(),
                "age_hours": snapshot_age,
                "stale": snapshot_age is None or snapshot_age > 26,
            }
            if latest_snapshot
            else None
        ),
        "counts": {
            "proposed": sum(1 for row in rows if row.status == "proposed"),
            "accepted": sum(1 for row in rows if row.status == "accepted"),
            "rejected": sum(1 for row in rows if row.status == "rejected"),
            "expired": sum(1 for row in rows if row.status == "expired"),
        },
        "items": [insight_out(row) for row in rows],
    }


@router.post("/insights/{insight_id}/decision")
async def decide(
    insight_id: uuid.UUID,
    body: InsightDecisionRequest,
    request: Request,
    context: AdminOnly,
    session: SessionDep,
) -> dict[str, Any]:
    insight = await decide_insight(
        session,
        insight_id=insight_id,
        status=body.status,
        decided_by=context.subject,
        note=body.note,
        trace_id=getattr(request.state, "trace_id", None),
    )
    await session.commit()
    await session.refresh(insight)
    return insight_out(insight)
