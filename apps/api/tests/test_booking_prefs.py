"""Unit tests for chat booking preference parsing (G-39)."""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

from app.agents.booking_prefs import (
    CLINIC_TZ,
    format_slot_label,
    parse_preferred_starts_at,
    rank_slots_near_preference,
)


def test_parse_today_3pm() -> None:
    now = dt.datetime(2026, 11, 1, 10, 0, tzinfo=CLINIC_TZ)
    preferred = parse_preferred_starts_at("book an appointment today at 3 pm for fever", now=now)
    assert preferred is not None
    assert preferred.date() == now.date()
    assert preferred.hour == 15
    assert preferred.minute == 0


def test_parse_tomorrow_morning() -> None:
    now = dt.datetime(2026, 11, 1, 18, 0, tzinfo=CLINIC_TZ)
    preferred = parse_preferred_starts_at("tomorrow 9am cardiology", now=now)
    assert preferred is not None
    assert preferred.date() == now.date() + dt.timedelta(days=1)
    assert preferred.hour == 9


def test_rank_slots_prefers_requested_time() -> None:
    preferred = dt.datetime(2026, 11, 1, 15, 0, tzinfo=CLINIC_TZ)
    slots = [
        {"starts_at": "2026-11-01T09:00:00+05:30", "doctor_name": "A"},
        {"starts_at": "2026-11-01T15:00:00+05:30", "doctor_name": "B"},
        {"starts_at": "2026-11-01T16:30:00+05:30", "doctor_name": "C"},
    ]
    ranked = rank_slots_near_preference(slots, preferred, limit=2)
    assert ranked[0]["doctor_name"] == "B"
    assert ranked[1]["doctor_name"] == "C"


def test_format_slot_label_today() -> None:
    now = dt.datetime(2026, 11, 1, 10, 0, tzinfo=CLINIC_TZ)
    starts = dt.datetime(2026, 11, 1, 15, 0, tzinfo=CLINIC_TZ)
    label = format_slot_label(
        doctor_name="Dr Rao", clinic_code="BANER", starts_at=starts, now=now
    )
    assert "Dr Rao" in label
    assert "BANER" in label
    assert "Today" in label
    assert "3:00" in label or "03:00" in label
