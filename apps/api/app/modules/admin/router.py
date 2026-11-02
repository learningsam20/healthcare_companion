from __future__ import annotations

import csv
import datetime as dt
import io
import json
import math
from typing import Annotated, Any, Literal

from app.agents.pii_gate import PiiGate
from app.core.db import get_session
from app.core.pagination import GridMeta
from app.core.security import AuthContext, Role, require_roles
from app.core.services import Services, get_services
from app.modules.admin.schemas import (
    AuditEventOut,
    AuditEventOutPublic,
    FlagChangeOut,
    FlagOut,
    FlagUpdate,
    GovernancePatch,
)
from app.modules.compliance import service as compliance
from app.repositories.audit import AuditRepository
from app.repositories.flags import FeatureFlagRepository
from app.repositories.models import Notification, NotificationDelivery
from app.repositories.usage import UsageRepository
from fastapi import APIRouter, Depends, File, Form, Query, Request, Response, UploadFile
from sahyog_common.errors import ProblemError
from sahyog_common.feature_flags import FeatureFlagError, FlagClass
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/admin", tags=["admin"])

SessionDep = Annotated[AsyncSession, Depends(get_session)]
ServicesDep = Annotated[Services, Depends(get_services)]
AdminOnly = Annotated[AuthContext, Depends(require_roles(Role.ADMIN))]
AdminOrCompliance = Annotated[AuthContext, Depends(require_roles(Role.ADMIN, Role.COMPLIANCE))]


def _flag_out(services: Services, key: str, definition) -> FlagOut:  # type: ignore[no-untyped-def]
    effective = services.features.get(key)
    return FlagOut(
        key=key,
        value=effective.value,
        default=definition.default,
        source=effective.source,
        flag_class=effective.flag_class.value,
        owner=effective.owner,
        expires=effective.expires,
        description=definition.description,
        runtime_changeable=definition.flag_class is FlagClass.RUNTIME,
    )


def _strip_secrets(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            key: _strip_secrets(item)
            for key, item in value.items()
            if not any(marker in key.lower() for marker in ("secret", "password", "token", "key"))
        }
    if isinstance(value, list):
        return [_strip_secrets(item) for item in value]
    return value


@router.get("/flags")
async def list_flags(
    context: AdminOnly,
    services: ServicesDep,
) -> dict[str, Any]:
    definitions = {definition.key: definition for definition in services.feature_registry.flags}
    items = [
        _flag_out(services, key, definitions[key]).model_dump(mode="json")
        for key in sorted(definitions)
    ]
    return {
        "registry_version": services.feature_registry.version,
        "items": items,
        "note": "Locked safety flags cannot be disabled by any actor.",
    }


@router.patch("/flags/{key}")
async def update_flag(
    key: str,
    body: FlagUpdate,
    request: Request,
    context: AdminOnly,
    services: ServicesDep,
    session: SessionDep,
) -> FlagOut:
    definitions = {definition.key: definition for definition in services.feature_registry.flags}
    definition = definitions.get(key)
    if definition is None:
        raise ProblemError(404, "flag_not_found", "Not found", "No such feature flag.")
    if definition.flag_class is not FlagClass.RUNTIME:
        raise ProblemError(
            409,
            "flag_not_runtime",
            "Cannot change at runtime",
            f"{key} is {definition.flag_class.value}; change configuration and redeploy.",
        )
    try:
        old_value, new_value = services.features.set_runtime(key, body.value)
    except FeatureFlagError as exc:
        raise ProblemError(409, "flag_locked", "Flag cannot change", str(exc)) from exc
    repo = FeatureFlagRepository(session)
    await repo.upsert_override(flag_key=key, value=body.value, updated_by=context.subject)
    await repo.record(
        flag_key=key,
        old_value=old_value,
        new_value=new_value,
        actor_subject=context.subject,
        reason=body.reason,
    )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="admin.feature_flag_changed",
        resource_type="feature_flag",
        resource_id=key,
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"old_value": old_value, "new_value": new_value, "reason": body.reason},
    )
    await session.commit()
    return _flag_out(services, key, definition)


@router.get("/flags/changes")
async def flag_changes(
    context: AdminOnly,
    session: SessionDep,
) -> list[FlagChangeOut]:
    rows = await FeatureFlagRepository(session).recent(limit=50)
    return [FlagChangeOut.model_validate(row) for row in rows]


