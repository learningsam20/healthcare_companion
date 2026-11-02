"""Compliance attestation + governance settings helpers."""

from __future__ import annotations

import datetime as dt
import hashlib
import uuid
from typing import Any

from sahyog_common.errors import ProblemError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.storage import DocumentStorage, StorageError
from app.repositories.audit import AuditRepository
from app.repositories.models import ComplianceAttestation, GovernanceSetting

CLINICAL = "clinical_validation"
DPDP = "dpdp_audit"

DEFAULT_GOVERNANCE: dict[str, Any] = {
    "finops_history_days": 90,
    "judge_require_attested_human": True,
    "judge_min_kappa": 0.6,
    "chat_retention_days": 365,
    "memory_retention_days": 180,
    "external_egress_enabled": False,
    # Enforce=true requires status=attested; demo default false (only disapproved stops).
    "dpdp_enforce": False,
}


def _problem(status: int, code: str, title: str, detail: str) -> ProblemError:
    return ProblemError(status, code, title, detail)


async def get_attestation(session: AsyncSession, kind: str) -> ComplianceAttestation | None:
    result = await session.execute(
        select(ComplianceAttestation).where(ComplianceAttestation.kind == kind)
    )
    return result.scalar_one_or_none()


async def ensure_attestation(session: AsyncSession, kind: str) -> ComplianceAttestation:
    row = await get_attestation(session, kind)
    if row is not None:
        return row
    row = ComplianceAttestation(id=uuid.uuid4(), kind=kind, status="not_attested")
    session.add(row)
    await session.flush()
    return row


def attestation_public(row: ComplianceAttestation | None, *, kind: str) -> dict[str, Any]:
    if row is None:
        return {
            "kind": kind,
            "status": "not_attested",
            "approver_name": None,
            "approver_role": None,
            "attested_at": None,
            "has_report": False,
            "report_filename": None,
            "notes": None,
            "claim": "not_a_validated_medical_device"
            if kind == CLINICAL
            else "dpdp_review_incomplete",
        }
    return {
        "kind": row.kind,
        "status": row.status,
        "approver_name": row.approver_name,
        "approver_role": row.approver_role,
        "attested_at": row.attested_at.isoformat() if row.attested_at else None,
        "has_report": bool(row.report_object_key),
        "report_filename": row.report_filename,
        "report_sha256": row.report_sha256,
        "notes": row.notes,
        "claim": (
            "attested_report_on_file_not_regulatory_clearance"
            if row.status == "attested" and kind == CLINICAL
            else (
                "dpdp_approved"
                if row.status == "attested" and kind == DPDP
                else (
                    "dpdp_disapproved_processing_stopped"
                    if row.status == "disapproved" and kind == DPDP
                    else (
                        "not_a_validated_medical_device"
                        if kind == CLINICAL
                        else "dpdp_review_incomplete"
                    )
                )
            )
        ),
    }


async def get_governance(session: AsyncSession) -> dict[str, Any]:
    merged = dict(DEFAULT_GOVERNANCE)
    result = await session.execute(select(GovernanceSetting))
    for row in result.scalars().all():
        if isinstance(row.value, dict):
            merged[row.key] = row.value.get("value", row.value)
    return merged


async def set_governance(
    session: AsyncSession,
    *,
    key: str,
    value: Any,
    updated_by: str,
) -> dict[str, Any]:
    if key not in DEFAULT_GOVERNANCE:
        raise _problem(400, "unknown_governance_key", "Unknown key", f"No such key: {key}")
    result = await session.execute(select(GovernanceSetting).where(GovernanceSetting.key == key))
    row = result.scalar_one_or_none()
    payload = {"value": value}
    if row is None:
        row = GovernanceSetting(key=key, value=payload, updated_by=updated_by)
        session.add(row)
    else:
        row.value = payload
        row.updated_by = updated_by
    await session.flush()
    return await get_governance(session)


async def upload_and_attest(
    session: AsyncSession,
    storage: DocumentStorage,
    *,
    kind: str,
    status: str,
    approver_name: str,
    approver_role: str,
    attestation_checked: bool,
    attestation_text: str,
    notes: str | None,
    filename: str,
    content_type: str,
    data: bytes,
    actor: str,
    actor_role: str,
    trace_id: str | None,
) -> ComplianceAttestation:
    if kind not in {CLINICAL, DPDP}:
        raise _problem(400, "invalid_kind", "Invalid kind", "Unsupported attestation kind.")
    if status not in {"attested", "disapproved", "pending", "revoked", "not_attested"}:
        raise _problem(400, "invalid_status", "Invalid status", "Unsupported status.")
    if status == "attested":
        if not attestation_checked:
            raise _problem(
                400,
                "attestation_required",
                "Checkbox required",
                "Approver must tick the attestation checkbox for status=attested.",
            )
        if not approver_name.strip() or not data:
            raise _problem(
                400,
                "report_and_approver_required",
                "Incomplete attestation",
                "Attested status requires approver name and an uploaded report.",
            )
    if status == "disapproved" and kind != DPDP:
        raise _problem(
            400,
            "disapproved_dpdp_only",
            "Invalid status",
            "disapproved is only valid for dpdp_audit.",
        )

    row = await ensure_attestation(session, kind)
    if data:
        digest = hashlib.sha256(data).hexdigest()
        key = f"compliance/{kind}/{uuid.uuid4().hex}_{filename[-80:]}"
        try:
            await storage.put(key=key, data=data, content_type=content_type or "application/pdf")
        except StorageError as exc:
            raise _problem(
                503, "storage_unavailable", "Storage unavailable", "Could not store report."
            ) from exc
        row.report_object_key = key
        row.report_sha256 = digest
        row.report_filename = filename[:260]
        row.report_content_type = (content_type or "application/pdf")[:120]

    row.status = status
    row.approver_name = approver_name.strip() or None
    row.approver_role = approver_role.strip() or None
    row.attestation_text = attestation_text.strip() or None
    row.notes = (notes or "").strip() or None
    row.updated_by = actor
    row.attested_at = (
        dt.datetime.now(dt.UTC) if status in {"attested", "disapproved"} else row.attested_at
    )
    await session.flush()

    AuditRepository(session).append(
        actor_subject=actor,
        actor_role=actor_role,
        action=f"compliance.{kind}.{status}",
        resource_type="compliance_attestation",
        resource_id=str(row.id),
        patient_id=None,
        consent_id=None,
        trace_id=trace_id,
        metadata={
            "status": status,
            "approver_name": row.approver_name,
            "has_report": bool(row.report_object_key),
            "report_sha256": row.report_sha256,
        },
    )
    return row


async def dpdp_blocks_processing(session: AsyncSession) -> bool:
    """True when patient-linked processing must stop (G-19).

    - Always block when status is ``disapproved``.
    - When ``dpdp_enforce`` is true, also block unless status is ``attested``.
    """
    gov = await get_governance(session)
    enforce = bool(gov.get("dpdp_enforce", False))
    row = await get_attestation(session, DPDP)
    if row is not None and row.status == "disapproved":
        return True
    if not enforce:
        return False
    return row is None or row.status != "attested"
