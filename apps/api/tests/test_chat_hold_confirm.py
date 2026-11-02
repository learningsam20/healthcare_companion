"""G-45 residual: soft-hold response shape + public confirm endpoint contract."""

from __future__ import annotations

import datetime as dt
import uuid

from app.modules.chat.schemas import HeldAppointmentOut, SendResult
from app.modules.chat.schemas import MessageOut


def test_held_appointment_out_includes_hold_expiry() -> None:
    now = dt.datetime.now(dt.UTC)
    held = HeldAppointmentOut(
        id=uuid.uuid4(),
        doctor_name="Dr. Ananya Rao",
        clinic_code="BANER",
        specialty_code="GM",
        starts_at=now + dt.timedelta(hours=2),
        duration_minutes=20,
        status="held",
        source="assistant",
        hold_expires_at=now + dt.timedelta(seconds=120),
    )
    assert held.status == "held"
    assert held.hold_expires_at > held.starts_at - dt.timedelta(days=1)
    payload = held.model_dump(mode="json")
    assert "hold_expires_at" in payload


def test_send_result_can_carry_held_appointment() -> None:
    now = dt.datetime.now(dt.UTC)
    msg = MessageOut(
        id=uuid.uuid4(),
        role="assistant",
        content="Held slot",
        language="en-IN",
        sources=[],
        safety={},
        trace_id=None,
        model_alias=None,
        created_at=now,
    )
    held = HeldAppointmentOut(
        id=uuid.uuid4(),
        doctor_name="Dr. Ananya Rao",
        clinic_code="BANER",
        specialty_code="GM",
        starts_at=now + dt.timedelta(hours=2),
        duration_minutes=20,
        status="held",
        source="assistant",
        hold_expires_at=now + dt.timedelta(seconds=120),
    )
    result = SendResult(
        user_message=msg,
        assistant_message=msg,
        appointment=held,
    )
    assert result.appointment is not None
    assert result.appointment.status == "held"
