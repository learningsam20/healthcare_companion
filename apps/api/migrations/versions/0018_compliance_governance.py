"""Compliance attestations + governance settings (G-12/G-19/G-15/G-16/G-28).

Revision ID: 0018_compliance_governance
Revises: 0017_nursing_summaries
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0018_compliance_governance"
down_revision: str | None = "0017_nursing_summaries"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "compliance_attestations" not in tables:
        op.create_table(
            "compliance_attestations",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("kind", sa.String(40), nullable=False),
            sa.Column("status", sa.String(20), server_default="not_attested", nullable=False),
            sa.Column("approver_name", sa.String(200), nullable=True),
            sa.Column("approver_role", sa.String(120), nullable=True),
            sa.Column("attested_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("attestation_text", sa.Text(), nullable=True),
            sa.Column("report_object_key", sa.String(500), nullable=True),
            sa.Column("report_sha256", sa.String(64), nullable=True),
            sa.Column("report_filename", sa.String(260), nullable=True),
            sa.Column("report_content_type", sa.String(120), nullable=True),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("updated_by", sa.String(200), nullable=True),
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
            sa.UniqueConstraint("kind", name="uq_compliance_attestations_kind"),
            sa.CheckConstraint(
                "kind IN ('clinical_validation','dpdp_audit')",
                name="ck_compliance_attestations_kind",
            ),
            sa.CheckConstraint(
                "status IN ('not_attested','pending','attested','disapproved','revoked')",
                name="ck_compliance_attestations_status",
            ),
        )
    if "governance_settings" not in tables:
        op.create_table(
            "governance_settings",
            sa.Column("key", sa.String(80), primary_key=True, nullable=False),
            sa.Column(
                "value",
                postgresql.JSONB(),
                server_default=sa.text("'{}'::jsonb"),
                nullable=False,
            ),
            sa.Column("updated_by", sa.String(200), nullable=True),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )


def downgrade() -> None:
    op.drop_table("governance_settings")
    op.drop_table("compliance_attestations")
