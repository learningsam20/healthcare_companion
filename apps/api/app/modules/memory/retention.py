"""G-24: retention for preference memory, driven by admin governance settings.

Reads ``memory_retention_days`` / ``chat_retention_days`` from ``governance_settings``
(written by ``PATCH /api/v1/admin/governance``). This module only *reads* governance
state; attestation and the admin compliance endpoints are owned elsewhere.
"""

from __future__ import annotations

import datetime as dt
import logging
from typing import Any

from app.core.services import Services
from app.repositories.audit import AuditRepository
from app.repositories.models import GovernanceSetting, MemoryPreference
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

MEMORY_RETENTION_KEY = "memory_retention_days"
CHAT_RETENTION_KEY = "chat_retention_days"
DEFAULT_MEMORY_RETENTION_DAYS = 180


async def governance_override_days(session: AsyncSession, key: str) -> int | None:
    """Admin-set retention days, or ``None`` when no valid row exists for ``key``."""
    row = await session.get(GovernanceSetting, key)
    if row is None or not isinstance(row.value, dict):
        return None
    raw = row.value.get("value")
    if isinstance(raw, bool):
        return None
    try:
        days = int(raw)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return days if 1 <= days <= 3650 else None


async def effective_chat_retention_days(session: AsyncSession, config_days: int) -> int:
    """Chat retention = the stricter of deploy config and an explicit admin override.

    Governance can shorten chat retention below ``config/app.yaml`` but never lengthen
    it: the page default (365) must not silently relax the 30-day deployment baseline.
    """
    override = await governance_override_days(session, CHAT_RETENTION_KEY)
    return min(config_days, override) if override is not None else config_days


async def effective_memory_retention_days(session: AsyncSession) -> tuple[int, str]:
    override = await governance_override_days(session, MEMORY_RETENTION_KEY)
    if override is not None:
        return override, "governance"
    return DEFAULT_MEMORY_RETENTION_DAYS, "default"


async def purge_expired_memory_preferences(
    services: Services, *, now: dt.datetime | None = None
) -> dict[str, Any]:
    """Delete preference rows untouched for longer than the retention window (+ Mem0)."""
    from app.modules.analytics.jobs import _job
    from app.modules.memory.router import _sync_mem0_delete

    current = now or dt.datetime.now(dt.UTC)
    async with _job(services, "memory.retention") as (session, run):
        days, source = await effective_memory_retention_days(session)
        cutoff = current - dt.timedelta(days=days)
        rows = list(
            await session.scalars(
                select(MemoryPreference).where(MemoryPreference.updated_at < cutoff)
            )
        )
        subjects: set[str] = set()
        purged_keys: list[tuple[str, str]] = []
        for row in rows:
            subjects.add(row.subject)
            purged_keys.append((row.subject, row.key))
            await session.delete(row)
        if rows:
            AuditRepository(session).append(
                actor_subject="system:retention",
                actor_role="service",
                action="retention.memory_purged",
                resource_type="memory_preference",
                metadata={
                    "count": len(rows),
                    "subjects": len(subjects),
                    "retention_days": days,
                    "source": source,
                    "cutoff": cutoff.isoformat(),
                    "provenance": "not_clinical_evidence",
                },
            )
        detail = {
            "retention_days": days,
            "source": source,
            "cutoff": cutoff.isoformat(),
            "purged": len(rows),
        }
        run.detail = detail
    # Mem0 is best-effort after the Postgres commit; failures are logged, never raised.
    for subject, key in purged_keys:
        await _sync_mem0_delete(services, subject=subject, key=key)
    logger.info(
        "memory retention run",
        extra={"event": "retention.memory", "extra_fields": detail},
    )
    return detail
