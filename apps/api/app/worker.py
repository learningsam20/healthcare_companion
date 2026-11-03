"""ARQ worker for scheduled retention jobs.

The worker runs only configured, evidence-producing jobs. It never purges clinical
notes and never touches object storage; those jobs are separate runbooks.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sahyog_common.logging import configure_logging
from sqlalchemy import delete, func, select, update

from app.composition import build_app_services
from app.core.config import get_settings
from app.core.ports import DeliveryError
from app.modules.notifications.service import NotificationService
from app.modules.records.ingest import ingest_document_job
from app.repositories.audit import AuditRepository
from app.repositories.models import (
    Appointment,
    ChatSession,
    ClinicalNote,
    Consent,
    Document,
    Encounter,
    Notification,
    Patient,
    ReviewTask,
    StockReservation,
    Transcript,
)
from app.repositories.notifications import ContactChannelRepository, NotificationRepository
from app.repositories.privacy import DataDeletionRequestRepository
from app.repositories.scribe import EncounterRepository, TranscriptRepository

logger = logging.getLogger(__name__)


async def startup(ctx: dict[str, Any]) -> None:
    settings = get_settings()
    settings.validate_startup()
    configure_logging(settings.log_level)
    ctx["services"] = build_app_services(settings)


async def shutdown(ctx: dict[str, Any]) -> None:
    services = ctx.get("services")
    if services is not None:
        await services.db.dispose()


async def purge_expired_chat_sessions(ctx: dict[str, Any]) -> int:
    services = ctx["services"]
    chat_days = int(services.app_config.get("retention", {}).get("chat_days", 30))
    async with services.db.sessionmaker() as session:
        # G-24: an explicit admin chat_retention_days can only shorten the config baseline.
        from app.modules.memory.retention import effective_chat_retention_days

        chat_days = await effective_chat_retention_days(session, chat_days)
        cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=chat_days)
        candidates = await session.scalar(
            select(func.count())
            .select_from(ChatSession)
            .where(
                ChatSession.updated_at < cutoff,
                ChatSession.status == "active",
            )
        )
        if candidates:
            await session.execute(
                update(ChatSession)
                .where(
                    ChatSession.updated_at < cutoff,
                    ChatSession.status == "active",
                )
                .values(status="deleted", deleted_at=dt.datetime.now(dt.UTC))
            )
            AuditRepository(session).append(
                actor_subject="system:retention",
                actor_role="service",
                action="retention.chat_sessions_purged",
                resource_type="chat_session",
                metadata={"count": int(candidates), "cutoff": cutoff.isoformat()},
            )
            await session.commit()
    logger.info(
        "chat retention run",
        extra={"event": "retention.chat_sessions", "extra_fields": {"count": int(candidates or 0)}},
    )
    return int(candidates or 0)


async def expire_consents(ctx: dict[str, Any]) -> int:
    services = ctx["services"]
    now = dt.datetime.now(dt.UTC)
    async with services.db.sessionmaker() as session:
        expired = await session.scalar(
            select(func.count())
            .select_from(Consent)
            .where(
                Consent.status == "active",
                Consent.expires_at.is_not(None),
                Consent.expires_at <= now,
            )
        )
        if expired:
            await session.execute(
                update(Consent)
                .where(
                    Consent.status == "active",
                    Consent.expires_at.is_not(None),
                    Consent.expires_at <= now,
                )
                .values(status="expired")
            )
            AuditRepository(session).append(
                actor_subject="system:retention",
                actor_role="service",
                action="consent.expired",
                resource_type="consent",
                metadata={"count": int(expired), "checked_at": now.isoformat()},
            )
            await session.commit()
    return int(expired or 0)


async def delete_expired_audio(ctx: dict[str, Any]) -> dict[str, int]:
    services = ctx["services"]
    audio_hours = int(services.app_config.get("retention", {}).get("audio_hours", 24))
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(hours=audio_hours)
    counts = {"deleted": 0, "failed": 0, "skipped_unconfigured": 0}
    async with services.db.sessionmaker() as session:
        transcripts = TranscriptRepository(session)
        encounters = EncounterRepository(session)
        for transcript in await transcripts.due_audio_deletions(cutoff=cutoff):
            if not services.settings.s3_configured:
                counts["skipped_unconfigured"] += 1
                continue
            try:
                await services.storage.delete(
                    key=transcript.object_key or "",
                    bucket=services.settings.s3_bucket_audio,
                )
            except Exception as exc:  # noqa: BLE001 - storage boundary, retry next run
                logger.warning(
                    "audio deletion failed",
                    extra={
                        "event": "retention.audio_delete_failed",
                        "extra_fields": {"transcript_id": str(transcript.id)},
                    },
                    exc_info=exc,
                )
                counts["failed"] += 1
                continue
            await transcripts.mark_audio_deleted(transcript)
            encounter = await encounters.get(transcript.encounter_id)
            AuditRepository(session).append(
                actor_subject="system:retention",
                actor_role="service",
                action="retention.audio_deleted",
                resource_type="transcript",
                resource_id=str(transcript.id),
                patient_id=encounter.patient_id if encounter else None,
                metadata={"cutoff": cutoff.isoformat(), "audio_hours": audio_hours},
            )
            counts["deleted"] += 1
        await session.commit()
    logger.info(
        "audio retention run",
        extra={"event": "retention.audio", "extra_fields": counts},
    )
    return counts


async def _purge_patient(services: Any, session: Any, patient_id: Any) -> dict[str, int]:
    documents = list(
        await session.scalars(select(Document).where(Document.patient_id == patient_id))
    )
    transcripts = list(
        await session.scalars(
            select(Transcript)
            .join(Encounter, Encounter.id == Transcript.encounter_id)
            .where(Encounter.patient_id == patient_id, Transcript.object_key.is_not(None))
        )
    )
    keys = [key for row in documents for key in (row.object_key, row.quarantine_key) if key]
    audio_keys = [row.object_key for row in transcripts if row.object_key]
    if keys or audio_keys:
        if not services.settings.s3_configured:
            raise RuntimeError("object storage is not configured; refusing an incomplete purge")
        for key in dict.fromkeys(keys):
            await services.storage.delete(key=key)
        for key in audio_keys:
            await services.storage.delete(
                key=key, bucket=services.settings.s3_bucket_audio
            )

    note_ids = select(ClinicalNote.id).where(ClinicalNote.patient_id == patient_id)
    reservations = await session.execute(
        delete(StockReservation).where(StockReservation.note_id.in_(note_ids))
    )
    sessions = await session.execute(
        delete(ChatSession).where(ChatSession.patient_id == patient_id)
    )
    notifications = await session.execute(
        delete(Notification).where(Notification.patient_id == patient_id)
    )
    reviews = await session.execute(
        delete(ReviewTask).where(ReviewTask.patient_id == patient_id)
    )
    appointments = await session.execute(
        delete(Appointment).where(Appointment.patient_id == patient_id)
    )
    notes = await session.execute(
        delete(ClinicalNote).where(ClinicalNote.patient_id == patient_id)
    )
    encounters = await session.execute(
        delete(Encounter).where(Encounter.patient_id == patient_id)
    )
    patients = await session.execute(delete(Patient).where(Patient.id == patient_id))
    return {
        "documents": len(documents),
        "objects_deleted": len(set(keys)) + len(audio_keys),
        "transcripts": len(transcripts),
        "chat_sessions": int(sessions.rowcount or 0),
        "notifications": int(notifications.rowcount or 0),
        "review_tasks": int(reviews.rowcount or 0),
        "appointments": int(appointments.rowcount or 0),
        "stock_reservations": int(reservations.rowcount or 0),
        "clinical_notes": int(notes.rowcount or 0),
        "encounters": int(encounters.rowcount or 0),
        "patients": int(patients.rowcount or 0),
    }


async def process_deletion_requests(ctx: dict[str, Any]) -> dict[str, int]:
    services = ctx["services"]
    now = dt.datetime.now(dt.UTC)
    counts = {"completed": 0, "failed": 0}
    async with services.db.sessionmaker() as session:
        repo = DataDeletionRequestRepository(session)
        for request in await repo.due(now=now):
            request.status = "processing"
            await session.flush()
            try:
                async with session.begin_nested():
                    evidence = await _purge_patient(services, session, request.patient_id)
            except Exception as exc:  # noqa: BLE001 - retried by the operator runbook
                request.status = "failed"
                request.evidence = {
                    **dict(request.evidence or {}),
                    "error": type(exc).__name__,
                    "failed_at": now.isoformat(),
                }
                AuditRepository(session).append(
                    actor_subject="system:privacy",
                    actor_role="service",
                    action="privacy.deletion_failed",
                    resource_type="data_deletion_request",
                    resource_id=str(request.id),
                    patient_id=request.patient_id,
                    metadata={"error": type(exc).__name__},
                )
                counts["failed"] += 1
                await session.commit()
                continue
            request.status = "completed"
            request.completed_at = now
            request.evidence = {**dict(request.evidence or {}), "deleted": evidence}
            AuditRepository(session).append(
                actor_subject="system:privacy",
                actor_role="service",
                action="privacy.deletion_completed",
                resource_type="data_deletion_request",
                resource_id=str(request.id),
                patient_id=request.patient_id,
                metadata={"deleted": evidence},
            )
            counts["completed"] += 1
            await session.commit()
    logger.info(
        "deletion request run",
        extra={"event": "privacy.deletion", "extra_fields": counts},
    )
    return counts


async def dispatch_pending_notifications(ctx: dict[str, Any]) -> dict[str, int]:
    services = ctx["services"]
    retry = services.notifications_config.get("retry", {})
    max_attempts = int(retry.get("max_attempts", 3))
    backoff = [int(value) for value in retry.get("backoff_seconds", [30, 120, 600])]
    now = dt.datetime.now(dt.UTC)
    counts = {"sent": 0, "retried": 0, "failed": 0, "suppressed": 0}
    async with services.db.sessionmaker() as session:
        repo = NotificationRepository(session)
        contacts = ContactChannelRepository(session)
        service = NotificationService(services, session)
        for delivery in await repo.due_deliveries(now=now):
            notification = await repo.get(delivery.notification_id)
            if notification is None:
                await repo.update_delivery(
                    delivery, status="failed", attempts=delivery.attempts, error_code="missing"
                )
                counts["failed"] += 1
                continue
            if notification.template_id == "delivery_failure":
                await repo.update_delivery(
                    delivery,
                    status="suppressed",
                    attempts=delivery.attempts,
                    error_code="no_recursive_delivery",
                )
                counts["suppressed"] += 1
                continue
            contact = await contacts.find(
                subject=notification.recipient_subject,
                channel=delivery.channel,
                patient_id=notification.patient_id,
            )
            if contact is None or not contact.verified:
                await repo.update_delivery(
                    delivery,
                    status="suppressed",
                    attempts=delivery.attempts,
                    error_code="recipient_missing" if contact is None else "recipient_unverified",
                )
                counts["suppressed"] += 1
                continue
            dispatcher = services.notifications
            attempt = delivery.attempts + 1
            if dispatcher is None or not dispatcher.configured(delivery.channel):
                error_code = "adapter_unconfigured"
            else:
                try:
                    attachments = None
                    if delivery.channel == "email":
                        from app.modules.notifications.attachments import decode_attachments

                        payload = notification.payload or {}
                        attachments = decode_attachments(payload.get("attachments"))
                    raw_presentation = (notification.payload or {}).get("presentation")
                    message_id = await dispatcher.send(
                        channel=delivery.channel,
                        address=contact.address,
                        subject=notification.title,
                        body=notification.body,
                        attachments=attachments,
                        presentation=(
                            raw_presentation if isinstance(raw_presentation, dict) else None
                        ),
                    )
                except DeliveryError as exc:
                    error_code = exc.code
                except Exception as exc:  # noqa: BLE001 - adapter boundary, fail closed
                    logger.warning(
                        "notification adapter error",
                        extra={
                            "event": "notification.adapter_error",
                            "extra_fields": {"channel": delivery.channel},
                        },
                        exc_info=exc,
                    )
                    error_code = "adapter_error"
                else:
                    await repo.update_delivery(
                        delivery,
                        status="sent",
                        attempts=attempt,
                        provider_message_id=message_id,
                    )
                    counts["sent"] += 1
                    continue
            if error_code == "adapter_unconfigured" or attempt >= max_attempts:
                await repo.update_delivery(
                    delivery, status="failed", attempts=attempt, error_code=error_code
                )
                counts["failed"] += 1
                if services.settings.notify_ops_subject:
                    await service.send(
                        template_id="delivery_failure",
                        recipient_subject=services.settings.notify_ops_subject,
                        recipient_role="admin",
                        patient_id=None,
                        locale="en-IN",
                        data={"channel": delivery.channel},
                        actor_subject="system:notifications",
                        actor_role="service",
                        requested_channels=[],
                        emergency=True,
                    )
                continue
            delay = backoff[min(attempt - 1, len(backoff) - 1)]
            await repo.update_delivery(
                delivery,
                status="queued",
                attempts=attempt,
                error_code=error_code,
                scheduled_at=now + dt.timedelta(seconds=delay),
            )
            counts["retried"] += 1
        AuditRepository(session).append(
            actor_subject="system:notifications",
            actor_role="service",
            action="notifications.dispatch",
            resource_type="notification_batch",
            metadata={**counts, "checked_at": now.isoformat()},
        )
        await session.commit()
    logger.info(
        "notification dispatch run",
        extra={"event": "notification.dispatch", "extra_fields": counts},
    )
    return counts


async def import_pharmacy_stock(ctx: dict[str, Any]) -> dict[str, Any]:
    """Batch-import CSVs from stock drop_dir into stock_items; records job_runs (G-30)."""
    from app.modules.ops.jobs import run_stock_drop_import

    return await run_stock_drop_import(ctx["services"])


async def purge_expired_memory(ctx: dict[str, Any]) -> dict[str, Any]:
    """Preference-memory retention from governance_settings (G-24)."""
    from app.modules.memory.retention import purge_expired_memory_preferences

    return await purge_expired_memory_preferences(ctx["services"])


class WorkerSettings:
    functions = [
        ingest_document_job,
        dispatch_pending_notifications,
        delete_expired_audio,
        purge_expired_chat_sessions,
        purge_expired_memory,
        expire_consents,
        process_deletion_requests,
        import_pharmacy_stock,
    ]
    cron_jobs = [
        cron(dispatch_pending_notifications, minute=set(range(60))),
        cron(process_deletion_requests, hour={2}, minute={10}),
        # Poll the pharmacy drop folder frequently so uploaded HIS extracts land quickly.
        cron(import_pharmacy_stock, minute={0, 15, 30, 45}),
    ]
    queue_name = get_settings().arq_worker_queue
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_burst_jobs = 10
    job_timeout = 300
    keep_result = 3600
