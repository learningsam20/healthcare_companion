"""Shared post-score side effects for no-show risk (waitlist handoff)."""

from __future__ import annotations

import logging
import uuid
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.services import Services
from app.modules.scheduling.no_show import NoShowScore, apply_no_show_score
from app.repositories.models import Appointment

logger = logging.getLogger(__name__)


async def score_and_act(
    session: AsyncSession,
    appointment: Appointment,
    *,
    services: Services | None = None,
    actor_subject: str = "system:scheduling",
    actor_role: str = "service",
    locale: str = "en-IN",
    trace_id: str | None = None,
    consent_id: uuid.UUID | None = None,
) -> NoShowScore:
    """Score appointment and open a waitlist desk ticket when risk is high."""
    scored = await apply_no_show_score(session, appointment)
    if services is None or not scored.waitlist_suggested:
        return scored
    try:
        from app.modules.handoffs.service import create_staff_handoff

        await create_staff_handoff(
            session,
            services,
            patient_id=appointment.patient_id,
            created_by_subject=actor_subject,
            actor_role=actor_role,
            clinic_code=appointment.clinic_code,
            reason="waitlist_suggestion",
            notes=(
                f"High no-show risk ({scored.risk:.0%}) for appointment {appointment.id}. "
                f"{appointment.doctor_name} @ {appointment.starts_at.isoformat()}. "
                "Consider offering this slot on the waitlist if unconfirmed."
            )[:500],
            resource_type="appointment",
            resource_id=str(appointment.id),
            rule_ids=["no_show_high"],
            priority="normal",
            trace_id=trace_id,
            consent_id=consent_id,
            locale=locale,
        )
    except Exception:  # noqa: BLE001
        logger.warning("waitlist handoff create failed", exc_info=True)
    return scored


def score_metadata(scored: NoShowScore) -> dict[str, Any]:
    return {
        "no_show_risk": scored.risk,
        "no_show_band": scored.band,
        "waitlist_suggested": scored.waitlist_suggested,
        "confirm_by_reply": scored.confirm_by_reply,
    }
