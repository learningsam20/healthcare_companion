from __future__ import annotations

import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient
from sahyog_common.errors import ProblemError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import Settings, get_settings
from app.core.db import get_session
from app.repositories.consents import ConsentRepository

ROLE_PRECEDENCE = (
    "admin",
    "compliance",
    "doctor",
    "front_desk",
    "pharmacist",
    "caregiver",
    "patient",
    "service",
)


class Role(StrEnum):
    PATIENT = "patient"
    CAREGIVER = "caregiver"
    DOCTOR = "doctor"
    FRONT_DESK = "front_desk"
    PHARMACIST = "pharmacist"
    COMPLIANCE = "compliance"
    ADMIN = "admin"
    SERVICE = "service"


@dataclass(frozen=True, slots=True)
class AuthContext:
    subject: str
    roles: tuple[str, ...]
    primary_role: Role
    patient_id: uuid.UUID | None
    clinic_ids: tuple[str, ...]
    locale: str
    traffic_class: str
    token_id: str | None
    consent_id: uuid.UUID | None = None
    preferred_username: str | None = None
    display_name: str | None = None
    doctor_display_name: str | None = None


def _claim_str(claims: dict[str, Any], *keys: str) -> str | None:
    for key in keys:
        value = claims.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
        if isinstance(value, list) and value:
            first = value[0]
            if isinstance(first, str) and first.strip():
                return first.strip()
    return None


def doctor_schedule_name(context: AuthContext) -> str | None:
    """Canonical doctor_name used on appointments for the signed-in doctor."""
    if context.primary_role is not Role.DOCTOR:
        return None
    if context.doctor_display_name:
        return context.doctor_display_name
    if context.display_name:
        name = context.display_name
        return name if name.lower().startswith("dr") else f"Dr. {name}"
    return None


_bearer = HTTPBearer(auto_error=False)
_jwks_clients: dict[str, PyJWKClient] = {}


def _jwks(settings: Settings) -> PyJWKClient:
    url = settings.keycloak_jwks_url
    client = _jwks_clients.get(url)
    if client is None:
        client = PyJWKClient(
            url, cache_keys=True, lifespan=300, timeout=settings.keycloak_jwks_timeout_seconds
        )
        _jwks_clients[url] = client
    return client


def _roles_from_claims(claims: dict[str, Any], client_id: str) -> tuple[str, ...]:
    roles: set[str] = set(claims.get("realm_access", {}).get("roles", []))
    resource = claims.get("resource_access", {}).get(client_id, {})
    roles.update(resource.get("roles", []))
    return tuple(role for role in ROLE_PRECEDENCE if role in roles)


def verify_token(token: str, settings: Settings) -> AuthContext:
    try:
        signing_key = _jwks(settings).get_signing_key_from_jwt(token)
        claims = jwt.decode(
            token,
            signing_key.key,
            algorithms=["RS256"],
            audience=settings.keycloak_audience,
            issuer=settings.keycloak_issuer,
            options={"require": ["exp", "iat", "sub", "iss", "aud"]},
        )
    except jwt.PyJWKClientError as exc:
        raise ProblemError(
            status=503,
            code="identity_unavailable",
            title="Identity provider unavailable",
            detail="Sign-in keys could not be fetched. Try again shortly.",
        ) from exc
    except jwt.ExpiredSignatureError as exc:
        raise ProblemError(401, "token_expired", "Session expired", "Sign in again.") from exc
    except jwt.InvalidTokenError as exc:
        raise ProblemError(
            401, "token_invalid", "Authentication failed", "The access token is invalid."
        ) from exc

    roles = _roles_from_claims(claims, settings.keycloak_client_id)
    if not roles:
        raise ProblemError(
            403,
            "role_missing",
            "Access denied",
            "The account has no role in this application.",
        )
    primary = Role(next(role for role in ROLE_PRECEDENCE if role in roles))
    patient_raw = claims.get("patient_id")
    patient_id: uuid.UUID | None = None
    if isinstance(patient_raw, str):
        try:
            patient_id = uuid.UUID(patient_raw)
        except ValueError:
            patient_id = None
    clinics = tuple(str(item) for item in claims.get("clinic_ids", []) if item)
    locale = (
        claims.get("locale") if claims.get("locale") in {"en-IN", "hi-IN", "mr-IN"} else "en-IN"
    )
    traffic = claims.get("traffic_class")
    traffic_class = traffic if traffic in {"real", "synthetic"} else "real"
    preferred_username = _claim_str(claims, "preferred_username")
    given = _claim_str(claims, "given_name")
    family = _claim_str(claims, "family_name")
    display_name = _claim_str(claims, "name") or (
        " ".join(part for part in (given, family) if part) or None
    )
    doctor_display_name = _claim_str(claims, "doctor_display_name")
    if primary is Role.DOCTOR and not doctor_display_name and display_name:
        doctor_display_name = (
            display_name if display_name.lower().startswith("dr") else f"Dr. {display_name}"
        )
    return AuthContext(
        subject=str(claims["sub"]),
        roles=roles,
        primary_role=primary,
        patient_id=patient_id,
        clinic_ids=clinics,
        locale=str(locale),
        traffic_class=str(traffic_class),
        token_id=claims.get("jti"),
        preferred_username=preferred_username,
        display_name=display_name,
        doctor_display_name=doctor_display_name,
    )


async def get_auth_context(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[Settings, Depends(get_settings)],
    session: Annotated[AsyncSession, Depends(get_session)],
    consent_header: Annotated[str | None, Header(alias="X-Consent-Id")] = None,
) -> AuthContext:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise ProblemError(
            401,
            "authentication_required",
            "Authentication required",
            "Provide a Keycloak access token.",
        )
    context = verify_token(credentials.credentials, settings)
    request.state.traffic_class = context.traffic_class
    if consent_header:
        if context.primary_role is not Role.CAREGIVER:
            raise ProblemError(
                403,
                "context_forbidden",
                "Access denied",
                "A patient context can only be selected by a caregiver account.",
            )
        try:
            consent_id = uuid.UUID(consent_header)
        except ValueError as exc:
            raise ProblemError(
                400, "context_invalid", "Invalid context", "The selected context is not valid."
            ) from exc
        consent = await ConsentRepository(session).active_for_subject(
            consent_id=consent_id, caregiver_subject=context.subject
        )
        if consent is None:
            raise ProblemError(
                403,
                "consent_required",
                "Consent required",
                "The selected consent is not active. Ask the patient to share their record.",
            )
        context = replace(context, patient_id=consent.patient_id, consent_id=consent.id)
        request.state.consent_id = str(consent.id)
    elif context.primary_role is Role.CAREGIVER and context.patient_id is not None:
        consent = await ConsentRepository(session).latest_active_for_patient(
            caregiver_subject=context.subject, patient_id=context.patient_id
        )
        if consent is not None:
            context = replace(context, consent_id=consent.id)
            request.state.consent_id = str(consent.id)
    return context


def require_roles(*allowed: Role) -> Callable[[AuthContext], Awaitable[AuthContext]]:
    allowed_set = {role.value for role in allowed}

    async def _dependency(
        context: Annotated[AuthContext, Depends(get_auth_context)],
    ) -> AuthContext:
        if not allowed_set.intersection(context.roles):
            raise ProblemError(
                403,
                "forbidden",
                "Access denied",
                "This action is not permitted for your role.",
            )
        return context

    return _dependency


def staff_or_admin(context: AuthContext) -> bool:
    return bool({"doctor", "front_desk", "pharmacist", "compliance", "admin"} & set(context.roles))
