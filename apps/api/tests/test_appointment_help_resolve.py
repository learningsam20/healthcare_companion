"""Appointment help ordinal / doctor name resolution (G-45)."""

from __future__ import annotations

import datetime as dt
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from app.agents.appointment_help_graph import _resolve_appointment

TZ = ZoneInfo("Asia/Kolkata")


def _row(name: str, minutes: int = 60) -> SimpleNamespace:
    return SimpleNamespace(
        id=f"00000000-0000-4000-8000-00000000000{minutes % 9}",
        doctor_name=name,
        clinic_code="BANER",
        status="confirmed",
        starts_at=dt.datetime.now(TZ) + dt.timedelta(minutes=minutes),
    )


def test_resolve_by_ordinal() -> None:
    rows = [_row("Dr Rao", 60), _row("Dr Mehta", 120)]
    assert _resolve_appointment("cancel 2", rows).doctor_name == "Dr Mehta"
    assert _resolve_appointment("please cancel the first one", rows).doctor_name == "Dr Rao"


def test_resolve_by_doctor_name() -> None:
    rows = [_row("Dr Priya Rao", 60), _row("Dr Mehta", 120)]
    assert _resolve_appointment("cancel rao", rows).doctor_name == "Dr Priya Rao"


def test_resolve_by_uuid() -> None:
    rows = [_row("Dr Rao", 60)]
    rows[0].id = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
    assert (
        _resolve_appointment("cancel aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee", rows).id
        == rows[0].id
    )
