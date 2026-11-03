"""Read-only LiteLLM spend reconciliation.

The gateway owns billing truth. This module copies spend rows into an application
table, then compares them with application usage rows by gateway request id. It never
updates or deletes a usage row to force a match; unmatched calls remain visible.
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from dataclasses import dataclass
from typing import Any

from app.core.services import Services
from app.modules.analytics.schemas import ReconciliationOut
from app.modules.notifications.service import NotificationService
from app.repositories.audit import AuditRepository
from app.repositories.models import (
    GatewaySpendLog,
    SpendReconciliation,
    UsageRecord,
)
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

logger = logging.getLogger(__name__)


class ReconciliationUnavailable(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported: int
    fetched: int
    window_start: dt.datetime
    window_end: dt.datetime


def _async_url(value: str) -> str:
    url = make_url(value)
    if url.drivername in {"postgresql", "postgres"}:
        url = url.set(drivername="postgresql+asyncpg")
    return url.render_as_string(hide_password=False)


def _naive(value: dt.datetime) -> dt.datetime:
    if value.tzinfo is None:
        return value
    return value.astimezone(dt.UTC).replace(tzinfo=None)


async def import_spend_logs(
    services: Services,
    *,
    start: dt.datetime,
    end: dt.datetime,
    batch_size: int = 500,
) -> ImportResult:
    """Copy gateway spend rows into the application database (idempotent)."""
    if not services.settings.litellm_database_url:
        raise ReconciliationUnavailable("litellm_database_url_unconfigured")
    engine = create_async_engine(
        _async_url(services.settings.litellm_database_url),
        pool_pre_ping=True,
        pool_size=2,
        max_overflow=2,
    )
    query = text(
        """
        SELECT request_id, model_group, model, spend, prompt_tokens,
               completion_tokens, total_tokens, status, "startTime"
        FROM "LiteLLM_SpendLogs"
        WHERE "startTime" >= :start AND "startTime" < :end
        ORDER BY "startTime"
        """
    )
    try:
        async with engine.connect() as connection:
            rows = (
                (await connection.execute(query, {"start": _naive(start), "end": _naive(end)}))
                .mappings()
                .all()
            )
    finally:
        await engine.dispose()
    imported = 0
    async with services.db.sessionmaker() as session:
        for offset in range(0, len(rows), batch_size):
            values = [
                {
                    "request_id": str(row["request_id"]),
                    "model_alias": str(row["model_group"] or row["model"] or "unknown"),
                    "spend_usd": float(row["spend"] or 0),
                    "prompt_tokens": int(row["prompt_tokens"] or 0),
                    "completion_tokens": int(row["completion_tokens"] or 0),
                    "total_tokens": int(row["total_tokens"] or 0),
                    "status": str(row["status"] or ""),
                    "started_at": row["startTime"].replace(tzinfo=dt.UTC),
                }
                for row in rows[offset : offset + batch_size]
            ]
            if not values:
                continue
            statement = pg_insert(GatewaySpendLog).values(values)
            statement = statement.on_conflict_do_update(
                index_elements=[GatewaySpendLog.request_id],
                set_={
                    "model_alias": statement.excluded.model_alias,
                    "spend_usd": statement.excluded.spend_usd,
                    "prompt_tokens": statement.excluded.prompt_tokens,
                    "completion_tokens": statement.excluded.completion_tokens,
                    "total_tokens": statement.excluded.total_tokens,
                    "status": statement.excluded.status,
                    "started_at": statement.excluded.started_at,
                    "imported_at": dt.datetime.now(dt.UTC),
                },
            )
            await session.execute(statement)
            imported += len(values)
        await session.commit()
    return ImportResult(imported=imported, fetched=len(rows), window_start=start, window_end=end)


def _status(
    *,
    configured: bool,
    app_calls: int,
    gateway_calls: int,
    matched_calls: int,
    unmatched_app_calls: int,
    unmatched_gateway_calls: int,
    variance_pct: float,
    tolerance: float,
) -> str:
    if not configured or (not app_calls and not gateway_calls):
        return "insufficient_data"
    if app_calls and gateway_calls and not matched_calls:
        return "variance"
    if variance_pct > tolerance:
        return "variance"
    if unmatched_app_calls or unmatched_gateway_calls:
        return "partial"
    return "matched"


async def reconcile_spend(
    services: Services,
    session: AsyncSession,
    *,
    window_hours: int = 24,
    lag_minutes: int = 5,
    import_first: bool = True,
) -> SpendReconciliation:
    now = dt.datetime.now(dt.UTC)
    end = now - dt.timedelta(minutes=max(0, lag_minutes))
    start = end - dt.timedelta(hours=window_hours)
    import_result: ImportResult | None = None
    import_error: str | None = None
    if import_first:
        try:
            import_result = await import_spend_logs(services, start=start, end=end)
        except ReconciliationUnavailable as exc:
            import_error = str(exc)
        except Exception as exc:  # noqa: BLE001 - gateway DB boundary
            import_error = "litellm_import_failed"
            logger.warning(
                "LiteLLM spend import failed",
                extra={"event": "finops.reconciliation.import_failed"},
                exc_info=exc,
            )

    app_rows = list(
        await session.scalars(
            select(UsageRecord).where(UsageRecord.created_at >= start, UsageRecord.created_at < end)
        )
    )
    gateway_rows = list(
        await session.scalars(
            select(GatewaySpendLog).where(
                GatewaySpendLog.started_at >= start,
                GatewaySpendLog.started_at < end,
            )
        )
    )
    gateway_ids = {row.request_id for row in gateway_rows}
    app_ids = {row.gateway_request_id for row in app_rows if row.gateway_request_id}
    matched_ids = app_ids & gateway_ids
    unmatched_app = [
        row
        for row in app_rows
        if not row.gateway_request_id or row.gateway_request_id not in gateway_ids
    ]
    unmatched_gateway = [row for row in gateway_rows if row.request_id not in app_ids]
    app_cost = round(sum(float(row.cost_usd) for row in app_rows), 8)
    gateway_cost = round(sum(float(row.spend_usd) for row in gateway_rows), 8)
    variance = round(gateway_cost - app_cost, 8)
    denominator = max(abs(gateway_cost), abs(app_cost))
    variance_pct = round(abs(variance) / denominator * 100, 4) if denominator else 0.0
    tolerance = float(
        services.app_config.get("finops", {}).get("reconciliation_tolerance_pct", 2.0)
    )
    configured = bool(services.settings.litellm_database_url) and import_error is None
    status = _status(
        configured=configured,
        app_calls=len(app_rows),
        gateway_calls=len(gateway_rows),
        matched_calls=len(matched_ids),
        unmatched_app_calls=len(unmatched_app),
        unmatched_gateway_calls=len(unmatched_gateway),
        variance_pct=variance_pct,
        tolerance=tolerance,
    )
    match_rate_pct = (
        round(len(matched_ids) / max(len(app_ids), len(gateway_ids)) * 100, 4)
        if app_ids or gateway_ids
        else 0.0
    )

    by_alias: dict[str, dict[str, Any]] = {}
    for row in app_rows:
        entry = by_alias.setdefault(
            row.model_alias,
            {"app_usd": 0.0, "gateway_usd": 0.0, "app_calls": 0, "gateway_calls": 0},
        )
        entry["app_usd"] = round(entry["app_usd"] + float(row.cost_usd), 8)
        entry["app_calls"] += 1
    for gateway_row in gateway_rows:
        entry = by_alias.setdefault(
            gateway_row.model_alias,
            {"app_usd": 0.0, "gateway_usd": 0.0, "app_calls": 0, "gateway_calls": 0},
        )
        entry["gateway_usd"] = round(entry["gateway_usd"] + float(gateway_row.spend_usd), 8)
        entry["gateway_calls"] += 1

    detail: dict[str, Any] = {
        "gateway_configured": bool(services.settings.litellm_database_url),
        "import_error": import_error,
        "imported_rows": import_result.imported if import_result else 0,
        "fetched_rows": import_result.fetched if import_result else 0,
        "lag_minutes": lag_minutes,
        "price_version": services.prices.get("version"),
        "price_basis_date": str(services.prices.get("effective_from") or ""),
        "fx_usd_inr": services.prices.get("fx_usd_inr"),
        "finops_model_version": services.finops_model.get("model_version"),
        "match_rate_pct": match_rate_pct,
        "by_alias": by_alias,
        "unmatched_app_request_ids": [
            str(row.gateway_request_id or f"usage:{row.id}") for row in unmatched_app[:50]
        ],
        "unmatched_gateway_request_ids": [row.request_id for row in unmatched_gateway[:50]],
        "note": (
            "Spend rows are copied read-only from LiteLLM. Usage rows are never edited. "
            "Recent calls inside the lag window may not be reconciled yet."
        ),
    }
    record = SpendReconciliation(
        window_start=start,
        window_end=end,
        app_cost_usd=app_cost,
        gateway_cost_usd=gateway_cost,
        app_calls=len(app_rows),
        gateway_calls=len(gateway_rows),
        matched_calls=len(matched_ids),
        unmatched_app_calls=len(unmatched_app),
        unmatched_gateway_calls=len(unmatched_gateway),
        variance_usd=variance,
        variance_pct=variance_pct,
        tolerance_pct=tolerance,
        status=status,
        detail=detail,
    )
    session.add(record)
    AuditRepository(session).append(
        actor_subject="system:finops",
        actor_role="service",
        action="finops.spend_reconciled",
        resource_type="spend_reconciliation",
        resource_id=str(record.id),
        trace_id=None,
        metadata={
            "status": status,
            "variance_pct": variance_pct,
            "tolerance_pct": tolerance,
            "app_calls": len(app_rows),
            "gateway_calls": len(gateway_rows),
            "matched_calls": len(matched_ids),
        },
    )
    await session.flush()
    if status == "variance":
        await _alert_variance(services, session, record)
    return record


async def _alert_variance(
    services: Services, session: AsyncSession, record: SpendReconciliation
) -> None:
    if not services.settings.notify_ops_subject:
        return
    try:
        await NotificationService(services, session).send(
            template_id="ops_alert",
            recipient_subject=services.settings.notify_ops_subject,
            recipient_role="admin",
            patient_id=None,
            locale="en-IN",
            data={
                "alert": (
                    "FinOps reconciliation variance "
                    f"{record.variance_pct:.2f}% exceeds {record.tolerance_pct:.2f}% "
                    f"for window {record.window_start.isoformat()} "
                    f"to {record.window_end.isoformat()}."
                )
            },
            actor_subject="system:finops",
            actor_role="service",
            requested_channels=["in_app", "email"],
            emergency=True,
            action_path="/analytics",
        )
        await session.flush()
    except Exception:  # noqa: BLE001 - alerting must not fail the reconciliation
        logger.warning(
            "FinOps variance alert could not be queued",
            extra={"event": "finops.reconciliation.alert_failed"},
        )


def reconciliation_out(record: SpendReconciliation | None) -> ReconciliationOut:
    if record is None:
        return ReconciliationOut(
            status="unavailable",
            note="No reconciliation run has been recorded yet.",
        )
    return ReconciliationOut(
        status=record.status,
        window_start=record.window_start,
        window_end=record.window_end,
        app_cost_usd=record.app_cost_usd,
        gateway_cost_usd=record.gateway_cost_usd,
        app_calls=record.app_calls,
        gateway_calls=record.gateway_calls,
        matched_calls=record.matched_calls,
        unmatched_app_calls=record.unmatched_app_calls,
        unmatched_gateway_calls=record.unmatched_gateway_calls,
        variance_usd=record.variance_usd,
        variance_pct=record.variance_pct,
        tolerance_pct=record.tolerance_pct,
        detail=record.detail,
        created_at=record.created_at,
        note=(
            "Read-only comparison of application usage with LiteLLM spend logs. "
            "This is not a invoice; tax and credits are excluded."
        ),
    )


def new_trace_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex}"[:64]
