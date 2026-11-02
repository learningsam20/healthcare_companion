from __future__ import annotations

import datetime as dt
import uuid
from collections.abc import AsyncIterator

import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import register_exception_handlers
from app.core.security import AuthContext, Role, get_auth_context
from app.modules.consents.router import router as consents_router
from app.repositories.audit import AuditRepository
from app.repositories.consents import ConsentRepository
from app.repositories.models import AuditEvent, Consent, Patient
from app.repositories.patients import PatientRepository
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.pool import NullPool

pytestmark = pytest.mark.integration


@pytest.fixture
async def session() -> AsyncIterator[AsyncSession]:
    engine = create_async_engine(Settings().database_url, poolclass=NullPool)
    async with engine.connect() as connection:
        outer = await connection.begin()
        db = AsyncSession(
            bind=connection,
            join_transaction_mode="create_savepoint",
            expire_on_commit=False,
        )
        try:
            yield db
        finally:
            await db.close()
            await outer.rollback()
    await engine.dispose()


def _context(role: Role, *, subject: str, patient_id: uuid.UUID | None = None) -> AuthContext:
    return AuthContext(
        subject=subject,
        roles=(role.value,),
        primary_role=role,
        patient_id=patient_id,
        clinic_ids=(),
        locale="en-IN",
        traffic_class="synthetic",
        token_id=None,
    )


async def _patient(session: AsyncSession) -> Patient:
    patient = Patient(display_name=f"Consent Test {uuid.uuid4().hex[:8]}", locale="en-IN")
    session.add(patient)
    await session.flush()
    return patient


async def _consent(
    session: AsyncSession,
    *,
    patient_id: uuid.UUID,
    caregiver: str,
    scopes: list[str] | None = None,
    expires_at: dt.datetime | None = None,
    status: str = "active",
) -> Consent:
    consent = Consent(
        patient_id=patient_id,
        grantor_subject="patient-subject",
        caregiver_subject=caregiver,
        scopes=scopes or ["chat", "records"],
        purpose="care",
        status=status,
        granted_at=dt.datetime.now(dt.UTC),
        expires_at=expires_at,
    )
    return await ConsentRepository(session).create(consent)


def _client(session: AsyncSession, context: AuthContext) -> AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(consents_router)
    app.dependency_overrides[get_auth_context] = lambda: context

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session_override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_revoked_consent_denies_access(session: AsyncSession) -> None:
    patient = await _patient(session)
    consent = await _consent(session, patient_id=patient.id, caregiver="caregiver-revoke")
    repo = ConsentRepository(session)
    patients = PatientRepository(session)
    assert await patients.active_consent(
        caregiver_subject="caregiver-revoke", patient_id=patient.id, scope="chat"
    )

    await repo.revoke(consent)

    assert consent.status == "revoked"
    assert consent.revoked_at is not None
    assert not await patients.active_consent(
        caregiver_subject="caregiver-revoke", patient_id=patient.id, scope="chat"
    )
    assert (
        await repo.active_for_pair(patient_id=patient.id, caregiver_subject="caregiver-revoke")
        is None
    )


async def test_expired_consent_denies_access(session: AsyncSession) -> None:
    patient = await _patient(session)
    await _consent(
        session,
        patient_id=patient.id,
        caregiver="caregiver-expired",
        expires_at=dt.datetime.now(dt.UTC) - dt.timedelta(minutes=1),
    )
    assert not await PatientRepository(session).active_consent(
        caregiver_subject="caregiver-expired", patient_id=patient.id, scope="records"
    )


async def test_selected_consent_scope_is_authoritative(session: AsyncSession) -> None:
    patient = await _patient(session)
    chat_only = await _consent(
        session, patient_id=patient.id, caregiver="caregiver-scoped", scopes=["chat"]
    )
    records_consent = await _consent(
        session, patient_id=patient.id, caregiver="caregiver-scoped", scopes=["records"]
    )
    patients = PatientRepository(session)

    assert await patients.active_consent(
        caregiver_subject="caregiver-scoped",
        patient_id=patient.id,
        scope="records",
        consent_id=records_consent.id,
    )
    assert not await patients.active_consent(
        caregiver_subject="caregiver-scoped",
        patient_id=patient.id,
        scope="records",
        consent_id=chat_only.id,
    )
    assert not await patients.active_consent(
        caregiver_subject="caregiver-scoped",
        patient_id=patient.id,
        scope="chat",
        consent_id=records_consent.id,
    )


