"""G-07: contact re-verification job decision + scheduler wiring."""

from __future__ import annotations

import asyncio
import datetime as dt
import uuid

from app.modules.notifications.jobs import channel_due_for_reverify
from app.repositories.models import ContactChannel
from app.repositories.notifications import ContactChannelRepository
from app.scheduler import WorkerSettings, contact_reverification_job
from sqlalchemy.dialects import postgresql


def test_channel_due_when_verified_at_older_than_180_days() -> None:
    now = dt.datetime(2026, 10, 31, tzinfo=dt.UTC)
    contact = ContactChannel(
        id=uuid.uuid4(),
        subject="patient-1",
        channel="slack_patient",
        address="U123",
        verified=True,
        opt_in=True,
        verified_at=now - dt.timedelta(days=200),
    )
    assert channel_due_for_reverify(contact, now=now, max_days=180) is True


def test_channel_not_due_when_recently_verified() -> None:
    now = dt.datetime(2026, 10, 31, tzinfo=dt.UTC)
    contact = ContactChannel(
        id=uuid.uuid4(),
        subject="patient-1",
        channel="email",
        address="a@example.com",
        verified=True,
        opt_in=True,
        verified_at=now - dt.timedelta(days=30),
    )
    assert channel_due_for_reverify(contact, now=now, max_days=180) is False


def test_scheduler_registers_contact_reverification_cron() -> None:
    names = {fn.__name__ for fn in WorkerSettings.functions}
    assert "contact_reverification_job" in names
    cron_names = {job.coroutine.__name__ for job in WorkerSettings.cron_jobs}
    assert "contact_reverification_job" in cron_names
    assert contact_reverification_job.__name__ == "contact_reverification_job"


def test_list_due_sql_filters_verified_at() -> None:
    captured: list[object] = []

    class _Session:
        async def scalars(self, statement: object) -> list[ContactChannel]:
            captured.append(statement)
            return []

    repo = ContactChannelRepository(_Session())  # type: ignore[arg-type]
    cutoff = dt.datetime(2026, 5, 1, tzinfo=dt.UTC)
    asyncio.run(repo.list_due_for_reverification(cutoff=cutoff))
    assert len(captured) == 1
    compiled = captured[0].compile(dialect=postgresql.dialect())  # type: ignore[attr-defined]
    sql = str(compiled)
    assert "verified" in sql.lower()
    assert "verified_at" in sql.lower()
