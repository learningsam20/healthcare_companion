"""X-01 nursing summary drafts with accept/edit/reject versioning.

Revision ID: 0017_nursing_summaries
Revises: 0016_abdm_ha_ops
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0017_nursing_summaries"
down_revision: str | None = "0016_abdm_ha_ops"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "nursing_summaries" not in tables:
        op.create_table(
            "nursing_summaries",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "patient_id",
                sa.Uuid(),
                sa.ForeignKey("patients.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("version", sa.Integer(), server_default="1", nullable=False),
            sa.Column("status", sa.String(20), server_default="draft", nullable=False),
            sa.Column("summary", sa.Text(), nullable=False),
            sa.Column("sources", postgresql.JSONB(), server_default="[]", nullable=False),
            sa.Column("graph", sa.String(80), server_default="x01_nursing.v1", nullable=False),
            sa.Column("model_alias", sa.String(80), nullable=True),
            sa.Column("created_by", sa.String(200), nullable=False),
            sa.Column("decided_by", sa.String(200), nullable=True),
            sa.Column("decided_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("decision_note", sa.String(500), nullable=True),
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
                "status IN ('draft','accepted','edited','rejected')",
                name="ck_nursing_summaries_status",
            ),
            sa.UniqueConstraint(
                "patient_id",
                "version",
                name="uq_nursing_summaries_patient_version",
            ),
        )
        op.create_index(
            "ix_nursing_summaries_patient_status",
            "nursing_summaries",
            ["patient_id", "status"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "nursing_summaries" in tables:
        op.drop_index("ix_nursing_summaries_patient_status", table_name="nursing_summaries")
        op.drop_table("nursing_summaries")
