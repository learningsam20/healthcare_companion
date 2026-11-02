"""Booking idempotency + active slot uniqueness (G-43 / FR-W1-11/12).

Revision ID: 0019_booking_idempotency
Revises: 0018_compliance_governance
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0019_booking_idempotency"
down_revision: str | None = "0018_compliance_governance"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "booking_idempotency" not in tables:
        op.create_table(
            "booking_idempotency",
            sa.Column("scope", sa.String(120), primary_key=True, nullable=False),
            sa.Column("key", sa.String(80), primary_key=True, nullable=False),
            sa.Column(
                "appointment_id",
                sa.Uuid(),
                sa.ForeignKey("appointments.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_booking_idempotency_appointment",
            "booking_idempotency",
            ["appointment_id"],
        )

    # One active (held/confirmed) appointment per doctor+clinic+starts_at.
    op.execute(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS uq_appointments_active_slot
        ON appointments (doctor_name, clinic_code, starts_at)
        WHERE status IN ('held', 'confirmed')
        """
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS uq_appointments_active_slot")
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "booking_idempotency" in tables:
        op.drop_index("ix_booking_idempotency_appointment", table_name="booking_idempotency")
        op.drop_table("booking_idempotency")
