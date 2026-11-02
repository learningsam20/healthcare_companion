"""Admin in-app observability: browse sessions/runs + deep links to Langfuse/Grafana.

Conversation bodies are visible to admin only (audited). Full span trees stay in Langfuse;
host metrics stay in Grafana/Prometheus — this surface aggregates the operational browse path.
"""

from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Annotated, Any, Literal

from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.security import AuthContext, Role, require_roles
from app.core.services import Services, get_services
from app.modules.handoffs.service import mtta_summary
from app.repositories.audit import AuditRepository
from app.repositories.models import (
    ChatMessage,
    ChatRun,
    ChatSession,
    Handoff,
    JobRun,
    SpendReconciliation,
    UsageRecord,
)
from app.repositories.usage import UsageRepository
from fastapi import APIRouter, Depends, Query, Request
from sahyog_common.errors import ProblemError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/admin/observability", tags=["admin-observability"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[Services, Depends(get_services)]
AdminOnly = Annotated[AuthContext, Depends(require_roles(Role.ADMIN))]


def _public_links(services: Services) -> dict[str, Any]:
    settings = services.settings
    langfuse = (getattr(settings, "langfuse_public_url", None) or "").strip()
    if not langfuse and settings.langfuse_host:
        # Prefer browser-facing URL; docker-internal host is useless in the SPA.
        langfuse = ""
    grafana = (getattr(settings, "grafana_public_url", None) or "").strip()
    prometheus = (getattr(settings, "prometheus_public_url", None) or "").strip()
    mailpit = (getattr(settings, "mailpit_public_url", None) or "").strip()
    embed = bool(getattr(settings, "observability_embed_grafana", True))
    return {
        "langfuse": {
            "url": langfuse or None,
            "configured": bool(settings.langfuse_public_key and settings.langfuse_secret_key),
            "capture_content": bool(settings.langfuse_capture_content),
            "trace_path_template": "{base}/trace/{trace_id}",
        },
        "grafana": {
            "url": grafana or None,
            "embed": embed and bool(grafana),
            "embed_url": f"{grafana.rstrip('/')}/?orgId=1&kiosk" if grafana and embed else None,
        },
        "prometheus": {"url": prometheus or None},
        "mailpit": {"url": mailpit or None},
        "note": (
            "In-app panels show app DB aggregates and conversation metadata. "
            "Open Langfuse for span trees; Grafana for host/Prometheus dashboards."
        ),
    }


def _trace_url(services: Services, trace_id: str | None) -> str | None:
    if not trace_id:
        return None
    links = _public_links(services)
    base = links["langfuse"]["url"]
    if not base:
        return None
    return f"{base.rstrip('/')}/trace/{trace_id}"


@router.get("/links")
async def observability_links(context: AdminOnly, services: ServicesDep) -> dict[str, Any]:
    return _public_links(services)


@router.get("/snapshot")
async def observability_snapshot(
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
    days: Annotated[int, Query(ge=1, le=90)] = 7,
) -> dict[str, Any]:
    """One-screen ops snapshot: traffic, FinOps, MTTA, jobs, handoffs."""
    end = dt.datetime.now(dt.UTC)
    start = end - dt.timedelta(days=days)
    usage = await UsageRepository(session).summary(start=start, end=end)
    try:
        mtta = await mtta_summary(session, window_hours=days * 24)
    except Exception:  # noqa: BLE001 — MTTA columns may lag a migrate on older DBs
        mtta = {
            "window_hours": days * 24,
            "acknowledged_count": 0,
            "mean_seconds": None,
            "p50_seconds": None,
            "p95_seconds": None,
            "max_seconds": None,
            "within_sla_count": 0,
            "within_sla_ratio": None,
            "sla_seconds_emergency": 120,
            "target_met": None,
        }
    open_handoffs = int(
        await session.scalar(
            select(func.count()).select_from(Handoff).where(Handoff.status.in_(("open", "assigned")))
        )
        or 0
    )
    overdue = int(
        await session.scalar(
            select(func.count())
            .select_from(Handoff)
            .where(
                Handoff.status.in_(("open", "assigned")),
                Handoff.sla_due_at.is_not(None),
                Handoff.sla_due_at < end,
            )
        )
        or 0
    )
    sessions = int(
        await session.scalar(
            select(func.count())
            .select_from(ChatSession)
            .where(ChatSession.created_at >= start, ChatSession.deleted_at.is_(None))
        )
        or 0
    )
    runs_failed = int(
        await session.scalar(
            select(func.count())
            .select_from(ChatRun)
            .where(ChatRun.started_at >= start, ChatRun.status == "failed")
        )
        or 0
    )
    runs_total = int(
        await session.scalar(
            select(func.count()).select_from(ChatRun).where(ChatRun.started_at >= start)
        )
        or 0
    )
    latest_jobs = list(
        await session.scalars(
            select(JobRun).order_by(JobRun.started_at.desc()).limit(8)
        )
    )
    latest_recon = (
        await session.execute(
            select(SpendReconciliation).order_by(SpendReconciliation.created_at.desc()).limit(1)
        )
    ).scalars().first()
    return {
        "period": {"days": days, "start": start.isoformat(), "end": end.isoformat()},
        "links": _public_links(services),
        "traffic": {
            "chat_sessions": sessions,
            "chat_runs": runs_total,
            "chat_runs_failed": runs_failed,
        },
        "finops": {
            "calls": usage["calls"],
            "cost_usd": usage["cost_usd"],
            "prompt_tokens": usage["prompt_tokens"],
            "completion_tokens": usage["completion_tokens"],
            "monthly_run_rate_usd": round(float(usage["cost_usd"]) / days * 30, 4)
            if usage["calls"]
            else 0.0,
            "reconciliation_status": latest_recon.status if latest_recon else None,
            "reconciliation_variance_pct": (
                float(latest_recon.variance_pct) if latest_recon else None
            ),
        },
        "handoffs": {
            "open": open_handoffs,
            "overdue": overdue,
            "mtta": mtta,
        },
        "jobs": [
            {
                "job_name": row.job_name,
                "status": row.status,
                "started_at": row.started_at.isoformat() if row.started_at else None,
                "finished_at": row.finished_at.isoformat() if row.finished_at else None,
                "error_code": row.error_code,
            }
            for row in latest_jobs
        ],
        "as_of": end.isoformat(),
    }