@router.get("/audit")
async def audit_events(
    context: AdminOrCompliance,
    session: SessionDep,
    q: Annotated[str | None, Query(max_length=120)] = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    actor_role: Annotated[str | None, Query(max_length=20)] = None,
    date_from: Annotated[dt.date | None, Query()] = None,
    date_to: Annotated[dt.date | None, Query()] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
    sort: Annotated[Literal["created_at", "action", "actor_role"], Query()] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> dict[str, Any]:
    start = dt.datetime.combine(date_from, dt.time.min, tzinfo=dt.UTC) if date_from else None
    end = dt.datetime.combine(date_to, dt.time.max, tzinfo=dt.UTC) if date_to else None
    rows, total = await AuditRepository(session).list_events(
        query=q,
        action=action,
        actor_role=actor_role,
        start=start,
        end=end,
        sort=sort,
        descending=order == "desc",
        limit=page_size,
        offset=(page - 1) * page_size,
    )
    if context.primary_role is Role.COMPLIANCE:
        items: list[Any] = [AuditEventOutPublic.model_validate(row) for row in rows]
    else:
        items = [AuditEventOut.model_validate(row) for row in rows]
    return {
        "items": items,
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort=sort,
            order=order,
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }


@router.get("/audit/chain")
async def audit_chain_status(
    context: AdminOrCompliance,
    services: ServicesDep,
) -> dict[str, Any]:
    """Latest hash-chain verification result from the audit.verify_chain job."""
    from app.modules.ops.audit_verify import latest_verify_status

    return await latest_verify_status(services)


@router.post("/audit/chain/verify")
async def audit_chain_verify_now(
    context: AdminOnly,
    services: ServicesDep,
) -> dict[str, Any]:
    """Run an on-demand hash-chain walk and return the recorded job result."""
    from app.modules.ops.audit_verify import latest_verify_status, run_audit_chain_verify

    try:
        detail = await run_audit_chain_verify(services)
        return {"triggered": True, "status": detail.get("status"), "detail": detail}
    except Exception as exc:  # noqa: BLE001 — surface broken chain without 500ing the console
        latest = await latest_verify_status(services)
        return {
            "triggered": True,
            "status": latest.get("status") or "broken",
            "detail": latest.get("detail") or {},
            "error": str(exc)[:300],
        }


@router.get("/audit/export", response_model=None)
async def export_audit_events(
    request: Request,
    context: AdminOrCompliance,
    session: SessionDep,
    format: Annotated[Literal["csv", "json"], Query()] = "csv",
    q: Annotated[str | None, Query(max_length=120)] = None,
    action: Annotated[str | None, Query(max_length=80)] = None,
    actor_role: Annotated[str | None, Query(max_length=20)] = None,
    date_from: Annotated[dt.date | None, Query()] = None,
    date_to: Annotated[dt.date | None, Query()] = None,
    sort: Annotated[Literal["created_at", "action", "actor_role"], Query()] = "created_at",
    order: Annotated[Literal["asc", "desc"], Query()] = "desc",
) -> Any:
    start = dt.datetime.combine(date_from, dt.time.min, tzinfo=dt.UTC) if date_from else None
    end = dt.datetime.combine(date_to, dt.time.max, tzinfo=dt.UTC) if date_to else None
    rows, _ = await AuditRepository(session).list_events(
        query=q,
        action=action,
        actor_role=actor_role,
        start=start,
        end=end,
        sort=sort,
        descending=order == "desc",
        limit=5000,
        offset=0,
    )
    schema = AuditEventOutPublic if context.primary_role is Role.COMPLIANCE else AuditEventOut
    items = [schema.model_validate(row).model_dump(mode="json", by_alias=True) for row in rows]
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="admin.audit_exported",
        resource_type="audit_export",
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"format": format, "rows": len(items)},
    )
    await session.commit()
    if format == "json":
        return items
    output = io.StringIO()
    fieldnames = (
        list(items[0])
        if items
        else [
            "id",
            "actor_subject",
            "actor_role",
            "action",
            "resource_type",
            "resource_id",
            "created_at",
        ]
    )
    writer = csv.DictWriter(output, fieldnames=fieldnames)
    writer.writeheader()
    for item in items:
        writer.writerow(
            {
                key: json.dumps(value) if isinstance(value, (dict, list)) else value
                for key, value in item.items()
            }
        )
    return Response(
        output.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit-export.csv"},
    )


