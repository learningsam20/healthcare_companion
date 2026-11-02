from __future__ import annotations

import datetime as dt
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import (
    ContactChannel,
    Notification,
    NotificationDelivery,
)

SORT_COLUMNS = {
    "created_at": Notification.created_at,
    "status": Notification.status,
    "template_id": Notification.template_id,
}


class NotificationRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_grid(
        self,
        *,
        recipient_subject: str | None,
        status: str | None,
        channel: str | None,
        query: str | None,
        sort: str,
        descending: bool,
        limit: int,
        offset: int,
    ) -> tuple[list[Notification], int]:
        conditions = []
        if recipient_subject is not None:
            conditions.append(Notification.recipient_subject == recipient_subject)
        if status == "unread":
            conditions.append(Notification.status != "read")
        elif status:
            conditions.append(Notification.status == status)
        if channel:
            conditions.append(Notification.channel == channel)
        if query:
            pattern = f"%{query.strip()}%"
            conditions.append(
                or_(Notification.title.ilike(pattern), Notification.template_id.ilike(pattern))
            )
        column = SORT_COLUMNS.get(sort, Notification.created_at)
        order = column.desc() if descending else column.asc()
        total = await self._session.scalar(
            select(func.count()).select_from(Notification).where(*conditions)
        )
        rows = await self._session.scalars(
            select(Notification)
            .where(*conditions)
            .order_by(order, Notification.id)
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def unread_count(self, recipient_subject: str | None) -> int:
        conditions = [Notification.status != "read"]
        if recipient_subject is not None:
            conditions.append(Notification.recipient_subject == recipient_subject)
        count = await self._session.scalar(
            select(func.count()).select_from(Notification).where(*conditions)
        )
        return int(count or 0)

    async def get(self, notification_id: uuid.UUID) -> Notification | None:
        return await self._session.get(Notification, notification_id)

    async def mark_read(self, notification: Notification) -> None:
        if notification.status != "read":
            notification.status = "read"
            notification.read_at = dt.datetime.now(dt.UTC)
            await self._session.flush()

    async def deliveries(self, notification_id: uuid.UUID) -> list[NotificationDelivery]:
        rows = await self._session.scalars(
            select(NotificationDelivery)
            .where(NotificationDelivery.notification_id == notification_id)
            .order_by(NotificationDelivery.created_at)
        )
        return list(rows)

    async def due_deliveries(
        self, *, now: dt.datetime, limit: int = 50
    ) -> list[NotificationDelivery]:
        rows = await self._session.scalars(
            select(NotificationDelivery)
            .where(
                NotificationDelivery.status == "queued",
                NotificationDelivery.scheduled_at <= now,
            )
            .order_by(NotificationDelivery.scheduled_at)
            .limit(limit)
        )
        return list(rows)

    async def update_delivery(
        self,
        delivery: NotificationDelivery,
        *,
        status: str,
        attempts: int,
        error_code: str | None = None,
        provider_message_id: str | None = None,
        scheduled_at: dt.datetime | None = None,
    ) -> None:
        delivery.status = status
        delivery.attempts = attempts
        delivery.last_error_code = error_code
        delivery.provider_message_id = provider_message_id
        if scheduled_at is not None:
            delivery.scheduled_at = scheduled_at
        if status == "sent":
            delivery.sent_at = dt.datetime.now(dt.UTC)
        await self._session.flush()


class ContactChannelRepository:
    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def find(
        self, *, subject: str, channel: str, patient_id: uuid.UUID | None = None
    ) -> ContactChannel | None:
        row = await self._session.scalar(
            select(ContactChannel).where(
                ContactChannel.subject == subject,
                ContactChannel.channel == channel,
            )
        )
        if row is not None or patient_id is None:
            return row
        return await self._session.scalar(
            select(ContactChannel).where(
                ContactChannel.patient_id == patient_id,
                ContactChannel.channel == channel,
            )
        )

    async def list(
        self, *, subject: str | None, limit: int, offset: int
    ) -> tuple[list[ContactChannel], int]:
        conditions = []
        if subject:
            conditions.append(ContactChannel.subject == subject)
        total = await self._session.scalar(
            select(func.count()).select_from(ContactChannel).where(*conditions)
        )
        rows = await self._session.scalars(
            select(ContactChannel)
            .where(*conditions)
            .order_by(ContactChannel.created_at.desc())
            .limit(limit)
            .offset(offset)
        )
        return list(rows), int(total or 0)

    async def list_due_for_reverification(
        self, *, cutoff: dt.datetime, limit: int = 5000
    ) -> list[ContactChannel]:
        """Verified contacts whose verified_at is on or before cutoff (G-07)."""
        rows = await self._session.scalars(
            select(ContactChannel)
            .where(
                ContactChannel.verified.is_(True),
                ContactChannel.verified_at.is_not(None),
                ContactChannel.verified_at <= cutoff,
            )
            .order_by(ContactChannel.verified_at.asc())
            .limit(limit)
        )
        return list(rows)

    async def upsert(self, contact: ContactChannel) -> ContactChannel:
        existing = await self._session.scalar(
            select(ContactChannel).where(
                ContactChannel.subject == contact.subject,
                ContactChannel.channel == contact.channel,
            )
        )
        if existing is None:
            self._session.add(contact)
            await self._session.flush()
            return contact
        existing.address = contact.address
        existing.patient_id = contact.patient_id
        existing.verified = contact.verified
        existing.opt_in = contact.opt_in
        existing.workspace_id = contact.workspace_id
        existing.verified_at = contact.verified_at
        await self._session.flush()
        return existing
