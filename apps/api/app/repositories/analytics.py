from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import (
    Appointment,
    AuditEvent,
    ChatMessage,
    ChatSession,
    Consent,
    UsageRecord,
)


class AnalyticsRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def overview_counts(self, *, start: dt.datetime, end: dt.datetime) -> dict[str, int]:
        sessions = await self._session.scalar(
            select(func.count())
            .select_from(ChatSession)
            .where(
                ChatSession.created_at >= start,
                ChatSession.created_at < end,
                ChatSession.traffic_class == "real",
                ChatSession.status != "deleted",
            )
        )
        messages = await self._session.scalar(
            select(func.count())
            .select_from(ChatMessage)
            .join(ChatSession, ChatSession.id == ChatMessage.session_id)
            .where(
                ChatMessage.created_at >= start,
                ChatMessage.created_at < end,
                ChatSession.traffic_class == "real",
            )
        )
        appointments = await self._session.scalar(
            select(func.count())
            .select_from(Appointment)
            .where(
                Appointment.created_at >= start,
                Appointment.created_at < end,
                Appointment.traffic_class == "real",
                Appointment.status == "confirmed",
            )
        )
        active_users = await self._session.scalar(
            select(func.count(func.distinct(AuditEvent.actor_subject))).where(
                AuditEvent.created_at >= start,
                AuditEvent.created_at < end,
            )
        )
        return {
            "active_users": int(active_users or 0),
            "chat_sessions": int(sessions or 0),
            "chat_messages": int(messages or 0),
            "bookings_confirmed": int(appointments or 0),
        }

    async def audit_action_counts(self, *, start: dt.datetime, end: dt.datetime) -> dict[str, int]:
        rows = await self._session.execute(
            select(AuditEvent.action, func.count())
            .where(AuditEvent.created_at >= start, AuditEvent.created_at < end)
            .group_by(AuditEvent.action)
        )
        return {str(action): int(count) for action, count in rows}

    async def consent_counts(self) -> dict[str, int]:
        rows = await self._session.execute(
            select(Consent.status, func.count()).group_by(Consent.status)
        )
        counts = {"active": 0, "revoked": 0, "expired": 0}
        for status, count in rows:
            counts[str(status)] = int(count)
        return counts

    async def audit_total(self) -> int:
        return int(await self._session.scalar(select(func.count()).select_from(AuditEvent)) or 0)

    async def latest_audit_at(self) -> dt.datetime | None:
        return await self._session.scalar(select(func.max(AuditEvent.created_at)))

    async def role_activity(self, *, start: dt.datetime, end: dt.datetime) -> list[dict[str, Any]]:
        rows = await self._session.execute(
            select(AuditEvent.actor_role, func.count(func.distinct(AuditEvent.actor_subject)))
            .where(AuditEvent.created_at >= start, AuditEvent.created_at < end)
            .group_by(AuditEvent.actor_role)
            .order_by(func.count(func.distinct(AuditEvent.actor_subject)).desc())
        )
        return [{"role": row[0], "active_users": int(row[1])} for row in rows]

    async def recent_audit(self, limit: int = 20) -> list[AuditEvent]:
        rows = await self._session.scalars(
            select(AuditEvent).order_by(AuditEvent.created_at.desc()).limit(limit)
        )
        return list(rows)

    async def load_guard(
        self,
        *,
        start: dt.datetime,
        end: dt.datetime,
        exclude_subjects: set[str],
    ) -> dict[str, Any]:
        # Background jobs (notification dispatch, seeding) are not real users.
        real_actor = and_(
            AuditEvent.actor_subject.not_like("system:%"),
            AuditEvent.actor_subject.not_like("bootstrap:%"),
        )
        activity = select(func.count(AuditEvent.id)).where(
            AuditEvent.created_at >= start,
            AuditEvent.created_at < end,
            real_actor,
        )
        actors = select(func.count(func.distinct(AuditEvent.actor_subject))).where(
            AuditEvent.created_at >= start,
            AuditEvent.created_at < end,
            real_actor,
        )
        if exclude_subjects:
            activity = activity.where(AuditEvent.actor_subject.notin_(exclude_subjects))
            actors = actors.where(AuditEvent.actor_subject.notin_(exclude_subjects))
        real_events = int(await self._session.scalar(activity) or 0)
        real_actors = int(await self._session.scalar(actors) or 0)
        usage = (
            await self._session.execute(
                select(
                    func.coalesce(func.sum(UsageRecord.cost_usd), 0.0),
                    func.count(UsageRecord.id),
                ).where(
                    UsageRecord.created_at >= start,
                    UsageRecord.created_at < end,
                    UsageRecord.traffic_class == "synthetic",
                )
            )
        ).one()
        return {
            "real_events": real_events,
            "real_actors": real_actors,
            "synthetic_cost_usd": round(float(usage[0]), 6),
            "synthetic_calls": int(usage[1]),
        }
