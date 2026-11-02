from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from types import SimpleNamespace
from typing import Any, cast

import pytest
from app.core.config import Settings
from app.core.db import get_session
from app.core.errors import register_exception_handlers
from app.core.security import AuthContext, Role, get_auth_context
from app.core.services import get_services
from app.modules.privacy.router import router as privacy_router
from app.modules.records.router import router as records_router
from app.repositories.models import (
    AuditEvent,
    ChatMessage,
    ChatSession,
    Consent,
    Document,
    DocumentChunk,
    Patient,
)
from app.worker import _purge_patient
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
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


def _services(*, s3: bool = False) -> Any:
    async def presign_get(*, key: str, expires_seconds: int = 300) -> str:
        return f"https://storage.test/{key}?expires={expires_seconds}"

    return cast(
        Any,
        SimpleNamespace(
            settings=SimpleNamespace(s3_configured=s3, s3_bucket_audio="audio"),
            storage=SimpleNamespace(delete=None, presign_get=presign_get),
            app_config={"retention": {"deletion_grace_days": 30}},
        ),
    )


def _client(session: AsyncSession, context: AuthContext, services: Any) -> AsyncClient:
    app = FastAPI()
    register_exception_handlers(app)
    app.include_router(privacy_router)
    app.include_router(records_router)
    app.dependency_overrides[get_auth_context] = lambda: context
    app.dependency_overrides[get_services] = lambda: services

    async def _session_override() -> AsyncIterator[AsyncSession]:
        yield session

    app.dependency_overrides[get_session] = _session_override
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _patient(session: AsyncSession) -> Patient:
    patient = Patient(display_name=f"Privacy Test {uuid.uuid4().hex[:8]}", locale="en-IN")
    session.add(patient)
    await session.flush()
    return patient


async def _document(session: AsyncSession, patient: Patient) -> Document:
    document = Document(
        patient_id=patient.id,
        uploaded_by_subject="patient-subject",
        kind="lab_report",
        title="Blood panel",
        object_key="",
        content_type="application/pdf",
        size_bytes=120,
        checksum_sha256="0" * 64,
        language="en-IN",
        status="indexed",
        scan_status="clean",
        traffic_class="synthetic",
    )
    session.add(document)
    await session.flush()
    session.add(
        DocumentChunk(
            document_id=document.id,
            patient_id=patient.id,
            chunk_index=0,
            page=1,
            content="Haemoglobin 13.2 g/dL",
            embedding=[0.0] * 1024,
        )
    )
    await session.flush()
    return document


async def _chat_citation(
    session: AsyncSession, patient: Patient, document: Document
) -> ChatMessage:
    chat = ChatSession(
        owner_subject="patient-subject",
        owner_role="patient",
        patient_id=patient.id,
        title="Question about results",
        status="active",
        traffic_class="synthetic",
    )
    session.add(chat)
    await session.flush()
    message = ChatMessage(
        session_id=chat.id,
        role="assistant",
        content="Your haemoglobin was 13.2 g/dL.",
        language="en-IN",
        sources=[
            {
                "id": str(uuid.uuid4()),
                "type": "document",
                "title": document.title,
                "metadata": {"document_id": str(document.id)},
            }
        ],
    )
    session.add(message)
    await session.flush()
    return message


async def test_patient_deletes_document_and_derived_artifacts(session: AsyncSession) -> None:
    patient = await _patient(session)
    document = await _document(session, patient)
    message = await _chat_citation(session, patient, document)
    context = _context(Role.PATIENT, subject="patient-subject", patient_id=patient.id)
    async with _client(session, context, _services()) as client:
        response = await client.delete(f"/api/v1/records/documents/{document.id}")
    assert response.status_code == 204, response.text

    assert await session.get(Document, document.id) is None
    remaining = await session.scalar(
        select(func.count())
        .select_from(DocumentChunk)
        .where(DocumentChunk.document_id == document.id)
    )
    assert remaining == 0
    await session.refresh(message)
    assert message.sources == []
    event = await session.scalar(
        select(AuditEvent).where(AuditEvent.action == "records.document_deleted")
    )
    assert event is not None
    assert event.patient_id == patient.id
    assert event.event_metadata["chunks_deleted"] == 1
    assert event.event_metadata["citations_scrubbed"]["chat_messages"] == 1