@router.get("/prompts")
async def list_prompts(context: AdminOnly, services: ServicesDep) -> dict[str, Any]:
    return {
        "items": [
            {"name": name, "id": prompt.get("id", name), "version": prompt.get("version")}
            for name, prompt in sorted(services.prompts.items())
        ]
    }


@router.get("/model-routes")
async def model_routes(context: AdminOnly, services: ServicesDep) -> dict[str, Any]:
    return {
        "version": services.models_config.get("version"),
        "purposes": _strip_secrets(services.models_config.get("purposes", {})),
        "aliases": _strip_secrets(services.models_config.get("aliases", {})),
    }


@router.get("/costs")
async def costs(context: AdminOnly, session: SessionDep) -> dict[str, Any]:
    end = dt.datetime.now(dt.UTC)
    start = end - dt.timedelta(days=30)
    usage = UsageRepository(session)
    return {
        "period": {"start": start.isoformat(), "end": end.isoformat(), "days": 30},
        "summary": await usage.summary(start=start, end=end),
        "by_purpose": await usage.by_purpose(start=start, end=end),
    }


@router.get("/compliance")
async def compliance_status(
    context: AdminOrCompliance,
    session: SessionDep,
    services: ServicesDep,
) -> dict[str, Any]:
    clinical = await compliance.get_attestation(session, compliance.CLINICAL)
    dpdp = await compliance.get_attestation(session, compliance.DPDP)
    gov = await compliance.get_governance(session)
    pii = await PiiGate(services.settings).health()
    return {
        "clinical_validation": compliance.attestation_public(clinical, kind=compliance.CLINICAL),
        "dpdp_audit": compliance.attestation_public(dpdp, kind=compliance.DPDP),
        "governance": gov,
        "pii": pii,
        "egress": {
            "env_enabled": bool(services.settings.external_egress_enabled),
            "admin_toggle": bool(gov.get("external_egress_enabled", False)),
            "may_enable": bool(
                pii.get("composite_ready")
                and (dpdp is not None and dpdp.status == "attested")
                and not await compliance.dpdp_blocks_processing(session)
            ),
            "note": (
                "EXTERNAL_EGRESS remains env-gated and fail-closed until composite PII "
                "is healthy, DPDP is attested, and security signs off."
            ),
        },
        "disclaimer": (
            "Attestation records product owner sign-off on uploaded reports. "
            "It is not CDSCO/FDA/MDR clearance."
        ),
    }


@router.post("/compliance/{kind}/attest")
async def attest_compliance(
    kind: Literal["clinical_validation", "dpdp_audit"],
    request: Request,
    context: AdminOrCompliance,
    session: SessionDep,
    services: ServicesDep,
    status: Annotated[str, Form()] = "attested",
    approver_name: Annotated[str, Form()] = "",
    approver_role: Annotated[str, Form()] = "",
    attestation_checked: Annotated[str, Form()] = "false",
    attestation_text: Annotated[str, Form()] = "",
    notes: Annotated[str, Form()] = "",
    report: Annotated[UploadFile | None, File()] = None,
) -> dict[str, Any]:
    checked = attestation_checked.strip().lower() in {"1", "true", "yes", "on"}
    data = b""
    filename = ""
    content_type = "application/pdf"
    if report is not None and report.filename:
        raw = await report.read()
        if len(raw) > 15 * 1024 * 1024:
            raise ProblemError(
                413, "report_too_large", "File too large", "Report must be ≤ 15 MB."
            )
        data = raw
        filename = report.filename
        content_type = report.content_type or "application/pdf"
        allowed = {
            "application/pdf",
            "application/json",
            "text/plain",
            "text/markdown",
            "application/octet-stream",
        }
        if content_type not in allowed and not filename.lower().endswith(
            (".pdf", ".json", ".md", ".txt")
        ):
            raise ProblemError(
                415,
                "unsupported_report_type",
                "Unsupported file",
                "Upload PDF, JSON, Markdown, or plain text.",
            )
    row = await compliance.upload_and_attest(
        session,
        services.storage,
        kind=kind,
        status=status,
        approver_name=approver_name,
        approver_role=approver_role,
        attestation_checked=checked,
        attestation_text=attestation_text
        or (
            "I attest this report covers the deployed product version and is on file."
            if kind == compliance.CLINICAL
            else "I attest the DPDP / subprocessor review findings in the uploaded report."
        ),
        notes=notes or None,
        filename=filename or "report.pdf",
        content_type=content_type,
        data=data,
        actor=context.subject,
        actor_role=context.primary_role.value,
        trace_id=getattr(request.state, "trace_id", None),
    )
    await session.commit()
    return compliance.attestation_public(row, kind=kind)


