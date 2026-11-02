"""Appointment booking source attribution (G-48).

Revision ID: 0020_appointment_source
Revises: 0019_booking_idempotency
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020_appointment_source"
down_revision: str | None = "0019_booking_idempotency"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("appointments")}
    if "source" not in cols:
        op.add_column(
            "appointments",
            sa.Column("source", sa.String(40), server_default="front_desk", nullable=False),
        )
        op.create_index("ix_appointments_source", "appointments", ["source"])
    op.execute(
        """
        DO $$ BEGIN
          ALTER TABLE appointments
            ADD CONSTRAINT ck_appointments_source
            CHECK (source IN ('assistant', 'front_desk'));
        EXCEPTION WHEN duplicate_object THEN NULL;
        END $$;
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE appointments DROP CONSTRAINT IF EXISTS ck_appointments_source")
    op.drop_index("ix_appointments_source", table_name="appointments")
    op.drop_column("appointments", "source")