@router.get("/sessions")
async def list_ops_sessions(
    context: AdminOnly,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    owner_subject: Annotated[str | None, Query(max_length=200)] = None,
    status: Annotated[Literal["active", "archived", "deleted"] | None, Query()] = None,
    traffic_class: Annotated[Literal["real", "synthetic"] | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    conditions: list[Any] = []
    if status == "deleted":
        conditions.append(ChatSession.status == "deleted")
    elif status:
        conditions.append(ChatSession.status == status)
        conditions.append(ChatSession.deleted_at.is_(None))
    else:
        conditions.append(ChatSession.deleted_at.is_(None))
    if owner_subject:
        conditions.append(ChatSession.owner_subject == owner_subject)
    if traffic_class:
        conditions.append(ChatSession.traffic_class == traffic_class)
    if q:
        pattern = f"%{q.strip()}%"
        try:
            as_uuid = uuid.UUID(q.strip())
            conditions.append(
                or_(
                    ChatSession.id == as_uuid,
                    ChatSession.title.ilike(pattern),
                    ChatSession.owner_subject.ilike(pattern),
                )
            )
        except ValueError:
            conditions.append(
                or_(
                    ChatSession.title.ilike(pattern),
                    ChatSession.owner_subject.ilike(pattern),
                )
            )
    total = int(
        await session.scalar(select(func.count()).select_from(ChatSession).where(*conditions)) or 0
    )
    rows = list(
        await session.scalars(
            select(ChatSession)
            .where(*conditions)
            .order_by(ChatSession.updated_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    )
    # Message / run counts per page
    session_ids = [row.id for row in rows]
    msg_counts: dict[uuid.UUID, int] = {}
    run_counts: dict[uuid.UUID, int] = {}
    last_traces: dict[uuid.UUID, str | None] = {}
    if session_ids:
        for sid, count in (
            await session.execute(
                select(ChatMessage.session_id, func.count())
                .where(ChatMessage.session_id.in_(session_ids))
                .group_by(ChatMessage.session_id)
            )
        ).all():
            msg_counts[sid] = int(count)
        for sid, count in (
            await session.execute(
                select(ChatRun.session_id, func.count())
                .where(ChatRun.session_id.in_(session_ids))
                .group_by(ChatRun.session_id)
            )
        ).all():
            run_counts[sid] = int(count)
        for sid, trace in (
            await session.execute(
                select(ChatRun.session_id, ChatRun.trace_id)
                .where(ChatRun.session_id.in_(session_ids), ChatRun.trace_id.is_not(None))
                .order_by(ChatRun.started_at.desc())
            )
        ).all():
            last_traces.setdefault(sid, trace)

    return {
        "items": [
            {
                "id": str(row.id),
                "title": row.title,
                "owner_subject": row.owner_subject,
                "owner_role": row.owner_role,
                "patient_id": str(row.patient_id) if row.patient_id else None,
                "status": row.status,
                "locale": row.locale,
                "traffic_class": row.traffic_class,
                "message_count": msg_counts.get(row.id, 0),
                "run_count": run_counts.get(row.id, 0),
                "latest_trace_id": last_traces.get(row.id),
                "created_at": row.created_at.isoformat(),
                "updated_at": row.updated_at.isoformat(),
            }
            for row in rows
        ],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="updated_at",
            order="desc",
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


@router.get("/sessions/{session_id}")
async def get_ops_session(
    session_id: uuid.UUID,
    request: Request,
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
    include_content: Annotated[bool, Query()] = True,
) -> dict[str, Any]:
    """Admin conversation debugger: metadata + messages (audited) + runs + Langfuse links."""
    row = await session.scalar(select(ChatSession).where(ChatSession.id == session_id))
    if row is None:
        raise ProblemError(404, "session_not_found", "Not found", "No such chat session.")
    messages = list(
        await session.scalars(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.created_at.asc())
            .limit(500)
        )
    )
    runs = list(
        await session.scalars(
            select(ChatRun)
            .where(ChatRun.session_id == session_id)
            .order_by(ChatRun.started_at.desc())
            .limit(100)
        )
    )
    usage_rows = (
        await session.execute(
            select(
                func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
                func.coalesce(func.sum(UsageRecord.prompt_tokens), 0),
                func.coalesce(func.sum(UsageRecord.completion_tokens), 0),
                func.count(UsageRecord.id),
            ).where(UsageRecord.session_id == session_id)
        )
    ).one()
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="admin.chat_session_inspected",
        resource_type="chat_session",
        resource_id=str(session_id),
        patient_id=row.patient_id,
        trace_id=getattr(request.state, "trace_id", None),
        metadata={
            "include_content": include_content,
            "message_count": len(messages),
            "run_count": len(runs),
        },
    )
    await session.commit()
    return {
        "session": {
            "id": str(row.id),
            "title": row.title,
            "owner_subject": row.owner_subject,
            "owner_role": row.owner_role,
            "patient_id": str(row.patient_id) if row.patient_id else None,
            "status": row.status,
            "locale": row.locale,
            "traffic_class": row.traffic_class,
            "created_at": row.created_at.isoformat(),
            "updated_at": row.updated_at.isoformat(),
        },
        "usage": {
            "cost_usd": round(float(usage_rows[0]), 6),
            "prompt_tokens": int(usage_rows[1]),
            "completion_tokens": int(usage_rows[2]),
            "calls": int(usage_rows[3]),
        },
        "messages": [
            {
                "id": str(msg.id),
                "role": msg.role,
                "language": msg.language,
                "model_alias": msg.model_alias,
                "trace_id": msg.trace_id,
                "trace_url": _trace_url(services, msg.trace_id),
                "safety": msg.safety or {},
                "source_count": len(msg.sources or []),
                "content": msg.content if include_content else None,
                "content_chars": len(msg.content or ""),
                "created_at": msg.created_at.isoformat(),
            }
            for msg in messages
        ],
        "runs": [_run_out(services, run) for run in runs],
        "links": _public_links(services),
        "include_content": include_content,
        "privacy_note": (
            "Admin inspection is audited. Prefer Langfuse for span-level debug; "
            "message content is omitted from Langfuse when capture_content is false."
        ),
    }


@router.get("/runs")
async def list_ops_runs(
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status: Annotated[
        Literal["running", "interrupted", "completed", "failed", "cancelled"] | None,
        Query(),
    ] = None,
    graph: Annotated[str | None, Query(max_length=80)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    conditions = []
    if status:
        conditions.append(ChatRun.status == status)
    if graph:
        conditions.append(ChatRun.graph == graph)
    if q:
        pattern = f"%{q.strip()}%"
        try:
            as_uuid = uuid.UUID(q.strip())
            conditions.append(
                or_(
                    ChatRun.id == as_uuid,
                    ChatRun.session_id == as_uuid,
                    ChatRun.trace_id.ilike(pattern),
                    ChatRun.owner_subject.ilike(pattern),
                    ChatRun.error_code.ilike(pattern),
                )
            )
        except ValueError:
            conditions.append(
                or_(
                    ChatRun.trace_id.ilike(pattern),
                    ChatRun.owner_subject.ilike(pattern),
                    ChatRun.error_code.ilike(pattern),
                    ChatRun.graph.ilike(pattern),
                )
            )
    total = int(
        await session.scalar(select(func.count()).select_from(ChatRun).where(*conditions)) or 0
    )
    rows = list(
        await session.scalars(
            select(ChatRun)
            .where(*conditions)
            .order_by(ChatRun.started_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    )
    return {
        "items": [_run_out(services, run) for run in rows],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="started_at",
            order="desc",
            pages=math.ceil(total / page_size) if total else 0,
        ),
        "links": _public_links(services),
    }


def _run_out(services: Services, run: ChatRun) -> dict[str, Any]:
    duration_ms = None
    if run.ended_at and run.started_at:
        duration_ms = int((run.ended_at - run.started_at).total_seconds() * 1000)
    return {
        "id": str(run.id),
        "session_id": str(run.session_id),
        "owner_subject": run.owner_subject,
        "graph": run.graph,
        "graph_version": run.graph_version,
        "status": run.status,
        "interrupt_type": run.interrupt_type,
        "error_code": run.error_code,
        "trace_id": run.trace_id,
        "trace_url": _trace_url(services, run.trace_id),
        "started_at": run.started_at.isoformat() if run.started_at else None,
        "ended_at": run.ended_at.isoformat() if run.ended_at else None,
        "duration_ms": duration_ms,
    }
