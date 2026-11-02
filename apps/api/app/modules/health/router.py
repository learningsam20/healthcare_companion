from __future__ import annotations

import asyncio
import datetime as dt
import logging
import time
from typing import Annotated, Any

import httpx
from fastapi import APIRouter, Depends
from fastapi.responses import JSONResponse, PlainTextResponse
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.services import Services, get_services
from app.repositories.models import JobRun, SpendReconciliation

logger = logging.getLogger(__name__)
router = APIRouter(tags=["health"])


async def _check_http(
    name: str, url: str, *, headers: dict[str, str] | None = None
) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async with httpx.AsyncClient(timeout=2.5) as client:
            response = await client.get(url, headers=headers)
        detail = "ok" if response.status_code < 500 else f"http_{response.status_code}"
        return {
            "name": name,
            "status": "up" if response.status_code < 500 else "down",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": detail,
        }
    except httpx.HTTPError:
        return {
            "name": name,
            "status": "down",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": "unreachable",
        }


async def _check_db(services: Services) -> dict[str, Any]:
    started = time.perf_counter()
    try:
        async with services.db.sessionmaker() as session:
            await session.execute(text("SELECT 1"))
        return {
            "name": "postgres",
            "status": "up",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": "ok",
        }
    except Exception:
        return {
            "name": "postgres",
            "status": "down",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": "unreachable",
        }


async def _check_redis(services: Services) -> dict[str, Any]:
    started = time.perf_counter()
    client = Redis.from_url(services.settings.redis_url, socket_timeout=2.0)
    try:
        await client.ping()
        return {
            "name": "redis",
            "status": "up",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": "ok",
        }
    except Exception:
        return {
            "name": "redis",
            "status": "down",
            "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            "detail": "unreachable",
        }
    finally:
        await client.aclose()


async def _check_malware(services: Services) -> dict[str, Any]:
    started = time.perf_counter()
    if not services.malware.configured:
        return {
            "name": "malware_scanner",
            "status": "up" if not services.malware.required else "down",
            "latency_ms": 0.0,
            "detail": "not_configured",
        }
    healthy = await services.malware.ping()
    return {
        "name": "malware_scanner",
        "status": "up" if healthy else "down",
        "latency_ms": round((time.perf_counter() - started) * 1000, 1),
        "detail": "clamav" if healthy else "unreachable",
    }


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok", "service": "sahyog-api"}


