"""Scheduled notification jobs: contact re-verification scan (G-07)."""

from __future__ import annotations

import datetime as dt
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from app.core.services import Services
from app.repositories.audit import AuditRepository
from app.repositories.models import ContactChannel, JobRun, Patient
from app.repositories.notifications import ContactChannelRepository
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

DEFAULT_MAX_DAYS = 180


@asynccontextmanager
async def _job(services: Services, name: str) -> AsyncIterator[tuple[AsyncSession, JobRun]]:
    async with services.db.sessionmaker() as session:
        run = JobRun(job_name=name, status="running")
        session.add(run)
        await session.flush()
        try:
            yield session, run
        except Exception as exc:
            run.status = "failed"
            run.error_code = type(exc).__name__[:80]
            run.finished_at = dt.datetime.now(dt.UTC)
            await session.commit()
            raise
        else:
            run.status = "succeeded"
            run.finished_at = dt.datetime.now(dt.UTC)
            await session.commit()


async def scan_contact_reverification(
    services: Services,
    *,
    max_days: int = DEFAULT_MAX_DAYS,
) -> dict[str, Any]:
    """Flag verified ContactChannel rows whose verified_at is older than max_days.

    Does not mutate contacts; writes job_runs + an audit event for ops follow-up.
    """
    async with _job(services, "notifications.contact_reverification") as (session, run):
        now = dt.datetime.now(dt.UTC)
        cutoff = now - dt.timedelta(days=max_days)
        rows = await ContactChannelRepository(session).list_due_for_reverification(
            cutoff=cutoff
        )
        due = [
            {
                "id": str(row.id),
                "subject": row.subject,
                "channel": row.channel,
                "verified_at": row.verified_at.isoformat() if row.verified_at else None,
                "opt_in": row.opt_in,
            }
            for row in rows
        ]
        AuditRepository(session).append(
            actor_subject="system:notifications",
            actor_role="service",
            action="notifications.contact_reverification_scanned",
            resource_type="contact_channel",
            metadata={
                "max_days": max_days,
                "cutoff": cutoff.isoformat(),
                "due_count": len(due),
                "due_ids": [item["id"] for item in due[:200]],
            },
        )
        coverage = await slack_patient_coverage(
            session,
            expected_workspace=services.settings.slack_patient_workspace_id,
            adapter_configured=services.settings.slack_patient_configured,
            max_days=max_days,
            now=now,
        )
        if coverage["status"] == "below_target":
            # Same ops-alert pattern as analytics staleness (6h audit dedupe, never raises).
            from app.modules.analytics.jobs import _send_alert

            await _send_alert(
                services,
                session,
                alert=(
                    f"Patient Slack verified coverage is {coverage['coverage_percent']}% "
                    f"({coverage['verified']}/{coverage['opted_in']} opted-in); target is 100%."
                ),
                action="notifications.slack_coverage_alerted",
            )
            AuditRepository(session).append(
                actor_subject="system:notifications",
                actor_role="service",
                action="notifications.slack_coverage_alerted",
                resource_type="contact_channel",
                metadata={
                    "coverage_percent": coverage["coverage_percent"],
                    "opted_in": coverage["opted_in"],
                    "verified": coverage["verified"],
                },
            )
        run.detail = {
            "max_days": max_days,
            "cutoff": cutoff.isoformat(),
            "due_count": len(due),
            "due": due[:200],
            "slack_patient_coverage": coverage,
        }
        logger.info(
            "contact re-verification scan",
            extra={
                "event": "notifications.contact_reverification",
                "extra_fields": {"due_count": len(due), "max_days": max_days},
            },
        )
        return dict(run.detail)


def classify_slack_contact(
    contact: ContactChannel,
    *,
    expected_workspace: str,
    now: dt.datetime,
    max_days: int = DEFAULT_MAX_DAYS,
) -> str:
    """Why an opted-in patient Slack contact does (not) count as covered.

    Mirrors the delivery gate in ``NotificationService._external_decision`` plus the
    180-day re-verification window, so coverage never overstates what can be delivered.
    """
    if not contact.verified:
        return "unverified"
    if not expected_workspace:
        return "workspace_unconfigured"
    if contact.workspace_id != expected_workspace:
        return "workspace_mismatch"
    if contact.verified_at is None:
        return "verified_at_missing"
    if channel_due_for_reverify(contact, now=now, max_days=max_days):
        return "stale"
    return "verified"


async def slack_patient_coverage(
    session: AsyncSession,
    *,
    expected_workspace: str,
    adapter_configured: bool,
    max_days: int = DEFAULT_MAX_DAYS,
    now: dt.datetime | None = None,
) -> dict[str, Any]:
    """G-07 coverage: % of opted-in patient Slack contacts that are verified and deliverable.

    ``coverage_percent`` is ``None`` (not 100) when nobody has opted in, so an empty
    population is never reported as closure evidence. ``delivery_ready`` is separate:
    it is false until the patient bot token + workspace are configured.
    """
    current = now or dt.datetime.now(dt.UTC)
    rows = list(
        await session.scalars(
            select(ContactChannel).where(
                ContactChannel.channel == "slack_patient",
                ContactChannel.opt_in.is_(True),
            )
        )
    )
    reasons: dict[str, int] = {
        "verified": 0,
        "unverified": 0,
        "workspace_unconfigured": 0,
        "workspace_mismatch": 0,
        "verified_at_missing": 0,
        "stale": 0,
    }
    for row in rows:
        reasons[
            classify_slack_contact(
                row, expected_workspace=expected_workspace, now=current, max_days=max_days
            )
        ] += 1
    covered_patient_ids = {row.patient_id for row in rows if row.patient_id is not None}
    metadata_only = list(
        await session.scalars(
            select(Patient.id).where(
                Patient.slack_user_id.is_not(None),
                Patient.slack_user_id != "",
                Patient.deleted_at.is_(None),
            )
        )
    )
    metadata_only_unverified = sum(1 for pid in metadata_only if pid not in covered_patient_ids)
    opted_in = len(rows)
    verified = reasons["verified"]
    percent = round(100.0 * verified / opted_in, 1) if opted_in else None
    if opted_in == 0:
        status = "no_opted_in_contacts"
    elif verified == opted_in:
        status = "complete"
    else:
        status = "below_target"
    return {
        "channel": "slack_patient",
        "opted_in": opted_in,
        "verified": verified,
        "not_covered": {key: value for key, value in reasons.items() if key != "verified"},
        "coverage_percent": percent,
        "target_percent": 100,
        "status": status,
        "meets_target": status == "complete",
        "delivery_ready": bool(adapter_configured),
        "workspace_configured": bool(expected_workspace),
        "reverify_after_days": max_days,
        "metadata_only_unverified": metadata_only_unverified,
        "checked_at": current.isoformat(),
        "note": (
            "Closure evidence for G-07 requires status=complete (100% of opted-in patients "
            "verified, workspace-matched, within the re-verification window) with a "
            "configured patient Slack workspace; an empty population is not evidence."
        ),
    }


def channel_due_for_reverify(
    contact: ContactChannel,
    *,
    now: dt.datetime,
    max_days: int = DEFAULT_MAX_DAYS,
) -> bool:
    if not contact.verified or contact.verified_at is None:
        return False
    verified_at = contact.verified_at
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=dt.UTC)
    return verified_at <= now - dt.timedelta(days=max_days)
