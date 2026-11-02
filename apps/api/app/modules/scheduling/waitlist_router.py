"""HTTP surface for the front-desk waitlist claim queue."""

from __future__ import annotations

import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.security import AuthContext, Role, require_roles
from app.core.services import Services, get_services
from app.modules.scheduling.waitlist import (
    WaitlistCloseRequest,
    WaitlistItemOut,
    claim_waitlist_item,
    close_waitlist_item,
    list_waitlist,
)
from app.repositories.scheduling import AppointmentRepository

router = APIRouter(prefix="/api/v1/waitlist", tags=["waitlist"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[Services, Depends(get_services)]
DeskAccess = Annotated[AuthContext, Depends(require_roles(Role.FRONT_DESK, Role.ADMIN))]


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


async def _item_out(
    session: AsyncSession,
    services: Services,
    appointment,
    locale: str,
) -> WaitlistItemOut:
    from app.modules.scheduling.schemas import AppointmentOut

    names = await AppointmentRepository(session).patient_names(
        {pid for pid in (appointment.patient_id, appointment.waitlist_offer_patient_id) if pid}
    )
    kinds = await AppointmentRepository(session).visit_kinds([appointment])
    base = AppointmentOut.model_validate(appointment).model_copy(
        update={
            "specialty_label": services.specialty_label(appointment.specialty_code, locale),
            "patient_display_name": (
                names.get(appointment.patient_id) if appointment.patient_id else None
            ),
            "visit_kind": kinds.get(appointment.id, "unknown"),
        }
    )
    return WaitlistItemOut(
        **base.model_dump(),
        offer_patient_display_name=(
            names.get(appointment.waitlist_offer_patient_id)
            if appointment.waitlist_offer_patient_id
            else None
        ),
    )


@router.get("")
async def get_waitlist(
    context: DeskAccess,
    services: ServicesDep,
    session: SessionDep,
    status: Annotated[
        Literal["open", "claimed", "closed", "active"] | None, Query()
    ] = "active",
    clinic: Annotated[str | None, Query(max_length=40)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[
        Literal["starts_at", "created_at", "no_show_risk", "waitlist_claimed_at"], Query()
    ] = "starts_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "asc",
) -> dict:
    return await list_waitlist(
        session,
        services,
        context,
        status=status,
        clinic=clinic,
        query=q,
        page=page,
        page_size=page_size,
        sort=sort,
        order=order,
        locale=context.locale,
    )


@router.post("/{appointment_id}/claim")
async def claim_item(
    appointment_id: uuid.UUID,
    request: Request,
    context: DeskAccess,
    services: ServicesDep,
    session: SessionDep,
) -> WaitlistItemOut:
    appointment = await claim_waitlist_item(
        session, context, appointment_id, trace_id=_trace(request)
    )
    await session.commit()
    await session.refresh(appointment)
    return await _item_out(session, services, appointment, context.locale)


@router.post("/{appointment_id}/close")
async def close_item(
    appointment_id: uuid.UUID,
    body: WaitlistCloseRequest,
    request: Request,
    context: DeskAccess,
    services: ServicesDep,
    session: SessionDep,
) -> WaitlistItemOut:
    appointment = await close_waitlist_item(
        session,
        services,
        context,
        appointment_id,
        body,
        trace_id=_trace(request),
        locale=context.locale,
    )
    await session.commit()
    await session.refresh(appointment)
    return await _item_out(session, services, appointment, context.locale)
