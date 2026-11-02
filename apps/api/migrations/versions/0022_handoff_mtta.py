"""Handoff MTTA: acknowledged_at + mtta_seconds.

Revision ID: 0022_handoff_mtta
Revises: 0021_wave_f_titles_sla_safety
Create Date: 2026-11-01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022_handoff_mtta"
down_revision: str | None = "0021_wave_f_titles_sla_safety"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("handoffs")}
    if "acknowledged_at" not in cols:
        op.add_column(
            "handoffs",
            sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        )
    if "mtta_seconds" not in cols:
        op.add_column(
            "handoffs",
            sa.Column("mtta_seconds", sa.Integer(), nullable=True),
        )
    op.create_index(
        "ix_handoffs_acknowledged_at",
        "handoffs",
        ["acknowledged_at"],
        unique=False,
        if_not_exists=True,
    )


def downgrade() -> None:
    op.drop_index("ix_handoffs_acknowledged_at", table_name="handoffs", if_exists=True)
    bind = op.get_bind()
    cols = {c["name"] for c in sa.inspect(bind).get_columns("handoffs")}
    if "mtta_seconds" in cols:
        op.drop_column("handoffs", "mtta_seconds")
    if "acknowledged_at" in cols:
        op.drop_column("handoffs", "acknowledged_at")