@router.get("/metrics", include_in_schema=False)
async def prometheus_metrics(
    services: Annotated[Services, Depends(get_services)],
) -> PlainTextResponse:
    """Prometheus text exposition for ARQ job heartbeats (G-30).

    Reads ``job_runs`` so Alertmanager rules ``SahyogJobStale`` /
    ``SahyogJobFailures`` can fire once scraped. No PHI; labels are job names only.
    """
    lines: list[str] = [
        "# HELP sahyog_job_last_success_timestamp Unix time of last succeeded job_runs row",
        "# TYPE sahyog_job_last_success_timestamp gauge",
        "# HELP sahyog_job_failures_total Cumulative failed job_runs rows",
        "# TYPE sahyog_job_failures_total counter",
        "# HELP sahyog_finops_variance_pct Latest spend reconciliation variance percent (G-31)",
        "# TYPE sahyog_finops_variance_pct gauge",
        "# HELP sahyog_finops_variance_over_tolerance 1 when latest reconciliation status is variance",
        "# TYPE sahyog_finops_variance_over_tolerance gauge",
        "# HELP sahyog_handoffs_open Open or assigned handoffs by overdue label",
        "# TYPE sahyog_handoffs_open gauge",
        "# HELP sahyog_handoff_mtta_seconds Rolling handoff MTTA (create→first assign)",
        "# TYPE sahyog_handoff_mtta_seconds gauge",
        "# HELP sahyog_handoff_mtta_within_sla_ratio Share of acks within priority SLA",
        "# TYPE sahyog_handoff_mtta_within_sla_ratio gauge",
        "# HELP sahyog_handoff_mtta_acknowledged_total Acknowledged handoffs in MTTA window",
        "# TYPE sahyog_handoff_mtta_acknowledged_total gauge",
    ]
    if not services.settings.database_url:
        lines.append("# no database configured")
        return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")

    from sqlalchemy import func, select

    async with services.db.sessionmaker() as session:
        success_rows = (
            await session.execute(
                select(JobRun.job_name, func.max(JobRun.finished_at))
                .where(JobRun.status == "succeeded")
                .group_by(JobRun.job_name)
            )
        ).all()
        fail_rows = (
            await session.execute(
                select(JobRun.job_name, func.count())
                .where(JobRun.status == "failed")
                .group_by(JobRun.job_name)
            )
        ).all()
        latest_recon = (
            await session.execute(
                select(SpendReconciliation)
                .order_by(SpendReconciliation.created_at.desc())
                .limit(1)
            )
        ).scalars().first()
        from app.repositories.models import Handoff

        now = dt.datetime.now(dt.UTC)
        open_total = int(
            await session.scalar(
                select(func.count())
                .select_from(Handoff)
                .where(Handoff.status.in_(("open", "assigned")))
            )
            or 0
        )
        overdue_total = int(
            await session.scalar(
                select(func.count())
                .select_from(Handoff)
                .where(
                    Handoff.status.in_(("open", "assigned")),
                    Handoff.sla_due_at.is_not(None),
                    Handoff.sla_due_at < now,
                )
            )
            or 0
        )
        from app.modules.handoffs.service import mtta_summary

        mtta = await mtta_summary(session, window_hours=24 * 30)

    for job_name, finished_at in success_rows:
        if finished_at is None:
            continue
        ts = finished_at.timestamp() if finished_at.tzinfo else finished_at.replace(tzinfo=dt.UTC).timestamp()
        safe = str(job_name).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'sahyog_job_last_success_timestamp{{job_name="{safe}"}} {ts:.3f}')
    for job_name, count in fail_rows:
        safe = str(job_name).replace("\\", "\\\\").replace('"', '\\"')
        lines.append(f'sahyog_job_failures_total{{job_name="{safe}"}} {int(count)}')
    if latest_recon is not None:
        lines.append(f"sahyog_finops_variance_pct {float(latest_recon.variance_pct):.4f}")
        over = 1 if latest_recon.status == "variance" else 0
        lines.append(f"sahyog_finops_variance_over_tolerance {over}")
    lines.append(f'sahyog_handoffs_open{{overdue="false"}} {max(0, open_total - overdue_total)}')
    lines.append(f'sahyog_handoffs_open{{overdue="true"}} {overdue_total}')
    if mtta["p50_seconds"] is not None:
        lines.append(f'sahyog_handoff_mtta_seconds{{stat="p50"}} {float(mtta["p50_seconds"]):.3f}')
    if mtta["mean_seconds"] is not None:
        lines.append(f'sahyog_handoff_mtta_seconds{{stat="mean"}} {float(mtta["mean_seconds"]):.3f}')
    if mtta["p95_seconds"] is not None:
        lines.append(f'sahyog_handoff_mtta_seconds{{stat="p95"}} {float(mtta["p95_seconds"]):.3f}')
    if mtta["within_sla_ratio"] is not None:
        lines.append(f"sahyog_handoff_mtta_within_sla_ratio {float(mtta['within_sla_ratio']):.4f}")
    lines.append(f"sahyog_handoff_mtta_acknowledged_total {int(mtta['acknowledged_count'])}")
    return PlainTextResponse("\n".join(lines) + "\n", media_type="text/plain; version=0.0.4")


@router.get("/readyz")
async def readyz(services: Annotated[Services, Depends(get_services)]) -> JSONResponse:
    settings = services.settings
    checks = await asyncio.gather(
        _check_db(services),
        _check_redis(services),
        _check_http("keycloak", settings.keycloak_jwks_url),
        _check_http("litellm", f"{settings.litellm_base_url.rstrip('/')}/health/liveliness"),
        _check_http("mcp_broker", f"{settings.mcp_broker_url.rstrip('/')}/healthz"),
    )
    check_list = list(checks)
    check_list.append(await _check_malware(services))
    if settings.ha_mode or settings.checkpointer_required:
        check_list.append(
            {
                "name": "checkpointer",
                "status": "up" if services.checkpointer is not None else "down",
                "latency_ms": 0.0,
                "detail": "configured" if services.checkpointer is not None else "required_missing",
            }
        )
    if settings.app_profile in {"core", "full"}:
        optional = await asyncio.gather(
            _check_http(
                "mcp_pii", f"{settings.pii_service_url.rstrip('/')}/healthz"
            ),
            _check_http(
                "mcp_stt", f"{settings.mcp_stt_url.rstrip('/')}/healthz"
            ),
        )
        check_list.extend(optional)
    ready = all(check["status"] == "up" for check in check_list)
    payload = {
        "ready": ready,
        "status": "ok" if ready else "degraded",
        "profile": settings.app_profile,
        "version": settings.version,
        "checked_at": dt.datetime.now(dt.UTC).isoformat(),
        "checks": check_list,
    }
    return JSONResponse(status_code=200 if ready else 503, content=payload)
