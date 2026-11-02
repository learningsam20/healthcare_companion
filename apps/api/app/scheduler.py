"""ARQ cron worker for retention and consent expiry (core/full profiles).

Notification dispatch stays on the always-on worker so the minimal profile still
delivers or suppresses queued messages truthfully. Retention jobs are separated so a
minimal developer stack does not silently destroy data on a schedule.
"""

from __future__ import annotations

from typing import Any

from arq import cron
from arq.connections import RedisSettings

from app.core.config import get_settings
from app.modules.analytics.jobs import (
    capture_snapshot,
    check_staleness,
    create_audit_anchor,
    generate_insights,
    run_finops_reconciliation,
)
from app.modules.notifications.jobs import scan_contact_reverification
from app.modules.ops.audit_verify import run_audit_chain_verify
from app.modules.ops.jobs import run_scheduled_backup
from app.worker import (
    delete_expired_audio,
    expire_consents,
    purge_expired_chat_sessions,
    purge_expired_memory,
    shutdown,
    startup,
)


async def analytics_snapshot_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await capture_snapshot(ctx["services"])


async def analytics_insights_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await generate_insights(ctx["services"])


async def analytics_anchor_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await create_audit_anchor(ctx["services"])


async def analytics_staleness_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await check_staleness(ctx["services"])


async def finops_reconcile_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await run_finops_reconciliation(ctx["services"])


async def contact_reverification_job(ctx: dict[str, Any]) -> dict[str, Any]:
    return await scan_contact_reverification(ctx["services"])


async def scheduled_backup_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """Daily backup stub — fails visibly when BACKUP_OUT_DIR is unset (G-30)."""
    return await run_scheduled_backup(ctx["services"])


async def handoff_sla_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """Escalate open handoffs past sla_due_at (Wave F / G-48)."""
    from app.modules.handoffs.service import mark_overdue_handoffs

    services = ctx["services"]
    async with services.db.sessionmaker() as session:
        result = await mark_overdue_handoffs(session, services)
        await session.commit()
        return result


async def audit_verify_job(ctx: dict[str, Any]) -> dict[str, Any]:
    """Hourly ADR-14 hash-chain walk; fails job_runs when digests break."""
    return await run_audit_chain_verify(ctx["services"])


class WorkerSettings:
    functions = [
        delete_expired_audio,
        purge_expired_chat_sessions,
        purge_expired_memory,
        expire_consents,
        analytics_snapshot_job,
        analytics_insights_job,
        analytics_anchor_job,
        analytics_staleness_job,
        finops_reconcile_job,
        contact_reverification_job,
        scheduled_backup_job,
        handoff_sla_job,
        audit_verify_job,
    ]
    cron_jobs = [
        cron(delete_expired_audio, minute=set(range(0, 60, 15))),
        cron(purge_expired_chat_sessions, hour=2, minute=15),
        cron(purge_expired_memory, hour=2, minute=20),
        cron(expire_consents, hour=2, minute=30),
        cron(analytics_snapshot_job, minute=5),
        cron(finops_reconcile_job, minute=10),
        cron(analytics_staleness_job, minute=20),
        cron(analytics_insights_job, hour=3, minute=10),
        cron(analytics_anchor_job, hour=2, minute=45),
        # Host-oriented backup: records failed job_runs until BACKUP_OUT_DIR is set.
        cron(scheduled_backup_job, hour=4, minute=5),
        cron(contact_reverification_job, hour=4, minute=25),
        # Emergency handoff SLA: every minute.
        cron(handoff_sla_job, minute=set(range(0, 60))),
        # Audit hash-chain integrity (ADR-14).
        cron(audit_verify_job, hour=set(range(0, 24)), minute={40}),
    ]
    queue_name = get_settings().arq_scheduler_queue
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    on_startup = startup
    on_shutdown = shutdown
    max_burst_jobs = 4
    job_timeout = 300
    keep_result = 3600
