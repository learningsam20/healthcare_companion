from __future__ import annotations

import datetime as dt
import math
import uuid
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query, Request
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.security import AuthContext, Role, require_roles
from app.modules.review.schemas import CloseReviewRequest, ReviewTaskOut
from app.repositories.audit import AuditRepository
from app.repositories.models import ReviewTask
from app.repositories.review import ReviewRepository

router = APIRouter(prefix="/api/v1/review-queue", tags=["review"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ReviewAccess = Annotated[
    AuthContext,
    Depends(
        require_roles(
            Role.DOCTOR,
            Role.PHARMACIST,
            Role.FRONT_DESK,
            Role.COMPLIANCE,
            Role.ADMIN,
        )
    ),
]


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _out(task, display_name: str | None) -> ReviewTaskOut:  # type: ignore[no-untyped-def]
    result = ReviewTaskOut.model_validate(task)
    result.patient_display_name = display_name
    return result


@router.get("")
async def list_review_tasks(
    context: ReviewAccess,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    status_filter: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    assigned_role: Annotated[str | None, Query(max_length=20)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[
        Literal["created_at", "due_at", "status", "assigned_role"], Query()
    ] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> dict[str, object]:
    role = context.primary_role
    scope_role: str | None = assigned_role
    if role not in {Role.ADMIN, Role.COMPLIANCE}:
        scope_role = role.value
    rows, total = await ReviewRepository(session).list_grid(
        status=status_filter,
        assigned_role=scope_role,
        owner_subject=None,
        query=q,
        sort=sort,
        descending=order == "desc",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {
        "items": [_out(task, display_name) for task, display_name in rows],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


async def _task_for(context: AuthContext, session: AsyncSession, task_id: uuid.UUID) -> ReviewTask:
    task = await ReviewRepository(session).get(task_id, lock=True)
    if task is None:
        raise ProblemError(404, "review_task_not_found", "Not found", "No such review task.")
    if (
        context.primary_role not in {Role.ADMIN, Role.COMPLIANCE}
        and task.assigned_role != context.primary_role.value
    ):
        raise ProblemError(403, "forbidden", "Access denied", "This task is for another role.")
    return task


@router.post("/{task_id}/claim")
async def claim_review_task(
    task_id: uuid.UUID,
    request: Request,
    context: ReviewAccess,
    session: SessionDep,
) -> ReviewTaskOut:
    task = await _task_for(context, session, task_id)
    if task.status == "closed":
        raise ProblemError(409, "task_closed", "Task closed", "This task is already closed.")
    if task.owner_subject and task.owner_subject != context.subject:
        raise ProblemError(
            409,
            "task_owned",
            "Already claimed",
            "Another clinician already owns this review task.",
        )
    task.owner_subject = context.subject
    task.status = "in_progress"
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="review_task.claimed",
        resource_type="review_task",
        resource_id=str(task.id),
        patient_id=task.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
    )
    await session.commit()
    return _out(task, None)


@router.post("/{task_id}/close")
async def close_review_task(
    task_id: uuid.UUID,
    body: CloseReviewRequest,
    request: Request,
    context: ReviewAccess,
    session: SessionDep,
) -> ReviewTaskOut:
    task = await _task_for(context, session, task_id)
    if task.status == "closed":
        raise ProblemError(409, "task_closed", "Task closed", "This task is already closed.")
    if (
        context.primary_role not in {Role.ADMIN, Role.COMPLIANCE}
        and task.owner_subject
        and task.owner_subject != context.subject
    ):
        raise ProblemError(
            403,
            "forbidden",
            "Access denied",
            "Only the owner of this review task can close it.",
        )
    if (
        context.primary_role not in {Role.ADMIN, Role.COMPLIANCE}
        and not task.owner_subject
    ):
        # Claiming is the doctor workflow; auto-claim on close so the action sticks.
        task.owner_subject = context.subject
        if task.status == "open":
            task.status = "in_progress"
    task.status = "closed"
    task.owner_subject = task.owner_subject or context.subject
    task.resolution = body.resolution
    task.closed_at = dt.datetime.now(dt.UTC)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="review_task.closed",
        resource_type="review_task",
        resource_id=str(task.id),
        patient_id=task.patient_id,
        consent_id=context.consent_id,
        trace_id=_trace(request),
        metadata={"has_resolution": True},
    )
    await session.commit()
    return _out(task, None)
