#!/usr/bin/env python3
"""Re-apply demo email/Slack contacts (same logic as seed_demo).

Prefer `python scripts/seed_demo.py` — contacts are seeded there for every patient,
staff, and other demo user. This script is a thin re-map helper for local smoke.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent
sys.path.insert(0, str(ROOT / "apps" / "api"))
sys.path.insert(0, str(ROOT / "packages" / "py-common"))
sys.path.insert(0, str(SCRIPT_DIR))

from app.core.config import get_settings  # noqa: E402
from app.repositories.models import ContactChannel, Patient  # noqa: E402
from demo_contacts import enrich_demo_patients, planned_contacts  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

NOW = dt.datetime.now(dt.UTC)


async def main() -> int:
    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required")

    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    mapped: list[dict[str, object]] = []
    try:
        async with sessionmaker() as session:
            for item in enrich_demo_patients():
                patient = await session.get(Patient, item["id"])
                if patient is None:
                    continue
                patient.notify_email = item.get("notify_email")  # type: ignore[assignment]
                patient.slack_user_id = item.get("slack_user_id")  # type: ignore[assignment]

            for contact in planned_contacts(
                staff_workspace=settings.slack_staff_workspace_id,
                patient_workspace=settings.slack_patient_workspace_id,
            ):
                row = await session.scalar(
                    select(ContactChannel).where(
                        ContactChannel.subject == contact["subject"],
                        ContactChannel.channel == contact["channel"],
                    )
                )
                if row is None:
                    session.add(
                        ContactChannel(
                            id=uuid.uuid5(
                                uuid.NAMESPACE_URL,
                                f"sahyog:contact:{contact['subject']}:{contact['channel']}",
                            ),
                            subject=contact["subject"],
                            patient_id=contact["patient_id"],
                            channel=contact["channel"],
                            address=contact["address"],
                            verified=contact["verified"],
                            opt_in=contact["opt_in"],
                            workspace_id=contact["workspace_id"],
                            verified_at=NOW,
                        )
                    )
                else:
                    row.address = contact["address"]
                    row.patient_id = contact["patient_id"]
                    row.verified = contact["verified"]
                    row.opt_in = contact["opt_in"]
                    row.workspace_id = contact["workspace_id"]
                    row.verified_at = NOW
                mapped.append(
                    {
                        "username": contact.get("username"),
                        "role": contact.get("role"),
                        "channel": contact["channel"],
                        "address": contact["address"],
                        "subject": contact["subject"],
                    }
                )
            await session.commit()
    finally:
        await engine.dispose()
    print(json.dumps({"mapped": mapped, "count": len(mapped)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
