"""Scheduled + on-demand audit hash-chain verification (ADR-14)."""

from __future__ import annotations

import logging
from typing import Any

from app.core.services import Services
from app.modules.analytics.jobs import _job
from app.repositories.audit import AuditRepository
from app.repositories.models import JobRun
from sqlalchemy import select

logger = logging.getLogger(__name__)

JOB_NAME = "audit.verify_chain"


async def run_audit_chain_verify(services: Services) -> dict[str, Any]:
    """Verify per-row audit digests; record result in job_runs."""
    async with _job(services, JOB_NAME) as (session, run):
        result = await AuditRepository(session).verify_chain()
        run.detail = result
        if result["status"] == "broken":
            # Mark failed so SahyogJobFailures / ops UI surface a real digest break.
            raise RuntimeError(
                f"audit_chain_broken: broken_count={result['broken_count']} checked={result['checked']}"
            )
        if result["status"] == "gapped":
            logger.warning(
                "audit chain has prev_hash gaps with valid digests",
                extra={
                    "event": "audit.verify_chain",
                    "extra_fields": {
                        "status": result["status"],
                        "checked": result["checked"],
                        "gap_count": result["gap_count"],
                    },
                },
            )
            return result
        logger.info(
            "audit chain verify",
            extra={
                "event": "audit.verify_chain",
                "extra_fields": {
                    "status": result["status"],
                    "checked": result["checked"],
                    "unhashed": result["unhashed"],
                },
            },
        )
        return result


async def latest_verify_status(services: Services) -> dict[str, Any]:
    """Return the most recent audit.verify_chain job_runs row (or never_run)."""
    async with services.db.sessionmaker() as session:
        row = await session.scalar(
            select(JobRun)
            .where(JobRun.job_name == JOB_NAME)
            .order_by(JobRun.started_at.desc())
            .limit(1)
        )
        if row is None:
            return {
                "status": "never_run",
                "job_status": None,
                "started_at": None,
                "finished_at": None,
                "detail": {},
                "error_code": None,
            }
        detail = row.detail if isinstance(row.detail, dict) else {}
        chain_status = detail.get("status")
        if row.status == "failed":
            chain_status = chain_status or "broken"
        return {
            "status": chain_status or row.status,
            "job_status": row.status,
            "started_at": row.started_at.isoformat() if row.started_at else None,
            "finished_at": row.finished_at.isoformat() if row.finished_at else None,
            "detail": detail,
            "error_code": row.error_code,
        }
