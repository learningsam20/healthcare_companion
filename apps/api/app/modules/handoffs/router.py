from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Annotated, Literal

from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.security import AuthContext, Role, require_roles
from app.modules.handoffs.schemas import (
    HandoffAssign,
    HandoffCreate,
    HandoffMttaSummary,
    HandoffOut,
    HandoffResolve,
)
from app.modules.handoffs.service import mtta_summary, mtta_within_sla, record_first_ack
from app.repositories.audit import AuditRepository
from app.repositories.models import Handoff
from fastapi import APIRouter, Depends, Query, Request, status
from sahyog_common.errors import ProblemError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/handoffs", tags=["handoffs"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ListAccess = Annotated[
    AuthContext,
    Depends(
        require_roles(
            Role.FRONT_DESK,
            Role.ADMIN,
            Role.DOCTOR,
            Role.COMPLIANCE,
        )
    ),
]
WriteAccess = Annotated[
    AuthContext,
    Depends(require_roles(Role.FRONT_DESK, Role.ADMIN, Role.DOCTOR)),
]

SORT_COLUMNS = {
    "created_at": Handoff.created_at,
    "status": Handoff.status,
    "clinic_code": Handoff.clinic_code,
    "resolved_at": Handoff.resolved_at,
    "sla_due_at": Handoff.sla_due_at,
    "priority": Handoff.priority,
}


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _handoff_out(row: Handoff) -> HandoffOut:
    now = dt.datetime.now(dt.UTC)
    overdue = bool(
        row.status in {"open", "assigned"}
        and row.sla_due_at is not None
        and row.sla_due_at < now
    )
    payload = HandoffOut.model_validate(row)
    return payload.model_copy(
        update={"overdue": overdue, "mtta_within_sla": mtta_within_sla(row)}
    )


async def _get_handoff(
    session: AsyncSession, handoff_id: uuid.UUID, *, lock: bool = False
) -> Handoff:
    query = select(Handoff).where(Handoff.id == handoff_id)
    if lock:
        query = query.with_for_update()
    handoff = await session.scalar(query)
    if handoff is None:
        raise ProblemError(404, "handoff_not_found", "Not found", "No such handoff.")
    return handoff


@router.get("")
async def list_handoffs(
    context: ListAccess,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status_filter: Annotated[
        Literal["open", "assigned", "resolved"] | None,
        Query(alias="status"),
    ] = None,
    overdue: Annotated[bool | None, Query()] = None,
    clinic_code: Annotated[str | None, Query(max_length=40)] = None,
    assigned_to_subject: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[
        Literal["created_at", "status", "clinic_code", "resolved_at", "sla_due_at", "priority"],
        Query(),
    ] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> dict[str, object]:
    conditions = []
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                Handoff.reason.ilike(pattern),
                Handoff.notes.ilike(pattern),
                Handoff.resource_id.ilike(pattern),
                Handoff.assigned_to_subject.ilike(pattern),
            )
        )
    if status_filter:
        conditions.append(Handoff.status == status_filter)
    if overdue is True:
        conditions.append(Handoff.status.in_(("open", "assigned")))
        conditions.append(Handoff.sla_due_at.is_not(None))
        conditions.append(Handoff.sla_due_at < dt.datetime.now(dt.UTC))
    if clinic_code:
        conditions.append(Handoff.clinic_code == clinic_code)
    if assigned_to_subject:
        conditions.append(Handoff.assigned_to_subject == assigned_to_subject)
    column = SORT_COLUMNS[sort]
    ordering = column.desc() if order == "desc" else column.asc()
    total = int(
        await session.scalar(select(func.count()).select_from(Handoff).where(*conditions)) or 0
    )
    rows = list(
        await session.scalars(
            select(Handoff)
            .where(*conditions)
            .order_by(ordering, Handoff.id.asc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    )
    return {
        "items": [_handoff_out(row) for row in rows],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


@router.get("/mtta", response_model=HandoffMttaSummary)
async def handoff_mtta(
    context: ListAccess,
    session: SessionDep,
    window_hours: Annotated[int, Query(ge=1, le=24 * 365)] = 24 * 30,
) -> HandoffMttaSummary:
    """Rolling MTTA (create → first assign) for staff ops dashboard."""
    return HandoffMttaSummary.model_validate(
        await mtta_summary(session, window_hours=window_hours)
    )


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_handoff(
    body: HandoffCreate,
    request: Request,
    context: WriteAccess,
    session: SessionDep,
) -> HandoffOut:
    handoff = Handoff(
        patient_id=body.patient_id,
        created_by_subject=context.subject,
        clinic_code=body.clinic_code,
        reason=body.reason,
        notes=body.notes,
        resource_type=body.resource_type,
        resource_id=body.resource_id,
    )
    session.add(handoff)
    await session.flush()
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="handoff.created",
        resource_type="handoff",
        resource_id=str(handoff.id),
        patient_id=handoff.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"clinic_code": handoff.clinic_code},
    )
    await session.commit()
    return _handoff_out(handoff)


@router.post("/{handoff_id}/assign")
async def assign_handoff(
    handoff_id: uuid.UUID,
    body: HandoffAssign,
    request: Request,
    context: WriteAccess,
    session: SessionDep,
) -> HandoffOut:
    handoff = await _get_handoff(session, handoff_id, lock=True)
    if handoff.status == "resolved":
        raise ProblemError(
            409,
            "handoff_resolved",
            "Handoff resolved",
            "A resolved handoff cannot be assigned.",
        )
    handoff.assigned_to_subject = body.assigned_to_subject
    handoff.status = "assigned"
    record_first_ack(handoff)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="handoff.assigned",
        resource_type="handoff",
        resource_id=str(handoff.id),
        patient_id=handoff.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={
            "assigned_to_subject": handoff.assigned_to_subject,
            "acknowledged_at": (
                handoff.acknowledged_at.isoformat() if handoff.acknowledged_at else None
            ),
            "mtta_seconds": handoff.mtta_seconds,
            "mtta_within_sla": mtta_within_sla(handoff),
        },
    )
    await session.commit()
    return _handoff_out(handoff)


@router.post("/{handoff_id}/resolve")
async def resolve_handoff(
    handoff_id: uuid.UUID,
    body: HandoffResolve,
    request: Request,
    context: WriteAccess,
    session: SessionDep,
) -> HandoffOut:
    handoff = await _get_handoff(session, handoff_id, lock=True)
    if handoff.status == "resolved":
        raise ProblemError(
            409,
            "handoff_resolved",
            "Handoff resolved",
            "This handoff is already resolved.",
        )
    handoff.status = "resolved"
    handoff.notes = body.notes
    handoff.resolved_at = dt.datetime.now(dt.UTC)
    if handoff.assigned_to_subject is None:
        handoff.assigned_to_subject = context.subject
    record_first_ack(handoff, at=handoff.resolved_at)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="handoff.resolved",
        resource_type="handoff",
        resource_id=str(handoff.id),
        patient_id=handoff.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={
            "has_notes": True,
            "mtta_seconds": handoff.mtta_seconds,
            "mtta_within_sla": mtta_within_sla(handoff),
        },
    )
    await session.commit()
    return _handoff_out(handoff)
