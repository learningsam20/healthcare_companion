#!/usr/bin/env python3
"""G-07: list contacts due for re-verification (verified_at older than max_days).

Modes:
  --fixture FILE   offline JSON helper (no database)
  --database       query ContactChannel via DATABASE_URL and print a report
                   (cron-callable; does not write job_runs — use the ARQ scheduler
                   job notifications.contact_reverification for audited runs)
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
ROOT = SCRIPT_DIR.parent


def due_for_reverify(
    *,
    verified_at: datetime | None,
    verified: bool,
    now: datetime,
    max_days: int,
) -> bool:
    if not verified or verified_at is None:
        return False
    if verified_at.tzinfo is None:
        verified_at = verified_at.replace(tzinfo=UTC)
    return verified_at <= now - timedelta(days=max_days)


async def scan_database(*, max_days: int) -> dict[str, object]:
    sys.path.insert(0, str(ROOT / "apps" / "api"))
    sys.path.insert(0, str(ROOT / "packages" / "py-common"))
    from app.core.config import get_settings  # noqa: E402
    from app.repositories.notifications import ContactChannelRepository  # noqa: E402
    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

    settings = get_settings()
    if not settings.database_url:
        raise SystemExit("DATABASE_URL is required for --database")
    now = datetime.now(UTC)
    cutoff = now - timedelta(days=max_days)
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    sessionmaker = async_sessionmaker(engine, expire_on_commit=False)
    try:
        async with sessionmaker() as session:
            rows = await ContactChannelRepository(session).list_due_for_reverification(
                cutoff=cutoff
            )
            due_ids = [str(row.id) for row in rows]
            return {
                "max_days": max_days,
                "cutoff": cutoff.isoformat(),
                "scanned_due": len(due_ids),
                "due_ids": due_ids,
                "status": "ok",
                "mode": "database",
                "note": (
                    "Cron-callable scan. Prefer ARQ contact_reverification_job for "
                    "job_runs + audit; this path is read-only reporting."
                ),
            }
    finally:
        await engine.dispose()


def scan_fixture(rows: list[dict[str, object]], *, max_days: int) -> dict[str, object]:
    now = datetime.now(UTC)
    due: list[object] = []
    for row in rows:
        verified_at = row.get("verified_at")
        parsed = (
            datetime.fromisoformat(str(verified_at).replace("Z", "+00:00"))
            if verified_at
            else None
        )
        if due_for_reverify(
            verified_at=parsed,
            verified=bool(row.get("verified")),
            now=now,
            max_days=max_days,
        ):
            due.append(row.get("id"))
    return {
        "max_days": max_days,
        "scanned": len(rows),
        "due_ids": due,
        "status": "ok",
        "mode": "fixture",
        "note": "Offline decision helper; wire to ContactChannel via --database or ARQ.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-days", type=int, default=180)
    parser.add_argument(
        "--fixture",
        type=argparse.FileType("r"),
        help="JSON list of {id,verified,verified_at}",
    )
    parser.add_argument(
        "--database",
        action="store_true",
        help="Query ContactChannel via DATABASE_URL (cron-callable)",
    )
    parser.add_argument("--out", type=argparse.FileType("w"), default="-")
    args = parser.parse_args()
    if args.database and args.fixture:
        parser.error("choose either --database or --fixture, not both")
    if args.database:
        report = asyncio.run(scan_database(max_days=args.max_days))
    else:
        rows: list[dict[str, object]] = []
        if args.fixture:
            rows = json.load(args.fixture)
        report = scan_fixture(rows, max_days=args.max_days)
    args.out.write(json.dumps(report, indent=2, sort_keys=True) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
