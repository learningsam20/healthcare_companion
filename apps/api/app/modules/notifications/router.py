from __future__ import annotations

import datetime as dt
import hashlib
import math
import re
import secrets
import uuid
from typing import Annotated, Any, Literal

from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.ports import DeliveryError
from app.core.security import AuthContext, Role, get_auth_context, require_roles
from app.core.services import Services, get_services
from app.modules.notifications.schemas import (
    ContactCreate,
    ContactOut,
    DeliveryOut,
    NotificationDetailOut,
    NotificationOut,
    SendOut,
    SelfContactCreate,
    SendRequest,
    VerificationCodeRequest,
)
from app.modules.notifications.jobs import DEFAULT_MAX_DAYS, slack_patient_coverage
from app.modules.notifications.service import NotificationService
from app.repositories.audit import AuditRepository
from app.repositories.models import ContactChannel, ContactVerificationCode
from app.repositories.notifications import ContactChannelRepository, NotificationRepository
from fastapi import APIRouter, Depends, Query, Request
from sahyog_common.errors import ProblemError
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/notifications", tags=["notifications"])
me_router = APIRouter(prefix="/api/v1/me", tags=["notifications"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ContextDep = Annotated[AuthContext, Depends(get_auth_context)]
ServicesDep = Annotated[Services, Depends(get_services)]
AdminDep = Annotated[AuthContext, Depends(require_roles(Role.ADMIN))]
SelfServiceDep = Annotated[AuthContext, Depends(require_roles(Role.PATIENT, Role.CAREGIVER))]


def _trace(request: Request) -> str | None:
    return getattr(request.state, "trace_id", None)


def _contact_access(contact: ContactChannel | None, context: AuthContext) -> ContactChannel:
    if contact is None or (
        contact.subject != context.subject and Role.ADMIN.value not in context.roles
    ):
        raise ProblemError(404, "contact_not_found", "Not found", "No such contact.")
    return contact


@router.get("")
async def list_notifications(
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
    all_users: Annotated[bool, Query()] = False,
    status_filter: Annotated[str | None, Query(alias="status", max_length=20)] = None,
    channel: Annotated[str | None, Query(max_length=20)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    sort: Annotated[str, Query(max_length=20)] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    if all_users and context.primary_role is not Role.ADMIN:
        raise ProblemError(403, "forbidden", "Access denied", "Only admins can list all users.")
    repo = NotificationRepository(session)
    scope_subject = None if all_users else context.subject
    rows, total = await repo.list_grid(
        recipient_subject=scope_subject,
        status=status_filter,
        channel=channel,
        query=q,
        sort=sort,
        descending=order == "desc",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    return {
        "items": [NotificationOut.model_validate(row).model_dump(mode="json") for row in rows],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ).model_dump(),
        "unread": await repo.unread_count(scope_subject),
    }


@router.get("/templates")
async def list_templates(_context: ContextDep, services: ServicesDep) -> dict[str, Any]:
    """Catalog is readable by any signed-in role; sending remains admin-only."""
    return {
        "version": services.notifications_config.get("version"),
        "templates": [
            {
                "id": template.get("id"),
                "version": template.get("version"),
                "channels": template.get("channels", []),
                "clinical_detail": template.get("clinical_detail", False),
            }
            for template in services.notifications_config.get("templates", [])
        ],
    }


@router.get("/slack-coverage")
async def slack_coverage(
    context: AdminDep,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    """G-07: share of opted-in patient Slack contacts that are verified and deliverable."""
    return await slack_patient_coverage(
        session,
        expected_workspace=services.settings.slack_patient_workspace_id,
        adapter_configured=services.settings.slack_patient_configured,
        max_days=DEFAULT_MAX_DAYS,
    )


@router.get("/{notification_id}")
async def get_notification(
    notification_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
) -> NotificationDetailOut:
    repo = NotificationRepository(session)
    notification = await repo.get(notification_id)
    if notification is None or (
        notification.recipient_subject != context.subject and context.primary_role is not Role.ADMIN
    ):
        raise ProblemError(404, "notification_not_found", "Not found", "No such notification.")
    deliveries = await repo.deliveries(notification.id)
    detail = NotificationDetailOut.model_validate(notification)
    detail.deliveries = [DeliveryOut.model_validate(item) for item in deliveries]
    return detail


@router.post("/{notification_id}/read")
async def mark_read(
    notification_id: uuid.UUID,
    context: ContextDep,
    session: SessionDep,
) -> NotificationOut:
    repo = NotificationRepository(session)
    notification = await repo.get(notification_id)
    if notification is None or notification.recipient_subject != context.subject:
        raise ProblemError(404, "notification_not_found", "Not found", "No such notification.")
    await repo.mark_read(notification)
    await session.commit()
    return NotificationOut.model_validate(notification)


@router.get("/contacts/list")
async def list_contacts(
    context: AdminDep,
    session: SessionDep,
    subject: Annotated[str | None, Query(max_length=200)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    rows, total = await ContactChannelRepository(session).list(
        subject=subject, limit=page_size, offset=(page - 1) * page_size
    )
    return {
        "items": [ContactOut.model_validate(row).model_dump(mode="json") for row in rows],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="created_at",
            order="desc",
            pages=math.ceil(total / page_size) if total else 0,
        ).model_dump(),
    }


@router.post("/contacts", status_code=201)
async def upsert_contact(
    body: ContactCreate,
    request: Request,
    context: AdminDep,
    session: SessionDep,
) -> ContactOut:
    address = body.address.strip()
    if body.channel == "email" and "@" not in address:
        raise ProblemError(422, "invalid_address", "Invalid address", "Enter a valid email.")
    if body.channel == "sms" and not address.lstrip("+").isdigit():
        raise ProblemError(
            422, "invalid_address", "Invalid address", "Enter a phone number in digits."
        )
    if body.channel in {"slack_staff", "slack_patient"} and address[:1] not in {"U", "W", "C"}:
        raise ProblemError(
            422,
            "invalid_address",
            "Invalid address",
            "Use a Slack user, workspace or channel identifier.",
        )
    contact = ContactChannel(
        subject=body.subject,
        patient_id=body.patient_id,
        channel=body.channel,
        address=address,
        verified=body.verified,
        opt_in=body.opt_in,
        workspace_id=body.workspace_id,
        verified_at=None,
    )
    saved = await ContactChannelRepository(session).upsert(contact)
    if saved.verified:
        import datetime as dt

        saved.verified_at = dt.datetime.now(dt.UTC)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="notifications.contact_upserted",
        resource_type="contact_channel",
        resource_id=str(saved.id),
        patient_id=saved.patient_id,
        trace_id=_trace(request),
        metadata={
            "channel": saved.channel,
            "verified": saved.verified,
            "opt_in": saved.opt_in,
        },
    )
    await session.commit()
    return ContactOut.model_validate(saved)


async def _deliver_verification_code(
    services: Services, contact: ContactChannel, code: str
) -> tuple[str, str | None]:
    """Send the one-time code over the contact's own channel, honestly.

    Returns ``(delivery, error_code)``. Nothing is mocked: without an approved adapter the
    code is not delivered (outside dev/test it is not exposed at all) and the caller is told.
    """
    settings = services.settings
    if not settings.notify_send_external:
        return "external_disabled", None
    dispatcher = services.notifications
    if dispatcher is None or not dispatcher.configured(contact.channel):
        return "unconfigured", None
    try:
        await dispatcher.send(
            channel=contact.channel,
            address=contact.address,
            subject="Sahyog verification code",
            body=f"Your Sahyog verification code is {code}. It expires in 15 minutes.",
        )
    except DeliveryError as exc:
        return "failed", exc.code
    except Exception:  # noqa: BLE001 - adapter boundary, fail closed
        return "failed", "adapter_error"
    return "sent", None


@router.post("/contacts/{contact_id}/request-verification")
async def request_contact_verification(
    contact_id: uuid.UUID,
    request: Request,
    context: ContextDep,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    contact = _contact_access(await session.get(ContactChannel, contact_id), context)
    now = dt.datetime.now(dt.UTC)
    code = f"{secrets.randbelow(1_000_000):06d}"
    await session.execute(
        update(ContactVerificationCode)
        .where(
            ContactVerificationCode.contact_id == contact.id,
            ContactVerificationCode.consumed_at.is_(None),
        )
        .values(consumed_at=now)
    )
    verification = ContactVerificationCode(
        contact_id=contact.id,
        code_hash=hashlib.sha256(code.encode()).hexdigest(),
        expires_at=now + dt.timedelta(minutes=15),
    )
    session.add(verification)
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="contact.verification_requested",
        resource_type="contact_channel",
        resource_id=str(contact.id),
        patient_id=contact.patient_id,
        trace_id=_trace(request),
        metadata={"channel": contact.channel},
    )
    await session.commit()
    delivery, delivery_error = await _deliver_verification_code(services, contact, code)
    response: dict[str, Any] = {
        "expires_at": verification.expires_at.isoformat(),
        "delivery": delivery,
        "delivery_error": delivery_error,
    }
    if services.settings.app_env in {"dev", "test"}:
        response["code"] = code
    return response


@router.post("/contacts/{contact_id}/verify")
async def verify_contact(
    contact_id: uuid.UUID,
    body: VerificationCodeRequest,
    request: Request,
    context: ContextDep,
    session: SessionDep,
) -> ContactOut:
    contact = _contact_access(await session.get(ContactChannel, contact_id), context)
    now = dt.datetime.now(dt.UTC)
    verification = await session.scalar(
        select(ContactVerificationCode)
        .where(
            ContactVerificationCode.contact_id == contact.id,
            ContactVerificationCode.consumed_at.is_(None),
        )
        .order_by(ContactVerificationCode.created_at.desc())
        .limit(1)
    )
    if verification is None or verification.expires_at <= now:
        raise ProblemError(
            422, "verification_expired", "Code expired", "Request a new verification code."
        )
    verification.attempts += 1
    supplied_hash = hashlib.sha256(body.code.encode()).hexdigest()
    if not secrets.compare_digest(supplied_hash, verification.code_hash):
        if verification.attempts >= 5:
            verification.consumed_at = now
        await session.commit()
        raise ProblemError(422, "verification_invalid", "Invalid code", "The code is not valid.")
    verification.consumed_at = now
    contact.verified = True
    contact.verified_at = now
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="contact.verified",
        resource_type="contact_channel",
        resource_id=str(contact.id),
        patient_id=contact.patient_id,
        trace_id=_trace(request),
        metadata={"channel": contact.channel},
    )
    await session.commit()
    return ContactOut.model_validate(contact)


@me_router.get("/contacts")
async def my_contacts(context: SelfServiceDep, session: SessionDep) -> list[ContactOut]:
    rows, _ = await ContactChannelRepository(session).list(
        subject=context.subject, limit=100, offset=0
    )
    return [ContactOut.model_validate(row) for row in rows]


_SLACK_MEMBER_ID = re.compile(r"^[UW][A-Z0-9]{6,39}$")


@me_router.post("/contacts", status_code=201)
async def register_my_contact(
    body: SelfContactCreate,
    request: Request,
    context: SelfServiceDep,
    services: ServicesDep,
    session: SessionDep,
) -> ContactOut:
    """Self-register a contact (G-06/G-07). Always created unverified; verify via code."""
    address = body.address.strip()
    if body.channel == "email" and "@" not in address:
        raise ProblemError(422, "invalid_address", "Invalid address", "Enter a valid email.")
    if body.channel == "sms" and not address.lstrip("+").isdigit():
        raise ProblemError(
            422, "invalid_address", "Invalid address", "Enter a phone number in digits."
        )
    if body.channel == "slack_patient" and not _SLACK_MEMBER_ID.match(address):
        raise ProblemError(
            422,
            "invalid_address",
            "Invalid address",
            "Enter your Slack member ID (starts with U or W), not a channel.",
        )
    repo = ContactChannelRepository(session)
    existing = await repo.find(subject=context.subject, channel=body.channel)
    unchanged = existing is not None and existing.address == address
    workspace = (
        services.settings.slack_patient_workspace_id or None
        if body.channel == "slack_patient"
        else None
    )
    saved = await repo.upsert(
        ContactChannel(
            subject=context.subject,
            patient_id=context.patient_id,
            channel=body.channel,
            address=address,
            verified=bool(existing and unchanged and existing.verified),
            opt_in=body.opt_in,
            workspace_id=workspace,
            verified_at=existing.verified_at if existing and unchanged else None,
        )
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="contact.self_registered",
        resource_type="contact_channel",
        resource_id=str(saved.id),
        patient_id=saved.patient_id,
        trace_id=_trace(request),
        metadata={"channel": saved.channel, "verified": saved.verified, "opt_in": saved.opt_in},
    )
    await session.commit()
    return ContactOut.model_validate(saved)


@me_router.post("/contacts/{contact_id}/request-verification")
async def request_my_contact_verification(
    contact_id: uuid.UUID,
    request: Request,
    context: SelfServiceDep,
    services: ServicesDep,
    session: SessionDep,
) -> dict[str, Any]:
    """Design-path alias (G-38): same behaviour as the notifications route, owner-only."""
    return await request_contact_verification(contact_id, request, context, services, session)


@me_router.post("/contacts/{contact_id}/verify")
async def verify_my_contact(
    contact_id: uuid.UUID,
    body: VerificationCodeRequest,
    request: Request,
    context: SelfServiceDep,
    session: SessionDep,
) -> ContactOut:
    """Design-path alias (G-38) for ``POST /api/v1/me/contacts/{id}/verify``."""
    return await verify_contact(contact_id, body, request, context, session)


@me_router.delete("/contacts/{contact_id}", status_code=204)
async def delete_my_contact(
    contact_id: uuid.UUID,
    request: Request,
    context: SelfServiceDep,
    session: SessionDep,
) -> None:
    contact = await session.get(ContactChannel, contact_id)
    if contact is None or contact.subject != context.subject:
        raise ProblemError(404, "contact_not_found", "Not found", "No such contact.")
    contact.verified = False
    contact.opt_in = False
    contact.verified_at = None
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="contact.deleted",
        resource_type="contact_channel",
        resource_id=str(contact.id),
        patient_id=contact.patient_id,
        trace_id=_trace(request),
    )
    await session.commit()


@router.post("/send")
async def send_notification(
    body: SendRequest,
    request: Request,
    context: AdminDep,
    services: ServicesDep,
    session: SessionDep,
) -> SendOut:
    service = NotificationService(services, session)
    notification, deliveries = await service.send(
        template_id=body.template_id,
        recipient_subject=body.recipient_subject,
        recipient_role=body.recipient_role,
        patient_id=body.patient_id,
        locale=body.locale,
        data=body.data,
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        trace_id=_trace(request),
        requested_channels=body.channels,
    )
    await session.commit()
    detail = NotificationDetailOut.model_validate(notification)
    detail.deliveries = [DeliveryOut.model_validate(item) for item in deliveries]
    return SendOut(
        notification=detail,
        queued_channels=sum(1 for item in deliveries if item.status == "queued"),
        suppressed_channels=sum(1 for item in deliveries if item.status == "suppressed"),
    )