@router.get("/governance")
async def get_governance_settings(
    context: AdminOnly,
    session: SessionDep,
) -> dict[str, Any]:
    return {"settings": await compliance.get_governance(session)}


@router.patch("/governance")
async def patch_governance_settings(
    body: GovernancePatch,
    request: Request,
    context: AdminOnly,
    session: SessionDep,
    services: ServicesDep,
) -> dict[str, Any]:
    if body.external_egress_enabled is True:
        pii = await PiiGate(services.settings).health()
        dpdp = await compliance.get_attestation(session, compliance.DPDP)
        if not pii.get("composite_ready"):
            raise ProblemError(
                409,
                "egress_requires_composite_pii",
                "Cannot enable egress",
                "Composite PII engine must be healthy before enabling egress.",
            )
        if dpdp is None or dpdp.status != "attested":
            raise ProblemError(
                409,
                "egress_requires_dpdp",
                "Cannot enable egress",
                "DPDP audit must be attested before enabling egress.",
            )
        if not services.settings.external_egress_enabled:
            raise ProblemError(
                409,
                "egress_env_disabled",
                "Cannot enable egress",
                "EXTERNAL_EGRESS_ENABLED is false in the environment; "
                "flip env after security sign-off.",
            )
    updates = body.model_dump(exclude_none=True)
    for key, value in updates.items():
        await compliance.set_governance(
            session, key=key, value=value, updated_by=context.subject
        )
    AuditRepository(session).append(
        actor_subject=context.subject,
        actor_role=context.primary_role.value,
        action="admin.governance_updated",
        resource_type="governance_settings",
        trace_id=getattr(request.state, "trace_id", None),
        metadata={"keys": sorted(updates)},
    )
    await session.commit()
    return {"settings": await compliance.get_governance(session)}


@router.get("/notification-deliveries")
async def notification_deliveries(
    context: AdminOnly,
    session: SessionDep,
    status: Annotated[str | None, Query(max_length=20)] = None,
    channel: Annotated[str | None, Query(max_length=20)] = None,
    q: Annotated[str | None, Query(max_length=120)] = None,
    page: Annotated[int, Query(ge=1)] = 1,
    page_size: Annotated[int, Query(ge=1, le=100)] = 20,
) -> dict[str, Any]:
    conditions = []
    if status:
        conditions.append(NotificationDelivery.status == status)
    if channel:
        conditions.append(NotificationDelivery.channel == channel)
    if q:
        pattern = f"%{q.strip()}%"
        conditions.append(
            or_(
                Notification.title.ilike(pattern),
                Notification.recipient_subject.ilike(pattern),
                Notification.template_id.ilike(pattern),
            )
        )
    joined = NotificationDelivery.__table__.join(
        Notification, Notification.id == NotificationDelivery.notification_id
    )
    total = int(
        await session.scalar(select(func.count()).select_from(joined).where(*conditions)) or 0
    )
    rows = (
        await session.execute(
            select(NotificationDelivery, Notification)
            .join(Notification, Notification.id == NotificationDelivery.notification_id)
            .where(*conditions)
            .order_by(NotificationDelivery.created_at.desc())
            .limit(page_size)
            .offset((page - 1) * page_size)
        )
    ).all()
    return {
        "items": [
            {
                "id": str(delivery.id),
                "notification_id": str(notification.id),
                "status": delivery.status,
                "channel": delivery.channel,
                "attempts": delivery.attempts,
                "last_error": delivery.last_error_code,
                "recipient_subject": notification.recipient_subject,
                "template_id": notification.template_id,
                "title": notification.title,
                "scheduled_at": delivery.scheduled_at.isoformat(),
                "sent_at": delivery.sent_at.isoformat() if delivery.sent_at else None,
            }
            for delivery, notification in rows
        ],
        "meta": GridMeta(
            total=total,
            page=page,
            page_size=page_size,
            sort="created_at",
            order="desc",
            pages=math.ceil(total / page_size) if total else 0,
        ),
    }