async def test_audit_event_records_consent_id(session: AsyncSession) -> None:
    patient = await _patient(session)
    consent = await _consent(session, patient_id=patient.id, caregiver="caregiver-audit")
    event = AuditRepository(session).append(
        actor_subject="caregiver-audit",
        actor_role="caregiver",
        action="records.documents_listed",
        resource_type="document",
        patient_id=patient.id,
        consent_id=consent.id,
        metadata={"count": 0},
    )
    await session.flush()
    stored = await session.scalar(select(AuditEvent).where(AuditEvent.id == event.id))
    assert stored is not None
    assert stored.consent_id == consent.id
    assert stored.patient_id == patient.id


async def test_patient_can_grant_and_revoke_consent(session: AsyncSession) -> None:
    patient = await _patient(session)
    context = _context(Role.PATIENT, subject="patient-subject", patient_id=patient.id)
    async with _client(session, context) as client:
        granted = await client.post(
            "/api/v1/consents",
            json={"caregiver_subject": "caregiver-flow", "scopes": ["chat", "records"]},
        )
        assert granted.status_code == 201, granted.text
        payload = granted.json()
        assert payload["patient_id"] == str(patient.id)
        assert payload["status"] == "active"
        assert payload["grantor_subject"] == "patient-subject"

        duplicate = await client.post(
            "/api/v1/consents",
            json={"caregiver_subject": "caregiver-flow", "scopes": ["chat"]},
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["code"] == "consent_exists"

        revoked = await client.post(f"/api/v1/consents/{payload['id']}/revoke")
        assert revoked.status_code == 200, revoked.text
        assert revoked.json()["status"] == "revoked"

        again = await client.post(f"/api/v1/consents/{payload['id']}/revoke")
        assert again.status_code == 200
        assert again.json()["status"] == "revoked"


async def test_patient_cannot_share_another_record(session: AsyncSession) -> None:
    own = await _patient(session)
    other = await _patient(session)
    context = _context(Role.PATIENT, subject="patient-subject", patient_id=own.id)
    async with _client(session, context) as client:
        response = await client.post(
            "/api/v1/consents",
            json={"caregiver_subject": "caregiver-cross", "patient_id": str(other.id)},
        )
    assert response.status_code == 403


async def test_caregiver_cannot_grant_consent(session: AsyncSession) -> None:
    patient = await _patient(session)
    context = _context(Role.CAREGIVER, subject="caregiver-grant", patient_id=patient.id)
    async with _client(session, context) as client:
        response = await client.post(
            "/api/v1/consents", json={"caregiver_subject": "caregiver-other"}
        )
    assert response.status_code == 403


async def test_caregiver_context_list_hides_revoked_consent(session: AsyncSession) -> None:
    patient = await _patient(session)
    consent = await _consent(
        session, patient_id=patient.id, caregiver="caregiver-context", scopes=["chat"]
    )
    context = _context(Role.CAREGIVER, subject="caregiver-context")
    async with _client(session, context) as client:
        active = await client.get("/api/v1/me/contexts")
        assert active.status_code == 200
        assert [row["consent_id"] for row in active.json()] == [str(consent.id)]

        activated = await client.post(f"/api/v1/me/contexts/{consent.id}/activate")
        assert activated.status_code == 200
        assert activated.json()["patient_id"] == str(patient.id)

        await ConsentRepository(session).revoke(consent)
        await session.flush()

        assert (await client.get("/api/v1/me/contexts")).json() == []
        blocked = await client.post(f"/api/v1/me/contexts/{consent.id}/activate")
    assert blocked.status_code == 403
    assert blocked.json()["code"] == "consent_required"
