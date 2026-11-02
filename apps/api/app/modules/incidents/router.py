from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Annotated, Literal

from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.security import AuthContext, Role, require_roles
from app.modules.incidents.schemas import IncidentCreate, IncidentOut, IncidentUpdate
from app.repositories.audit import AuditRepository
from app.repositories.models import SafetyIncident
from fastapi import APIRouter, Depends, Query, Request, status
from sahyog_common.errors import ProblemError
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/incidents", tags=["incidents"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
IncidentAccess = Annotated[
    AuthContext,
    Depends(require_roles(Role.ADMIN, Role.COMPLIANCE, Role.DOCTOR)),
]

SORT_COLUMNS = {
    "created_at": SafetyIncident.created_at,
    "severity": SafetyIncident.severity,
    "status": SafetyIncident.status,
    "category": SafetyIncident.category,
    "closed_at": SafetyIncident.closed_at,
}


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


@router.get("")
async def list_incidents(
    context: IncidentAccess,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status_filter: Annotated[
        Literal["open", "investigating", "closed"] | None,
        Query(alias="status"),
    ] = None,
    severity: Annotated[
        Literal["low", "medium", "high", "critical"] | None,
        Query(),
    ] = None,
    category: Annotated[str | None, Query(max_length=80)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[
        Literal["created_at", "severity", "status", "category", "closed_at"], Query()
    ] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> dict[str, object]:
    conditions = []
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                SafetyIncident.title.ilike(pattern),
                SafetyIncident.detail.ilike(pattern),
                SafetyIncident.category.ilike(pattern),
                SafetyIncident.resolution.ilike(pattern),
                SafetyIncident.linked_resource_id.ilike(pattern),
            )
        )
    if status_filter:
        conditions.append(SafetyIncident.status == status_filter)
    if severity:
        conditions.append(SafetyIncident.severity == severity)
    if category:
        conditions.append(SafetyIncident.category == category)
    column = SORT_COLUMNS[sort]
    ordering = column.desc() if order == "desc" else column.asc()
    total = int(
        await session.scalar(
            select(func.count()).select_from(SafetyIncident).where(*conditions)
        )
        or 0
    )
    rows = list(
        await session.scalars(
            select(SafetyIncident)
            .where(*conditions)
            .order_by(ordering, SafetyIncident.id.asc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    )
    return {
        "items": [IncidentOut.model_validate(row) for row in rows],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_incident(
    body: IncidentCreate,
    request: Request,
    context: IncidentAccess,
    session: SessionDep,
) -> IncidentOut:
    incident = SafetyIncident(
        patient_id=body.patient_id,
        reported_by_subject=context.subject,
        severity=body.severity,
        category=body.category,
        title=body.title,
        detail=body.detail,
        linked_resource_type=body.linked_resource_type,
        linked_resource_id=body.linked_resource_id,
    )
    session.add(incident)
    await session.flush()
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="incident.created",
        resource_type="safety_incident",
        resource_id=str(incident.id),
        patient_id=incident.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"severity": incident.severity, "category": incident.category},
    )
    await session.commit()
    return IncidentOut.model_validate(incident)


@router.patch("/{incident_id}")
async def update_incident(
    incident_id: uuid.UUID,
    body: IncidentUpdate,
    request: Request,
    context: IncidentAccess,
    session: SessionDep,
) -> IncidentOut:
    incident = await session.scalar(
        select(SafetyIncident)
        .where(SafetyIncident.id == incident_id)
        .with_for_update()
    )
    if incident is None:
        raise ProblemError(404, "incident_not_found", "Not found", "No such incident.")
    if body.status == "closed" and context.primary_role not in {
        Role.ADMIN,
        Role.COMPLIANCE,
    }:
        raise ProblemError(
            403,
            "incident_close_forbidden",
            "Access denied",
            "Only admins and compliance staff can close incidents.",
        )
    previous_status = incident.status
    if body.status is not None:
        incident.status = body.status
        incident.closed_at = (
            dt.datetime.now(dt.UTC) if body.status == "closed" else None
        )
    if body.resolution is not None:
        incident.resolution = body.resolution
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="incident.closed" if incident.status == "closed" else "incident.updated",
        resource_type="safety_incident",
        resource_id=str(incident.id),
        patient_id=incident.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={
            "previous_status": previous_status,
            "status": incident.status,
            "has_resolution": incident.resolution is not None,
        },
    )
    await session.commit()
    return IncidentOut.model_validate(incident)
