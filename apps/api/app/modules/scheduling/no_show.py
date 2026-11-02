"""Heuristic no-show risk scorer for bookings (W1 innovation).

Uses lead time, prior no-shows, weekday/hour priors — no cloud ML dependency.
Bands: low < 0.35, medium < 0.55, high ≥ 0.55.
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.models import Appointment

HIGH_THRESHOLD = 0.55
MEDIUM_THRESHOLD = 0.35


@dataclass(frozen=True, slots=True)
class NoShowScore:
    risk: float
    band: str
    waitlist_suggested: bool
    confirm_by_reply: bool
    features: dict[str, Any]


def _sigmoid(x: float) -> float:
    return 1.0 / (1.0 + math.exp(-x))


def score_no_show(
    *,
    starts_at: dt.datetime,
    created_at: dt.datetime | None = None,
    prior_no_shows: int = 0,
    prior_completed: int = 0,
    source: str = "front_desk",
) -> NoShowScore:
    now = created_at or dt.datetime.now(dt.UTC)
    if starts_at.tzinfo is None:
        starts_at = starts_at.replace(tzinfo=dt.UTC)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt.UTC)
    lead_hours = max(0.0, (starts_at - now).total_seconds() / 3600.0)
    local = starts_at.astimezone(dt.timezone(dt.timedelta(hours=5, minutes=30)))
    weekday = local.weekday()  # Mon=0
    hour = local.hour

    # Logistic features tuned to typical outpatient priors (~18% base rate).
    logit = -1.55
    if lead_hours < 6:
        logit += 0.15
    elif lead_hours < 24:
        logit += 0.05
    elif lead_hours < 72:
        logit += 0.35
    else:
        logit += 0.75
    logit += min(1.4, 0.45 * prior_no_shows)
    if prior_completed == 0 and prior_no_shows == 0:
        logit += 0.25  # first visit uncertainty
    if weekday >= 5:
        logit += 0.2
    if hour < 10 or hour >= 16:
        logit += 0.15
    if source == "assistant":
        logit -= 0.1  # slightly better confirmation path via chat

    risk = round(float(_sigmoid(logit)), 4)
    if risk >= HIGH_THRESHOLD:
        band = "high"
    elif risk >= MEDIUM_THRESHOLD:
        band = "medium"
    else:
        band = "low"
    return NoShowScore(
        risk=risk,
        band=band,
        waitlist_suggested=band == "high",
        confirm_by_reply=band in {"high", "medium"},
        features={
            "lead_hours": round(lead_hours, 2),
            "prior_no_shows": prior_no_shows,
            "prior_completed": prior_completed,
            "weekday": weekday,
            "hour": hour,
            "source": source,
        },
    )


async def prior_attendance(
    session: AsyncSession, patient_id: Any | None
) -> tuple[int, int]:
    if patient_id is None:
        return 0, 0
    no_shows = await session.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.patient_id == patient_id, Appointment.status == "no_show")
    )
    completed = await session.scalar(
        select(func.count())
        .select_from(Appointment)
        .where(Appointment.patient_id == patient_id, Appointment.status == "completed")
    )
    return int(no_shows or 0), int(completed or 0)


async def apply_no_show_score(
    session: AsyncSession,
    appointment: Appointment,
    *,
    created_at: dt.datetime | None = None,
) -> NoShowScore:
    priors_ns, priors_done = await prior_attendance(session, appointment.patient_id)
    scored = score_no_show(
        starts_at=appointment.starts_at,
        created_at=created_at or appointment.created_at,
        prior_no_shows=priors_ns,
        prior_completed=priors_done,
        source=appointment.source or "front_desk",
    )
    appointment.no_show_risk = scored.risk
    appointment.no_show_band = scored.band
    appointment.waitlist_suggested = scored.waitlist_suggested
    appointment.confirm_by_reply = scored.confirm_by_reply
    # Open a desk claim queue row when high risk and not already claimed/closed.
    if scored.waitlist_suggested and appointment.waitlist_status not in {"claimed", "closed"}:
        appointment.waitlist_status = "open"
    return scored
