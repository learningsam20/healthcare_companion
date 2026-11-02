#!/usr/bin/env python3
"""Prove email + Slack staff delivery (G-06) through real adapters.

Sends:
  1) Direct adapter probes (SMTP + Slack Web API)
  2) NotificationService ops_alert for NOTIFY_OPS_SUBJECT (queues email + slack_staff)
  3) Waits for ARQ worker dispatch and records delivery statuses

Writes docs/evidence/notify-channels-probe-<ts>.json when --write-evidence.

Usage (repo root, stack up, worker running):
  PYTHONPATH=apps/api:packages/common/src:. .venv/bin/python scripts/probe_notify_channels.py --write-evidence
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import os
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(REPO / "apps" / "api"),
    str(REPO / "packages" / "common" / "src"),
    str(REPO / "scripts"),
]


async def _direct_probes(settings) -> dict:
    from app.integrations.notifications import EmailAdapter, SlackAdapter

    out: dict = {"email": {"ok": False}, "slack_staff": {"ok": False}}
    email_to = (
        os.environ.get("TEST_STAFF_EMAIL")
        or os.environ.get("EMAIL_FROM")
        or settings.email_from
    ).strip()
    allowed = [
        part.strip()
        for part in (settings.slack_allowed_channels or "").split(",")
        if part.strip()
    ]
    slack_to = (
        os.environ.get("TEST_STAFF_SLACK_ID")
        or (allowed[0] if allowed else "")
        or "C0CEKMA92EL"
    ).strip()

    email = EmailAdapter(settings)
    if email.configured() and email_to:
        try:
            mid = await email.send(
                address=email_to,
                subject="Sahyog notify probe (email)",
                body="Direct SMTP probe — no clinical content.",
            )
            out["email"] = {"ok": True, "provider_message_id": mid, "to": email_to}
        except Exception as exc:  # noqa: BLE001
            out["email"] = {"ok": False, "error": type(exc).__name__, "code": getattr(exc, "code", None)}
    else:
        out["email"] = {"ok": False, "error": "unconfigured"}

    slack = SlackAdapter(settings)
    if slack.configured("slack_staff") and slack_to:
        try:
            mid = await slack.send(
                channel="slack_staff",
                address=slack_to,
                text="*Sahyog notify probe (Slack)*\nDirect Web API probe — no clinical content.",
            )
            out["slack_staff"] = {"ok": True, "provider_message_id": mid, "to": slack_to}
        except Exception as exc:  # noqa: BLE001
            out["slack_staff"] = {
                "ok": False,
                "error": type(exc).__name__,
                "code": getattr(exc, "code", None),
            }
    else:
        out["slack_staff"] = {"ok": False, "error": "unconfigured"}
    return out


async def _service_queue_and_wait(services, *, subject: str, timeout_s: float = 45.0) -> dict:
    from app.modules.notifications.service import NotificationService
    from app.repositories.notifications import NotificationRepository
    from sqlalchemy import select
    from app.repositories.models import NotificationDelivery

    async with services.db.sessionmaker() as session:
        service = NotificationService(services, session)
        notification, deliveries = await service.send(
            template_id="ops_alert",
            recipient_subject=subject,
            recipient_role="front_desk",
            patient_id=None,
            locale="en-IN",
            data={"alert": f"Notify channel probe {uuid.uuid4().hex[:8]}"},
            actor_subject="probe_notify_channels",
            actor_role="service",
            requested_channels=["in_app", "email", "slack_staff"],
            emergency=True,
        )
        await session.commit()
        notification_id = notification.id
        queued = [
            {"channel": d.channel, "status": d.status, "error": d.last_error_code}
            for d in deliveries
        ]

    # Kick the worker immediately (do not wait for the per-minute cron).
    try:
        from arq import create_pool
        from arq.connections import RedisSettings

        redis_url = os.environ.get("REDIS_URL") or services.settings.redis_url
        queue_name = services.settings.arq_worker_queue
        pool = await create_pool(RedisSettings.from_dsn(redis_url))
        await pool.enqueue_job("dispatch_pending_notifications", _queue_name=queue_name)
        await pool.aclose()
    except Exception as exc:  # noqa: BLE001
        queued.append({"enqueue_error": type(exc).__name__, "detail": str(exc)[:160]})

    deadline = dt.datetime.now(dt.UTC) + dt.timedelta(seconds=timeout_s)
    final: list[dict] = []
    while dt.datetime.now(dt.UTC) < deadline:
        async with services.db.sessionmaker() as session:
            rows = (
                await session.scalars(
                    select(NotificationDelivery).where(
                        NotificationDelivery.notification_id == notification_id
                    )
                )
            ).all()
            final = [
                {
                    "channel": r.channel,
                    "status": r.status,
                    "error": r.last_error_code,
                    "provider_message_id": r.provider_message_id,
                    "attempts": r.attempts,
                }
                for r in rows
            ]
            if final and all(r["status"] in {"sent", "failed", "suppressed"} for r in final):
                break
        await asyncio.sleep(1.5)

    sent = {r["channel"] for r in final if r["status"] == "sent"}
    return {
        "notification_id": str(notification_id),
        "queued": queued,
        "final": final,
        "email_sent": "email" in sent,
        "slack_staff_sent": "slack_staff" in sent,
    }


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--skip-queue", action="store_true", help="Only direct adapter probes")
    args = parser.parse_args()

    from app.core.vault import apply_secrets

    apply_secrets(force=True)

    # Host runs resolve Compose service DNS via published ports.
    db = os.environ.get("DATABASE_URL", "")
    pg_port = os.environ.get("POSTGRES_PORT", "5724").strip() or "5724"
    if "@postgres:" in db:
        os.environ["DATABASE_URL"] = db.replace("@postgres:5432", f"@127.0.0.1:{pg_port}")
    redis = os.environ.get("REDIS_URL", "")
    redis_port = os.environ.get("REDIS_PORT", "5725").strip() or "5725"
    if "://redis:" in redis:
        os.environ["REDIS_URL"] = redis.replace("://redis:", f"://127.0.0.1:")
        # keep redis path/db; only rewrite host if default compose name
        os.environ["REDIS_URL"] = (
            os.environ["REDIS_URL"]
            .replace("://127.0.0.1:6379", f"://127.0.0.1:{redis_port}")
        )

    from app.composition import build_app_services
    from app.core.config import Settings, get_settings

    get_settings.cache_clear()
    settings = Settings()
    services = build_app_services(settings)
    ops = (settings.notify_ops_subject or "").strip()

    result: dict = {
        "status": "failed",
        "generated_at": dt.datetime.now(dt.UTC).isoformat(),
        "notify_send_external": settings.notify_send_external,
        "notify_ops_subject_set": bool(ops),
        "adapters": {
            "email": settings.smtp_configured,
            "slack_staff": settings.slack_staff_configured,
            "sms": settings.sms_configured,
            "sms_feature_default_off": True,
        },
        "direct": {},
        "queued": {},
        "closes_gap": {"G-06_email_slack": False},
    }

    result["direct"] = await _direct_probes(settings)
    if not args.skip_queue:
        if not ops:
            result["queued"] = {"error": "NOTIFY_OPS_SUBJECT unset"}
        elif not settings.notify_send_external:
            result["queued"] = {"error": "NOTIFY_SEND_EXTERNAL=false"}
        else:
            result["queued"] = await _service_queue_and_wait(services, subject=ops)

    email_ok = bool(result["direct"].get("email", {}).get("ok"))
    slack_ok = bool(result["direct"].get("slack_staff", {}).get("ok"))
    queued = result.get("queued") or {}
    queue_email = bool(queued.get("email_sent"))
    queue_slack = bool(queued.get("slack_staff_sent"))
    # Prefer full-path success; accept direct probe if queue skipped.
    if args.skip_queue:
        result["closes_gap"]["G-06_email_slack"] = email_ok and slack_ok
    else:
        result["closes_gap"]["G-06_email_slack"] = (email_ok and slack_ok) and (
            queue_email and queue_slack
        )
    result["status"] = "passed" if result["closes_gap"]["G-06_email_slack"] else "failed"
    result["caveat_sms"] = (
        "SMS remains optional (FEATURE notifications_sms default false / channel disabled). "
        "Email + Slack staff are the required ship channels."
    )

    print(json.dumps(result, indent=2))
    if args.write_evidence:
        ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
        out = REPO / "docs" / "evidence" / f"notify-channels-probe-{ts}.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
        print(f"wrote {out}", file=sys.stderr)
    return 0 if result["status"] == "passed" else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
