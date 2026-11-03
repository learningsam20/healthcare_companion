from __future__ import annotations

import datetime as dt
import uuid
from typing import Any

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    MetaData,
    String,
    Text,
    UniqueConstraint,
    Uuid,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


class Patient(Base):
    __tablename__ = "patients"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    keycloak_subject: Mapped[str | None] = mapped_column(String(200), unique=True, nullable=True)
    display_name: Mapped[str | None] = mapped_column(String(120), nullable=True)
    locale: Mapped[str] = mapped_column(String(10), default="en-IN")
    notify_email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    slack_user_id: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class FhirPatientLink(Base):
    """Maps an internal patient to a FHIR Patient id. Resources are not stored wholesale."""

    __tablename__ = "fhir_patient_links"
    __table_args__ = (Index("ix_fhir_patient_links_fhir_id", "fhir_patient_id"),)

    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), primary_key=True
    )
    fhir_patient_id: Mapped[str] = mapped_column(String(120), nullable=False)
    system: Mapped[str] = mapped_column(String(200), default="fhir", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class PatientExternalId(Base):
    __tablename__ = "patient_external_ids"
    __table_args__ = (
        CheckConstraint("status IN ('linked','unlinked','pending')", name="status"),
        UniqueConstraint("patient_id", "system", name="uq_patient_external_ids_patient_system"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    system: Mapped[str] = mapped_column(String(40), nullable=False)
    value_enc: Mapped[str] = mapped_column(String(96), nullable=False)
    purpose: Mapped[str] = mapped_column(String(100), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="linked", nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class Consent(Base):
    __tablename__ = "consents"
    __table_args__ = (
        CheckConstraint("status IN ('active','revoked','expired')", name="status"),
        Index("ix_consents_caregiver_status", "caregiver_subject", "status"),
        Index("ix_consents_patient_status", "patient_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    grantor_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    caregiver_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    scopes: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    purpose: Mapped[str] = mapped_column(String(200), default="care", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    granted_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    expires_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class DataDeletionRequest(Base):
    __tablename__ = "data_deletion_requests"
    __table_args__ = (
        CheckConstraint(
            "status IN ('pending','processing','completed','failed','cancelled')",
            name="status",
        ),
        Index("ix_data_deletion_requests_patient_status", "patient_id", "status"),
        Index("ix_data_deletion_requests_due", "status", "scheduled_for"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True
    )
    requested_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    requested_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    scheduled_for: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)


class ChatSession(Base):
    __tablename__ = "chat_sessions"
    __table_args__ = (
        CheckConstraint("status IN ('active','archived','deleted')", name="status"),
        CheckConstraint(
            "owner_role IN ("
            "'patient','caregiver','doctor','front_desk','pharmacist','compliance','admin'"
            ")",
            name="owner_role",
        ),
        CheckConstraint("traffic_class IN ('real','synthetic')", name="traffic_class"),
        CheckConstraint("title_source IN ('system','user')", name="title_source"),
        Index("ix_chat_sessions_owner_updated", "owner_subject", "updated_at"),
        Index("ix_chat_sessions_patient_created", "patient_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    owner_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    owner_role: Mapped[str] = mapped_column(String(20), nullable=False)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True
    )
    title: Mapped[str] = mapped_column(String(120), default="New conversation", nullable=False)
    title_source: Mapped[str] = mapped_column(String(20), default="system", nullable=False)
    locale: Mapped[str] = mapped_column(String(10), default="en-IN", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    traffic_class: Mapped[str] = mapped_column(String(20), default="real", nullable=False)
    specialty_clarify_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    messages: Mapped[list[ChatMessage]] = relationship(
        back_populates="session", cascade="all, delete-orphan", lazy="raise"
    )


class ChatMessage(Base):
    __tablename__ = "chat_messages"
    __table_args__ = (
        CheckConstraint("role IN ('user','assistant','system')", name="role"),
        Index("ix_chat_messages_session_created", "session_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en-IN", nullable=False)
    sources: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    safety: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    model_alias: Mapped[str | None] = mapped_column(String(60), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[ChatSession] = relationship(back_populates="messages")


class ChatFeedback(Base):
    __tablename__ = "chat_feedback"
    __table_args__ = (
        CheckConstraint(
            "rating IN ('up','down','helpful','not_helpful')",
            name="chat_feedback_rating",
        ),
        Index("ix_chat_feedback_user", "user_subject"),
        Index("ix_chat_feedback_message", "message_id"),
        Index(
            "uq_chat_feedback_message_user",
            "message_id",
            "user_subject",
            unique=True,
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    message_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_messages.id", ondelete="CASCADE"), nullable=False
    )
    user_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    rating: Mapped[str] = mapped_column(String(20), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    review_task_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ChatRun(Base):
    """Operational registry for chat graph turns (interrupt/resume index)."""

    __tablename__ = "chat_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','interrupted','completed','failed','cancelled')",
            name="chat_run_status",
        ),
        Index("ix_chat_runs_session_started", "session_id", "started_at"),
        Index("ix_chat_runs_owner_status", "owner_subject", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    session_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("chat_sessions.id", ondelete="CASCADE"), nullable=False
    )
    owner_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    graph: Mapped[str] = mapped_column(String(80), nullable=False)
    graph_version: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    interrupt_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    interrupt_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    interrupt_payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    checkpoint: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    result_message_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class AuditEvent(Base):
    __tablename__ = "audit_events"
    __table_args__ = (
        Index("ix_audit_events_actor_created", "actor_subject", "created_at"),
        Index("ix_audit_events_patient_created", "patient_id", "created_at"),
        Index("ix_audit_events_resource", "resource_type", "resource_id"),
        Index("ix_audit_events_consent_created", "consent_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    actor_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    actor_role: Mapped[str] = mapped_column(String(20), nullable=False)
    action: Mapped[str] = mapped_column(String(80), nullable=False)
    resource_type: Mapped[str] = mapped_column(String(40), nullable=False)
    resource_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    consent_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_metadata: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, default=dict, nullable=False
    )
    prev_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    event_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Appointment(Base):
    __tablename__ = "appointments"
    __table_args__ = (
        CheckConstraint(
            "status IN ('held','confirmed','cancelled','completed','no_show')", name="status"
        ),
        CheckConstraint("traffic_class IN ('real','synthetic')", name="traffic_class"),
        CheckConstraint("source IN ('assistant', 'front_desk')", name="source"),
        Index("ix_appointments_clinic_starts", "clinic_code", "starts_at"),
        Index("ix_appointments_patient_starts", "patient_id", "starts_at"),
        Index("ix_appointments_source", "source"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    clinic_code: Mapped[str] = mapped_column(String(40), nullable=False)
    doctor_name: Mapped[str] = mapped_column(String(120), nullable=False)
    specialty_code: Mapped[str] = mapped_column(String(40), nullable=False)
    starts_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=20, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="confirmed", nullable=False)
    traffic_class: Mapped[str] = mapped_column(String(20), default="real", nullable=False)
    source: Mapped[str] = mapped_column(String(40), default="front_desk", nullable=False)
    no_show_risk: Mapped[float | None] = mapped_column(Float, nullable=True)
    no_show_band: Mapped[str | None] = mapped_column(String(20), nullable=True)
    waitlist_suggested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    confirm_by_reply: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    waitlist_status: Mapped[str | None] = mapped_column(String(20), nullable=True)
    waitlist_owner_subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    waitlist_claimed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    waitlist_closed_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    waitlist_resolution: Mapped[str | None] = mapped_column(String(40), nullable=True)
    waitlist_notes: Mapped[str | None] = mapped_column(String(500), nullable=True)
    waitlist_offer_patient_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    waitlist_offer_appointment_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class BookingIdempotency(Base):
    """Durable idempotency for chat/agent booking retries (FR-W1-11)."""

    __tablename__ = "booking_idempotency"

    scope: Mapped[str] = mapped_column(String(120), primary_key=True)
    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    appointment_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("appointments.id", ondelete="CASCADE"), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FeatureFlagChange(Base):
    __tablename__ = "feature_flag_changes"

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    flag_key: Mapped[str] = mapped_column(String(80), nullable=False)
    old_value: Mapped[bool] = mapped_column(nullable=False)
    new_value: Mapped[bool] = mapped_column(nullable=False)
    actor_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    reason: Mapped[str] = mapped_column(String(300), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FeatureFlagOverride(Base):
    __tablename__ = "feature_flag_overrides"

    flag_key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[bool] = mapped_column(nullable=False)
    updated_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class UsageRecord(Base):
    __tablename__ = "usage_records"
    __table_args__ = (
        CheckConstraint("traffic_class IN ('real','synthetic')", name="traffic_class"),
        Index("ix_usage_records_created_purpose", "created_at", "purpose"),
        Index("ix_usage_records_alias", "model_alias"),
        Index("ix_usage_records_gateway_request", "gateway_request_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    gateway_request_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    purpose: Mapped[str] = mapped_column(String(60), nullable=False)
    model_alias: Mapped[str] = mapped_column(String(60), nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    traffic_class: Mapped[str] = mapped_column(String(20), default="real", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Document(Base):
    __tablename__ = "documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued','processing','indexed','failed','quarantined')", name="status"
        ),
        CheckConstraint("traffic_class IN ('real','synthetic')", name="traffic_class"),
        Index("ix_documents_patient_created", "patient_id", "created_at"),
        Index("ix_documents_status_created", "status", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    uploaded_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    kind: Mapped[str] = mapped_column(String(40), default="other", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    object_key: Mapped[str] = mapped_column(String(400), nullable=False)
    content_type: Mapped[str] = mapped_column(String(100), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    checksum_sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en-IN", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    page_count: Mapped[int | None] = mapped_column(Integer, nullable=True)
    scan_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    scan_engine: Mapped[str | None] = mapped_column(String(60), nullable=True)
    scan_engine_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scanned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    quarantine_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    traffic_class: Mapped[str] = mapped_column(String(20), default="real", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class DocumentChunk(Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        Index("ix_document_chunks_patient", "patient_id"),
        Index("ix_document_chunks_document_index", "document_id", "chunk_index", unique=True),
        Index(
            "ix_document_chunks_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="CASCADE"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    section: Mapped[str | None] = mapped_column(String(200), nullable=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    quarantine_tag: Mapped[str | None] = mapped_column(String(40), nullable=True)
    retrieval_allowed: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Medication(Base):
    __tablename__ = "medications"
    __table_args__ = (
        CheckConstraint("status IN ('active','stopped','completed')", name="status"),
        Index("ix_medications_patient_status", "patient_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    dose: Mapped[str | None] = mapped_column(String(100), nullable=True)
    frequency: Mapped[str | None] = mapped_column(String(100), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    started_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    ended_on: Mapped[dt.date | None] = mapped_column(Date, nullable=True)
    source_document_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("documents.id", ondelete="SET NULL"), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Notification(Base):
    __tablename__ = "notifications"
    __table_args__ = (
        CheckConstraint("status IN ('queued','sent','failed','suppressed','read')", name="status"),
        CheckConstraint("traffic_class IN ('real','synthetic')", name="traffic_class"),
        Index("ix_notifications_recipient_created", "recipient_subject", "created_at"),
        Index("ix_notifications_patient_created", "patient_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True
    )
    recipient_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    recipient_role: Mapped[str] = mapped_column(String(20), nullable=False)
    template_id: Mapped[str] = mapped_column(String(60), nullable=False)
    template_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    traffic_class: Mapped[str] = mapped_column(String(20), default="real", nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    read_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NotificationDelivery(Base):
    __tablename__ = "notification_deliveries"
    __table_args__ = (
        CheckConstraint("channel IN ('email','sms','slack_staff','slack_patient')", name="channel"),
        CheckConstraint("status IN ('queued','sent','failed','suppressed')", name="status"),
        Index("ix_notification_deliveries_notification", "notification_id"),
        Index("ix_notification_deliveries_status_scheduled", "status", "scheduled_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    notification_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("notifications.id", ondelete="CASCADE"), nullable=False
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="queued", nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, server_default="0", nullable=False)
    last_error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    provider_message_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    scheduled_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    sent_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Encounter(Base):
    __tablename__ = "encounters"
    __table_args__ = (
        CheckConstraint("kind IN ('scheduled','walk_in')", name="kind"),
        CheckConstraint("status IN ('active','closed','cancelled')", name="status"),
        CheckConstraint("traffic_class IN ('real','synthetic')", name="traffic_class"),
        Index("ix_encounters_patient_started", "patient_id", "started_at"),
        Index("ix_encounters_doctor_started", "doctor_subject", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    doctor_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    doctor_name: Mapped[str] = mapped_column(String(120), nullable=False)
    clinic_code: Mapped[str] = mapped_column(String(40), nullable=False)
    appointment_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("appointments.id", ondelete="SET NULL"), nullable=True
    )
    kind: Mapped[str] = mapped_column(String(20), default="scheduled", nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="active", nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    ended_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    traffic_class: Mapped[str] = mapped_column(String(20), default="real", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Transcript(Base):
    __tablename__ = "transcripts"
    __table_args__ = (
        CheckConstraint(
            "status IN ('uploaded','processing','ready','failed','deleted')", name="status"
        ),
        CheckConstraint("source IN ('audio','manual')", name="source"),
        Index("ix_transcripts_encounter", "encounter_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("encounters.id", ondelete="CASCADE"), nullable=False
    )
    status: Mapped[str] = mapped_column(String(20), default="uploaded", nullable=False)
    source: Mapped[str] = mapped_column(String(20), default="manual", nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="mixed", nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    object_key: Mapped[str | None] = mapped_column(String(400), nullable=True)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    scan_status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)
    scan_engine: Mapped[str | None] = mapped_column(String(60), nullable=True)
    scan_engine_version: Mapped[str | None] = mapped_column(String(120), nullable=True)
    scanned_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    audio_deleted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    deleted_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class TranscriptTurn(Base):
    __tablename__ = "transcript_turns"
    __table_args__ = (
        CheckConstraint("speaker IN ('doctor','patient','other')", name="speaker"),
        Index("ix_transcript_turns_transcript_index", "transcript_id", "turn_index", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    turn_index: Mapped[int] = mapped_column(Integer, nullable=False)
    speaker: Mapped[str] = mapped_column(String(20), nullable=False)
    start_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    end_ms: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="mixed", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ScribeRun(Base):
    __tablename__ = "scribe_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running','draft','rejected','signed','failed','blocked','parked')",
            name="status",
        ),
        Index("ix_scribe_runs_encounter_created", "encounter_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("encounters.id", ondelete="CASCADE"), nullable=False
    )
    transcript_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("transcripts.id", ondelete="CASCADE"), nullable=False
    )
    requested_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    trace_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    revision: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    model_alias: Mapped[str | None] = mapped_column(String(60), nullable=True)
    prompt_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(60), nullable=True)
    rejection_reason: Mapped[str | None] = mapped_column(String(500), nullable=True)
    rejection_category: Mapped[str | None] = mapped_column(String(40), nullable=True)
    red_flag_ids: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    red_flag_acknowledged_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    completed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    review_seconds: Mapped[float | None] = mapped_column(Float, nullable=True)
    edit_distance: Mapped[dict[str, Any] | None] = mapped_column(JSONB, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class ScribeDraft(Base):
    __tablename__ = "scribe_drafts"
    __table_args__ = (Index("ix_scribe_drafts_run_revision", "run_id", "revision", unique=True),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scribe_runs.id", ondelete="CASCADE"), nullable=False
    )
    revision: Mapped[int] = mapped_column(Integer, nullable=False)
    schema_version: Mapped[str] = mapped_column(String(20), default="scribe_v1", nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ScribeSource(Base):
    __tablename__ = "scribe_sources"
    __table_args__ = (Index("ix_scribe_sources_draft", "draft_id"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    draft_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("scribe_drafts.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(String(40), nullable=False)
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="resolved", nullable=False)
    as_of: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClinicalNote(Base):
    __tablename__ = "clinical_notes"
    __table_args__ = (
        CheckConstraint("status IN ('signed','amended')", name="status"),
        Index("ix_clinical_notes_patient_created", "patient_id", "created_at"),
        Index("ix_clinical_notes_encounter", "encounter_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    encounter_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("encounters.id", ondelete="RESTRICT"), nullable=False
    )
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    author_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="signed", nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    language: Mapped[str] = mapped_column(String(10), default="en-IN", nullable=False)
    current_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    signed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    signed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signed_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ClinicalNoteVersion(Base):
    __tablename__ = "clinical_note_versions"
    __table_args__ = (
        Index("ix_clinical_note_versions_note_version", "note_id", "version", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clinical_notes.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    content: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    content_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    prev_content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    parent_version: Mapped[int | None] = mapped_column(Integer, nullable=True)
    signed_by: Mapped[str] = mapped_column(String(200), nullable=False)
    signed_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    signature_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NoteSource(Base):
    __tablename__ = "note_sources"
    __table_args__ = (Index("ix_note_sources_note_version", "note_id", "version"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clinical_notes.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    field: Mapped[str] = mapped_column(String(40), nullable=False)
    line_index: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str] = mapped_column(String(20), nullable=False)
    source_ref: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="resolved", nullable=False)
    as_of: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StockItemRecord(Base):
    __tablename__ = "stock_items"
    __table_args__ = (
        Index("ix_stock_items_clinic_name", "clinic_code", "drug_name"),
        Index("uq_stock_items_clinic_sku", "clinic_code", "sku", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    sku: Mapped[str] = mapped_column(String(80), nullable=False)
    drug_name: Mapped[str] = mapped_column(String(200), nullable=False)
    form: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    strength: Mapped[str] = mapped_column(String(80), default="", nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    clinic_code: Mapped[str] = mapped_column(String(40), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    source: Mapped[str] = mapped_column(String(80), default="demo-stock", nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StockImport(Base):
    __tablename__ = "stock_imports"
    __table_args__ = (Index("ix_stock_imports_created", "created_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(80), nullable=False)
    file_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    as_of: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    row_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="succeeded")
    errors: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class StockReservation(Base):
    __tablename__ = "stock_reservations"
    __table_args__ = (
        CheckConstraint("status IN ('reserved','cancelled')", name="status"),
        Index("ix_stock_reservations_note", "note_id"),
        Index("ix_stock_reservations_clinic", "clinic_code", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    note_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("clinical_notes.id", ondelete="RESTRICT"), nullable=False
    )
    medicine_name: Mapped[str] = mapped_column(String(200), nullable=False)
    sku: Mapped[str | None] = mapped_column(String(80), nullable=True)
    clinic_code: Mapped[str] = mapped_column(String(40), nullable=False)
    quantity: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="reserved", nullable=False)
    reserved_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ReviewTask(Base):
    __tablename__ = "review_tasks"
    __table_args__ = (
        CheckConstraint("status IN ('open','in_progress','closed')", name="status"),
        Index("ix_review_tasks_status_due", "status", "due_at"),
        Index("ix_review_tasks_patient", "patient_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True
    )
    created_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    assigned_role: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(String(200), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    owner_subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    resolution: Mapped[str | None] = mapped_column(String(500), nullable=True)
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Handoff(Base):
    __tablename__ = "handoffs"
    __table_args__ = (
        CheckConstraint("status IN ('open','assigned','resolved')", name="status"),
        CheckConstraint("priority IN ('normal','urgent','emergency')", name="priority"),
        CheckConstraint(
            "delivery_status IN ('pending','queued','sent','partial','failed','skipped')",
            name="delivery_status",
        ),
        Index("ix_handoffs_status_created", "status", "created_at"),
        Index("ix_handoffs_clinic_status", "clinic_code", "status"),
        Index("ix_handoffs_patient_created", "patient_id", "created_at"),
        Index("ix_handoffs_sla_due", "status", "sla_due_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True
    )
    created_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    assigned_to_subject: Mapped[str | None] = mapped_column(String(200), nullable=True)
    clinic_code: Mapped[str] = mapped_column(String(40), nullable=False)
    reason: Mapped[str] = mapped_column(String(500), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    priority: Mapped[str] = mapped_column(String(20), default="normal", nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    resource_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    resource_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    rule_ids: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    sla_due_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    notified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    delivery_status: Mapped[str] = mapped_column(String(40), default="pending", nullable=False)
    overdue_alerted_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    # First human ack (assign). mtta_seconds = acknowledged_at - created_at.
    acknowledged_at: Mapped[dt.datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    mtta_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    resolved_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class SafetyIncident(Base):
    __tablename__ = "safety_incidents"
    __table_args__ = (
        CheckConstraint("severity IN ('low','medium','high','critical')", name="severity"),
        CheckConstraint("status IN ('open','investigating','closed')", name="status"),
        Index("ix_safety_incidents_status_created", "status", "created_at"),
        Index("ix_safety_incidents_severity_status", "severity", "status"),
        Index("ix_safety_incidents_patient_created", "patient_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="SET NULL"), nullable=True
    )
    reported_by_subject: Mapped[str] = mapped_column(String(200), nullable=False)
    severity: Mapped[str] = mapped_column(String(20), nullable=False)
    category: Mapped[str] = mapped_column(String(80), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="open", nullable=False)
    linked_resource_type: Mapped[str | None] = mapped_column(String(40), nullable=True)
    linked_resource_id: Mapped[str | None] = mapped_column(String(200), nullable=True)
    resolution: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    closed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class MemoryPreference(Base):
    __tablename__ = "memory_preferences"
    __table_args__ = (Index("ix_memory_preferences_subject", "subject"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[str] = mapped_column(String(500), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class AgentMemory(Base):
    """First-party durable non-clinical memory when MEMORY_BACKEND=pgvector."""

    __tablename__ = "agent_memories"
    __table_args__ = (
        CheckConstraint("kind IN ('preference','episodic')", name="agent_memory_kind"),
        Index("ix_agent_memories_subject_kind", "subject", "kind"),
        Index("ix_agent_memories_session", "session_id"),
        Index(
            "ix_agent_memories_embedding_hnsw",
            "embedding",
            postgresql_using="hnsw",
            postgresql_with={"m": 16, "ef_construction": 64},
            postgresql_ops={"embedding": "vector_cosine_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    session_id: Mapped[uuid.UUID | None] = mapped_column(Uuid, nullable=True)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float]] = mapped_column(Vector(1024), nullable=False)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        "metadata", JSONB, nullable=False, default=dict
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ContactChannel(Base):
    __tablename__ = "contact_channels"
    __table_args__ = (
        CheckConstraint("channel IN ('email','sms','slack_staff','slack_patient')", name="channel"),
        Index("ix_contact_channels_subject_channel", "subject", "channel"),
        Index("ix_contact_channels_patient", "patient_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    subject: Mapped[str] = mapped_column(String(200), nullable=False)
    patient_id: Mapped[uuid.UUID | None] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=True
    )
    channel: Mapped[str] = mapped_column(String(20), nullable=False)
    address: Mapped[str] = mapped_column(String(300), nullable=False)
    verified: Mapped[bool] = mapped_column(default=False, nullable=False)
    opt_in: Mapped[bool] = mapped_column(default=False, nullable=False)
    workspace_id: Mapped[str | None] = mapped_column(String(100), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    verified_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ContactVerificationCode(Base):
    __tablename__ = "contact_verification_codes"
    __table_args__ = (
        Index("ix_contact_verification_codes_contact_created", "contact_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    contact_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("contact_channels.id", ondelete="CASCADE"), nullable=False
    )
    code_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FinopsBudget(Base):
    __tablename__ = "finops_budgets"
    __table_args__ = (
        CheckConstraint("limit_usd >= 0", name="limit_usd"),
        CheckConstraint("alert_pct >= 0 AND alert_pct <= 100", name="alert_pct"),
        UniqueConstraint("scope_type", "scope_id", "period", name="uq_finops_budgets_scope_period"),
        Index("ix_finops_budgets_period", "period"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    scope_type: Mapped[str] = mapped_column(String(40), nullable=False)
    scope_id: Mapped[str] = mapped_column(String(200), nullable=False)
    period: Mapped[str] = mapped_column(String(7), nullable=False)
    limit_usd: Mapped[float] = mapped_column(Float, nullable=False)
    alert_pct: Mapped[float] = mapped_column(
        Float, default=80.0, server_default="80", nullable=False
    )
    hard_stop: Mapped[bool] = mapped_column(
        Boolean, default=False, server_default="false", nullable=False
    )
    owner: Mapped[str] = mapped_column(String(200), nullable=False)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class FinopsSaving(Base):
    __tablename__ = "finops_savings"
    __table_args__ = (
        CheckConstraint("amount_usd >= 0", name="amount_usd"),
        Index("ix_finops_savings_period", "period_month"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    amount_usd: Mapped[float] = mapped_column(Float, nullable=False)
    period_month: Mapped[str] = mapped_column(String(7), nullable=False)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvalRun(Base):
    __tablename__ = "eval_runs"
    __table_args__ = (
        CheckConstraint("status IN ('passed','failed','error','unavailable')", name="status"),
        Index("ix_eval_runs_suite_created", "suite", "created_at"),
        Index("ix_eval_runs_framework_created", "framework", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    suite: Mapped[str] = mapped_column(String(40), nullable=False)
    framework: Mapped[str] = mapped_column(String(40), nullable=False)
    framework_version: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), nullable=False)
    dataset_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    git_sha: Mapped[str | None] = mapped_column(String(64), nullable=True)
    prompt_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    graph_version: Mapped[str | None] = mapped_column(String(80), nullable=True)
    judge_alias: Mapped[str | None] = mapped_column(String(60), nullable=True)
    case_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    passed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    failed_cases: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    thresholds: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    case_results: Mapped[list[dict[str, Any]]] = mapped_column(JSONB, default=list, nullable=False)
    artifact_key: Mapped[str | None] = mapped_column(String(300), nullable=True)
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class EvalMetricResult(Base):
    __tablename__ = "eval_metric_results"
    __table_args__ = (Index("ix_eval_metric_results_run_metric", "run_id", "metric_key"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    run_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("eval_runs.id", ondelete="CASCADE"), nullable=False
    )
    metric_key: Mapped[str] = mapped_column(String(80), nullable=False)
    value: Mapped[float] = mapped_column(Float, nullable=False)
    unit: Mapped[str] = mapped_column(String(20), default="ratio", nullable=False)
    framework: Mapped[str] = mapped_column(String(40), nullable=False)
    dimensions: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class GatewaySpendLog(Base):
    """Read-only mirror of LiteLLM spend rows used for reconciliation."""

    __tablename__ = "gateway_spend_logs"
    __table_args__ = (Index("ix_gateway_spend_started", "started_at"),)

    request_id: Mapped[str] = mapped_column(String(200), primary_key=True)
    model_alias: Mapped[str] = mapped_column(String(80), nullable=False)
    spend_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    total_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    status: Mapped[str | None] = mapped_column(String(40), nullable=True)
    started_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    imported_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class SpendReconciliation(Base):
    __tablename__ = "spend_reconciliations"
    __table_args__ = (
        CheckConstraint(
            "status IN ('matched','partial','variance','insufficient_data')", name="status"
        ),
        Index("ix_spend_reconciliations_created", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    window_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    app_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    gateway_cost_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    app_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gateway_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    matched_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unmatched_app_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    unmatched_gateway_calls: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    variance_usd: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    variance_pct: Mapped[float] = mapped_column(Float, default=0.0, nullable=False)
    tolerance_pct: Mapped[float] = mapped_column(Float, default=2.0, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="insufficient_data", nullable=False)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AnalyticsSnapshot(Base):
    __tablename__ = "analytics_snapshots"
    __table_args__ = (Index("ix_analytics_snapshots_captured", "captured_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    captured_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    period_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    period_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    metric_version: Mapped[str] = mapped_column(String(40), nullable=False)
    metrics: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    suppression_applied: Mapped[bool] = mapped_column(default=True, nullable=False)


class Insight(Base):
    __tablename__ = "insights"
    __table_args__ = (
        CheckConstraint("status IN ('proposed','accepted','rejected','expired')", name="status"),
        Index("ix_insights_status_created", "status", "created_at"),
        Index("ix_insights_dedupe", "dedupe_key", unique=True),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    dedupe_key: Mapped[str] = mapped_column(String(160), nullable=False)
    area: Mapped[str] = mapped_column(String(40), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    recommendation: Mapped[str] = mapped_column(Text, nullable=False)
    impact: Mapped[str | None] = mapped_column(String(300), nullable=True)
    confidence: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    effort: Mapped[str] = mapped_column(String(20), default="medium", nullable=False)
    owner: Mapped[str] = mapped_column(String(60), default="operations", nullable=False)
    evidence: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    generator: Mapped[str] = mapped_column(
        String(60), default="deterministic_rules", nullable=False
    )
    model_alias: Mapped[str | None] = mapped_column(String(60), nullable=True)
    ai_generated: Mapped[bool] = mapped_column(default=False, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="proposed", nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    window_start: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_end: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class JobRun(Base):
    __tablename__ = "job_runs"
    __table_args__ = (Index("ix_job_runs_name_started", "job_name", "started_at"),)

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    job_name: Mapped[str] = mapped_column(String(80), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="running", nullable=False)
    started_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    detail: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    error_code: Mapped[str | None] = mapped_column(String(80), nullable=True)


class ComplianceAttestation(Base):
    """G-12 / G-19 governance attestations (clinical validation report, DPDP audit).

    Status is product attestation only — never regulatory clearance by itself.
    """

    __tablename__ = "compliance_attestations"
    __table_args__ = (
        CheckConstraint(
            "kind IN ('clinical_validation','dpdp_audit')",
            name="ck_compliance_attestations_kind",
        ),
        CheckConstraint(
            "status IN ('not_attested','pending','attested','disapproved','revoked')",
            name="ck_compliance_attestations_status",
        ),
        UniqueConstraint("kind", name="uq_compliance_attestations_kind"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    kind: Mapped[str] = mapped_column(String(40), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="not_attested", nullable=False)
    approver_name: Mapped[str | None] = mapped_column(String(200), nullable=True)
    approver_role: Mapped[str | None] = mapped_column(String(120), nullable=True)
    attested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    attestation_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    report_object_key: Mapped[str | None] = mapped_column(String(500), nullable=True)
    report_sha256: Mapped[str | None] = mapped_column(String(64), nullable=True)
    report_filename: Mapped[str | None] = mapped_column(String(260), nullable=True)
    report_content_type: Mapped[str | None] = mapped_column(String(120), nullable=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class GovernanceSetting(Base):
    """Admin-configurable retention / egress / judge settings (G-15/16/24/28)."""

    __tablename__ = "governance_settings"

    key: Mapped[str] = mapped_column(String(80), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    updated_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class NursingSummary(Base):
    """X-01 nursing shift summary drafts with human accept/edit/reject."""

    __tablename__ = "nursing_summaries"
    __table_args__ = (
        CheckConstraint(
            "status IN ('draft','accepted','edited','rejected')",
            name="ck_nursing_summaries_status",
        ),
        UniqueConstraint("patient_id", "version", name="uq_nursing_summaries_patient_version"),
        Index("ix_nursing_summaries_patient_status", "patient_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(Uuid, primary_key=True, default=uuid.uuid4)
    patient_id: Mapped[uuid.UUID] = mapped_column(
        Uuid, ForeignKey("patients.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="draft", nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    sources: Mapped[list[Any]] = mapped_column(JSONB, default=list, nullable=False)
    graph: Mapped[str] = mapped_column(String(80), default="x01_nursing.v1", nullable=False)
    model_alias: Mapped[str | None] = mapped_column(String(80), nullable=True)
    created_by: Mapped[str] = mapped_column(String(200), nullable=False)
    decided_by: Mapped[str | None] = mapped_column(String(200), nullable=True)
    decided_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    decision_note: Mapped[str | None] = mapped_column(String(500), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )
