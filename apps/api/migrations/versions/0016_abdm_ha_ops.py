"""Add opaque patient external identifiers for the ABDM readiness seam.

Revision ID: 0016_abdm_ha_ops
Revises: 0015_handoffs_incidents_ops
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0016_abdm_ha_ops"
down_revision: str | None = "0015_handoffs_incidents_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "patient_external_ids" not in tables:
        op.create_table(
            "patient_external_ids",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "patient_id",
                sa.Uuid(),
                sa.ForeignKey("patients.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("system", sa.String(40), nullable=False),
            sa.Column("value_enc", sa.String(96), nullable=False),
            sa.Column("purpose", sa.String(100), nullable=False),
            sa.Column("status", sa.String(20), server_default="linked", nullable=False),
            sa.Column("created_by", sa.String(200), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint(
                "status IN ('linked','unlinked','pending')",
                name="ck_patient_external_ids_status",
            ),
            sa.UniqueConstraint(
                "patient_id",
                "system",
                name="uq_patient_external_ids_patient_system",
            ),
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "patient_external_ids" in tables:
        op.drop_table("patient_external_ids")