async def test_patient_downloads_original_via_presigned_url(session: AsyncSession) -> None:
    patient = await _patient(session)
    document = await _document(session, patient)
    document.object_key = "documents/test/blood-panel.pdf"
    await session.flush()
    context = _context(Role.PATIENT, subject="patient-subject", patient_id=patient.id)
    async with _client(session, context, _services(s3=True)) as client:
        response = await client.get(f"/api/v1/records/documents/{document.id}/download")
        assert response.status_code == 200, response.text
        payload = response.json()
        assert payload["url"].startswith("https://storage.test/documents/test/blood-panel.pdf")
        assert payload["expires_in"] == 300

    event = await session.scalar(
        select(AuditEvent)
        .where(AuditEvent.action == "records.document_downloaded")
        .order_by(AuditEvent.created_at.desc())
        .limit(1)
    )
    assert event is not None
    assert event.resource_id == str(document.id)

    async with _client(session, context, _services()) as client:
        unavailable = await client.get(f"/api/v1/records/documents/{document.id}/download")
    assert unavailable.status_code == 503
    assert unavailable.json()["code"] == "storage_unavailable"


async def test_patient_cannot_delete_another_patients_document(session: AsyncSession) -> None:
    own = await _patient(session)
    other = await _patient(session)
    document = await _document(session, other)
    context = _context(Role.PATIENT, subject="patient-subject", patient_id=own.id)
    async with _client(session, context, _services()) as client:
        response = await client.delete(f"/api/v1/records/documents/{document.id}")
    assert response.status_code == 403
    assert await session.get(Document, document.id) is not None


async def test_export_returns_metadata_and_audit_event(session: AsyncSession) -> None:
    patient = await _patient(session)
    await _document(session, patient)
    context = _context(Role.PATIENT, subject="patient-subject", patient_id=patient.id)
    async with _client(session, context, _services()) as client:
        response = await client.get("/api/v1/me/export")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["patient"]["id"] == str(patient.id)
    assert [row["title"] for row in body["documents"]] == ["Blood panel"]
    assert "object_key" not in body["documents"][0]
    assert body["scope"]["format"] == "metadata_only"
    assert "attachment" in response.headers["content-disposition"]
    event = await session.scalar(
        select(AuditEvent).where(AuditEvent.action == "privacy.export_downloaded")
    )
    assert event is not None


async def test_deletion_request_soft_deletes_and_cancels(session: AsyncSession) -> None:
    patient = await _patient(session)
    consent = Consent(
        patient_id=patient.id,
        grantor_subject="patient-subject",
        caregiver_subject="caregiver-privacy",
        scopes=["records"],
        purpose="care",
        status="active",
    )
    session.add(consent)
    await session.flush()
    context = _context(Role.PATIENT, subject="patient-subject", patient_id=patient.id)
    async with _client(session, context, _services()) as client:
        created = await client.post(
            "/api/v1/me/deletion-request", json={"reason": "no longer needed"}
        )
        assert created.status_code == 201, created.text
        payload = created.json()
        assert payload["status"] == "pending"

        duplicate = await client.post("/api/v1/me/deletion-request", json={})
        assert duplicate.status_code == 409

        await session.refresh(patient)
        assert patient.deleted_at is not None
        await session.refresh(consent)
        assert consent.status == "revoked"

        current = await client.get("/api/v1/me/deletion-request")
        assert current.status_code == 200
        assert current.json()["request"]["id"] == payload["id"]

        cancelled = await client.delete("/api/v1/me/deletion-request")
        assert cancelled.status_code == 204
        await session.refresh(patient)
        assert patient.deleted_at is None


async def test_purge_removes_patient_rows(session: AsyncSession) -> None:
    patient = await _patient(session)
    document = await _document(session, patient)
    await _chat_citation(session, patient, document)
    session.add(
        Consent(
            patient_id=patient.id,
            grantor_subject="patient-subject",
            caregiver_subject="caregiver-purge",
            scopes=["records"],
            purpose="care",
            status="active",
        )
    )
    await session.flush()
    patient_id = patient.id

    counts = await _purge_patient(_services(), session, patient_id)
    await session.flush()
    session.expunge_all()

    assert await session.get(Patient, patient_id) is None
    assert await session.get(Document, document.id) is None
    assert counts["patients"] == 1
    assert counts["chat_sessions"] >= 1


async def test_purge_refuses_when_object_storage_is_unconfigured(session: AsyncSession) -> None:
    patient = await _patient(session)
    document = await _document(session, patient)
    document.object_key = "documents/test/orphan"
    await session.flush()

    with pytest.raises(RuntimeError, match="object storage is not configured"):
        await _purge_patient(_services(), session, patient.id)
    assert await session.get(Patient, patient.id) is not None
