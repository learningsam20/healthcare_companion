from __future__ import annotations

import math
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pagination import GridMeta, GridResponse
from app.core.security import AuthContext, Role, require_roles
from app.modules.patients.schemas import PatientOut
from app.repositories.audit import AuditRepository
from app.repositories.patients import PatientRepository

router = APIRouter(prefix="/api/v1/patients", tags=["patients"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
StaffAccess = Annotated[
    AuthContext,
    Depends(require_roles(Role.FRONT_DESK, Role.DOCTOR, Role.ADMIN, Role.COMPLIANCE)),
]


@router.get("")
async def list_patients(
    request: Request,
    context: StaffAccess,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[Literal["display_name", "created_at", "locale"], Query()] = "display_name",
    order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> GridResponse[PatientOut]:
    rows, total = await PatientRepository(session).list_grid(
        query=q,
        sort=sort,
        descending=order == "desc",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="patients.listed",
        resource_type="patient_registry",
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"count": total, "page": page},
    )
    await session.commit()
    items = [
        PatientOut(
            id=row.id,
            display_name=row.display_name,
            locale=row.locale,
            notify_email=row.notify_email,
            slack_user_id=row.slack_user_id,
            linked=bool(row.keycloak_subject),
            created_at=row.created_at,
        )
        for row in rows
    ]
    return GridResponse[PatientOut](
        items=items,
        meta=GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    )
