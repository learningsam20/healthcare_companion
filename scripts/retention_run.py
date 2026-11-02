#!/usr/bin/env python3
"""Retention evidence runner for the jobs implemented in this build.

Dry-run is the default. Live mode reuses the scheduled worker functions so the
manual run and the cron path cannot drift. Clinical notes, audit events and eval
artefacts are never purged automatically; the report states which policies are
manual/deferred.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Any

from sqlalchemy import func, select, text

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages" / "py-common"))

from app.composition import build_app_services  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.repositories.audit import AuditRepository  # noqa: E402
from app.repositories.models import (  # noqa: E402
    ChatSession,
    Consent,
    DataDeletionRequest,
    Transcript,
)
from app.worker import (  # noqa: E402
    delete_expired_audio,
    expire_consents,
    process_deletion_requests,
    purge_expired_chat_sessions,
)
from sahyog_common.logging import configure_logging  # noqa: E402


def _cutoffs(services: Any) -> dict[str, dt.datetime]:
    retention = services.app_config.get("retention", {})
    now = dt.datetime.now(dt.UTC)
    return {
        "chat": now - dt.timedelta(days=int(retention.get("chat_days", 30))),
        "audio": now - dt.timedelta(hours=int(retention.get("audio_hours", 24))),
        "notification": now
        - dt.timedelta(days=int(retention.get("notification_delivery_days", 90))),
        "audit": now - dt.timedelta(days=int(retention.get("audit_days", 365))),
        "notes": now - dt.timedelta(days=int(retention.get("notes_days", 365))),
        "now": now,
    }


async def _dry_run(services: Any, cutoffs: dict[str, dt.datetime]) -> dict[str, int]:
    async with services.db.sessionmaker() as session:
        chat_candidates = int(
            await session.scalar(
                select(func.count())
                .select_from(ChatSession)
                .where(
                    ChatSession.updated_at < cutoffs["chat"],
                    ChatSession.status == "active",
                )
            )
            or 0
        )
        audio_candidates = int(
            await session.scalar(
                select(func.count())
                .select_from(Transcript)
                .where(
                    Transcript.object_key.is_not(None),
                    Transcript.audio_deleted_at.is_(None),
                    Transcript.created_at <= cutoffs["audio"],
                )
            )
            or 0
        )
        consent_candidates = int(
            await session.scalar(
                select(func.count())
                .select_from(Consent)
                .where(
                    Consent.status == "active",
                    Consent.expires_at.is_not(None),
                    Consent.expires_at <= cutoffs["now"],
                )
            )
            or 0
        )
        old_deliveries = int(
            await session.scalar(
                text(
                    "SELECT count(*) FROM notification_deliveries "
                    "WHERE created_at < :cutoff "
                    "AND status IN ('sent','failed','suppressed')"
                ),
                {"cutoff": cutoffs["notification"]},
            )
            or 0
        )
        deletion_requests = int(
            await session.scalar(
                select(func.count())
                .select_from(DataDeletionRequest)
                .where(
                    DataDeletionRequest.status == "pending",
                    DataDeletionRequest.scheduled_for <= cutoffs["now"],
                )
            )
            or 0
        )
    return {
        "chat_sessions": chat_candidates,
        "audio_objects": audio_candidates,
        "consents": consent_candidates,
        "notification_deliveries": old_deliveries,
        "deletion_requests": deletion_requests,
    }


async def _prune_deliveries(services: Any, cutoff: dt.datetime) -> int:
    async with services.db.sessionmaker() as session:
        result = await session.execute(
            text(
                "DELETE FROM notification_deliveries "
                "WHERE created_at < :cutoff "
                "AND status IN ('sent','failed','suppressed')"
            ),
            {"cutoff": cutoff},
        )
        deleted = int(result.rowcount or 0)
        AuditRepository(session).append(
            actor_subject="system:retention",
            actor_role="service",
            action="retention.notification_deliveries_pruned",
            resource_type="notification_delivery",
            metadata={"count": deleted, "cutoff": cutoff.isoformat()},
        )
        await session.commit()
    return deleted


async def _audit_summary(services: Any, report: dict[str, Any]) -> None:
    async with services.db.sessionmaker() as session:
        AuditRepository(session).append(
            actor_subject="system:retention",
            actor_role="service",
            action="retention.run",
            resource_type="retention_run",
            metadata=report,
        )
        await session.commit()


async def main_async(args: argparse.Namespace) -> dict[str, Any]:
    settings = get_settings()
    settings.validate_startup()
    configure_logging(settings.log_level)
    services = build_app_services(settings)
    cutoffs = _cutoffs(services)
    report: dict[str, Any] = {
        "mode": "live" if args.live else "dry_run",
        "as_of": cutoffs["now"].isoformat(),
        "cutoffs": {key: value.isoformat() for key, value in cutoffs.items() if key != "now"},
        "manual_or_deferred": [
            "signed clinical notes (notes_days) require the clinical retention runbook",
            "audit events (audit_days) are append-only and are not deleted by this tool",
            "mem0 inactivity, Langfuse metadata and eval artefacts have their own stores",
        ],
    }
    try:
        if args.live:
            report["chat_sessions"] = await purge_expired_chat_sessions({"services": services})
            report["audio_objects"] = await delete_expired_audio({"services": services})
            report["consents"] = await expire_consents({"services": services})
            report["notification_deliveries"] = await _prune_deliveries(
                services, cutoffs["notification"]
            )
            report["deletion_requests"] = await process_deletion_requests(
                {"services": services}
            )
        else:
            report["would_delete"] = await _dry_run(services, cutoffs)
            report["status"] = "dry_run"
            return report
        await _audit_summary(services, report)
        report["status"] = "live_run"
        return report
    finally:
        await services.db.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="Count candidates (default)")
    mode.add_argument("--live", action="store_true", help="Execute the implemented purges")
    parser.add_argument("--confirm", action="store_true", help="Required with --live")
    args = parser.parse_args()
    if args.live and not args.confirm:
        print("error: --live requires --confirm", file=sys.stderr)
        return 2
    try:
        result = asyncio.run(main_async(args))
    except Exception as exc:  # noqa: BLE001 - operator-facing failure
        print(f"error: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
