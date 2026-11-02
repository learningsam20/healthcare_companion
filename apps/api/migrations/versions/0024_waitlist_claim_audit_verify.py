"""Waitlist claim queue columns + indexes for desk fill workflow.

Revision ID: 0024_waitlist_claim_audit_verify
Revises: 0023_w1_w3_innovations
Create Date: 2026-11-02
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0024_waitlist_claim_audit_verify"
down_revision: str | None = "0023_w1_w3_innovations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _has_index(inspector: sa.Inspector, table: str, name: str) -> bool:
    return any(ix["name"] == name for ix in inspector.get_indexes(table))


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    cols = {c["name"] for c in inspector.get_columns("appointments")}

    if "waitlist_status" not in cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_status", sa.String(length=20), nullable=True),
        )
    if "waitlist_owner_subject" not in cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_owner_subject", sa.String(length=200), nullable=True),
        )
    if "waitlist_claimed_at" not in cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_claimed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "waitlist_closed_at" not in cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_closed_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "waitlist_resolution" not in cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_resolution", sa.String(length=40), nullable=True),
        )
    if "waitlist_notes" not in cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_notes", sa.String(length=500), nullable=True),
        )
    if "waitlist_offer_patient_id" not in cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_offer_patient_id", sa.Uuid(), nullable=True),
        )
    if "waitlist_offer_appointment_id" not in cols:
        op.add_column(
            "appointments",
            sa.Column("waitlist_offer_appointment_id", sa.Uuid(), nullable=True),
        )

    inspector = sa.inspect(bind)
    if not _has_index(inspector, "appointments", "ix_appointments_waitlist_status"):
        op.create_index(
            "ix_appointments_waitlist_status",
            "appointments",
            ["waitlist_status"],
        )

    # Backfill open queue rows for existing high-risk suggestions.
    op.execute(
        sa.text(
            "UPDATE appointments SET waitlist_status = 'open' "
            "WHERE waitlist_suggested IS TRUE "
            "AND waitlist_status IS NULL "
            "AND status IN ('held', 'confirmed')"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if _has_index(inspector, "appointments", "ix_appointments_waitlist_status"):
        op.drop_index("ix_appointments_waitlist_status", table_name="appointments")
    cols = {c["name"] for c in inspector.get_columns("appointments")}
    for name in (
        "waitlist_offer_appointment_id",
        "waitlist_offer_patient_id",
        "waitlist_notes",
        "waitlist_resolution",
        "waitlist_closed_at",
        "waitlist_claimed_at",
        "waitlist_owner_subject",
        "waitlist_status",
    ):
        if name in cols:
            op.drop_column("appointments", name)
