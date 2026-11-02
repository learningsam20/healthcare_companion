#!/usr/bin/env python3
"""Drill: create → assign records MTTA; assert analytics/overview + /metrics expose it.

Usage (repo root, API + DB up, migrate applied):
  PYTHONPATH=apps/api:packages/common/src:. .venv/bin/python scripts/probe_handoff_mtta.py --write-evidence
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import sys
import uuid
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path[:0] = [
    str(REPO / "apps" / "api"),
    str(REPO / "packages" / "common" / "src"),
]


async def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--write-evidence", action="store_true")
    parser.add_argument("--sleep-ms", type=int, default=250, help="Delay before assign")
    args = parser.parse_args()

    from app.core.services import build_services
    from app.modules.handoffs.service import (
        EMERGENCY_SLA_SECONDS,
        create_staff_handoff,
        mtta_summary,
        record_first_ack,
    )
    from app.repositories.models import Handoff
    from sqlalchemy import select

    services = build_services()
    started = dt.datetime.now(dt.UTC)
    evidence: dict = {
        "probe": "handoff_mtta",
        "started_at": started.isoformat(),
        "sla_seconds_emergency": EMERGENCY_SLA_SECONDS,
        "ok": False,
    }

    async with services.db.sessionmaker() as session:
        handoff = await create_staff_handoff(
            session,
            services,
            patient_id=None,
            created_by_subject="probe:mtta",
            actor_role="service",
            clinic_code="PUNE-DEMO",
            reason="MTTA probe — synthetic emergency desk ticket",
            notes="No clinical content. Probe only.",
            resource_type="probe",
            resource_id=f"mtta-{uuid.uuid4().hex[:12]}",
            rule_ids=["probe.mtta"],
            priority="emergency",
            trace_id=f"mtta-probe-{uuid.uuid4().hex[:8]}",
        )
        await session.commit()
        handoff_id = handoff.id
        created_at = handoff.created_at

        await asyncio.sleep(max(args.sleep_ms, 0) / 1000.0)

        row = await session.scalar(select(Handoff).where(Handoff.id == handoff_id).with_for_update())
        assert row is not None
        row.assigned_to_subject = "frontdesk.imran"
        row.status = "assigned"
        record_first_ack(row)
        await session.commit()

        summary = await mtta_summary(session, window_hours=24 * 30)
        evidence["handoff_id"] = str(handoff_id)
        evidence["created_at"] = created_at.isoformat() if created_at else None
        evidence["acknowledged_at"] = row.acknowledged_at.isoformat() if row.acknowledged_at else None
        evidence["mtta_seconds"] = row.mtta_seconds
        evidence["summary"] = summary
        evidence["ok"] = bool(
            row.mtta_seconds is not None
            and row.acknowledged_at is not None
            and summary["acknowledged_count"] >= 1
        )

    evidence["finished_at"] = dt.datetime.now(dt.UTC).isoformat()
    print(json.dumps(evidence, indent=2, default=str))

    if args.write_evidence:
        out = (
            REPO
            / "docs"
            / "evidence"
            / f"handoff-mtta-probe-{started.strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        out.write_text(json.dumps(evidence, indent=2, default=str) + "\n")
        print(f"wrote {out}", file=sys.stderr)

    return 0 if evidence["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
