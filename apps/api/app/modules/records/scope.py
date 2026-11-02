from __future__ import annotations

import uuid

from app.core.security import AuthContext, Role
from app.repositories.patients import PatientRepository
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession


async def resolve_patient(
    context: AuthContext,
    session: AsyncSession,
    requested: uuid.UUID | None,
    *,
    scope: str = "records",
    allow_all_for_admin: bool = False,
) -> uuid.UUID | None:
    role = context.primary_role
    if role is Role.PATIENT:
        if context.patient_id is None:
            raise ProblemError(
                409,
                "account_not_linked",
                "Account not linked",
                "This account is not linked to a patient record. Contact the clinic.",
            )
        if requested is not None and requested != context.patient_id:
            raise ProblemError(
                403, "forbidden", "Access denied", "You can only access your own records."
            )
        if not await PatientRepository(session).exists(context.patient_id):
            raise ProblemError(
                403,
                "account_deleted",
                "Account deletion requested",
                "This record is pending deletion and cannot be used for this request.",
            )
        return context.patient_id
    if role is Role.CAREGIVER:
        if context.patient_id is None:
            raise ProblemError(
                403,
                "consent_required",
                "Consent required",
                "No patient is linked to this caregiver account.",
            )
        if requested is not None and requested != context.patient_id:
            raise ProblemError(
                403, "forbidden", "Access denied", "You can only access the linked patient."
            )
        allowed = await PatientRepository(session).active_consent(
            caregiver_subject=context.subject,
            patient_id=context.patient_id,
            scope=scope,
            consent_id=context.consent_id,
        )
        if not allowed:
            raise ProblemError(
                403,
                "consent_required",
                "Consent required",
                "The patient has not granted active record consent to this caregiver.",
            )
        return context.patient_id
    if requested is None:
        if allow_all_for_admin and role in {Role.ADMIN, Role.COMPLIANCE}:
            return None
        raise ProblemError(
            400,
            "patient_required",
            "Patient required",
            "Select a patient before opening records.",
        )
    if not await PatientRepository(session).exists(requested):
        raise ProblemError(404, "patient_not_found", "Not found", "No such patient.")
    return requested
