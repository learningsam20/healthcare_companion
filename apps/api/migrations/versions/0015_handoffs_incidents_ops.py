"""Add handoffs, safety incidents, contact verification, and FinOps operations.

Revision ID: 0015_handoffs_incidents_ops
Revises: 0014_chat_feedback_trgm
Create Date: 2026-10-31
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0015_handoffs_incidents_ops"
down_revision: str | None = "0014_chat_feedback_trgm"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "handoffs" not in tables:
        op.create_table(
            "handoffs",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "patient_id",
                sa.Uuid(),
                sa.ForeignKey("patients.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("created_by_subject", sa.String(200), nullable=False),
            sa.Column("assigned_to_subject", sa.String(200), nullable=True),
            sa.Column("clinic_code", sa.String(40), nullable=False),
            sa.Column("reason", sa.String(500), nullable=False),
            sa.Column("status", sa.String(20), server_default="open", nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("resource_type", sa.String(40), nullable=True),
            sa.Column("resource_id", sa.String(200), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "status IN ('open','assigned','resolved')", name="ck_handoffs_status"
            ),
        )
        op.create_index("ix_handoffs_status_created", "handoffs", ["status", "created_at"])
        op.create_index("ix_handoffs_clinic_status", "handoffs", ["clinic_code", "status"])
        op.create_index("ix_handoffs_patient_created", "handoffs", ["patient_id", "created_at"])

    if "safety_incidents" not in tables:
        op.create_table(
            "safety_incidents",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "patient_id",
                sa.Uuid(),
                sa.ForeignKey("patients.id", ondelete="SET NULL"),
                nullable=True,
            ),
            sa.Column("reported_by_subject", sa.String(200), nullable=False),
            sa.Column("severity", sa.String(20), nullable=False),
            sa.Column("category", sa.String(80), nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("detail", sa.Text(), nullable=False),
            sa.Column("status", sa.String(20), server_default="open", nullable=False),
            sa.Column("linked_resource_type", sa.String(40), nullable=True),
            sa.Column("linked_resource_id", sa.String(200), nullable=True),
            sa.Column("resolution", sa.Text(), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
            sa.CheckConstraint(
                "severity IN ('low','medium','high','critical')",
                name="ck_safety_incidents_severity",
            ),
            sa.CheckConstraint(
                "status IN ('open','investigating','closed')",
                name="ck_safety_incidents_status",
            ),
        )
        op.create_index(
            "ix_safety_incidents_status_created",
            "safety_incidents",
            ["status", "created_at"],
        )
        op.create_index(
            "ix_safety_incidents_severity_status",
            "safety_incidents",
            ["severity", "status"],
        )
        op.create_index(
            "ix_safety_incidents_patient_created",
            "safety_incidents",
            ["patient_id", "created_at"],
        )

    if "contact_verification_codes" not in tables:
        op.create_table(
            "contact_verification_codes",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column(
                "contact_id",
                sa.Uuid(),
                sa.ForeignKey("contact_channels.id", ondelete="CASCADE"),
                nullable=False,
            ),
            sa.Column("code_hash", sa.String(64), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
            sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
        )
        op.create_index(
            "ix_contact_verification_codes_contact_created",
            "contact_verification_codes",
            ["contact_id", "created_at"],
        )

    if "finops_budgets" not in tables:
        op.create_table(
            "finops_budgets",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("scope_type", sa.String(40), nullable=False),
            sa.Column("scope_id", sa.String(200), nullable=False),
            sa.Column("period", sa.String(7), nullable=False),
            sa.Column("limit_usd", sa.Float(), nullable=False),
            sa.Column("alert_pct", sa.Float(), server_default="80", nullable=False),
            sa.Column("hard_stop", sa.Boolean(), server_default=sa.false(), nullable=False),
            sa.Column("owner", sa.String(200), nullable=False),
            sa.Column("created_by", sa.String(200), nullable=False),
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint("limit_usd >= 0", name="ck_finops_budgets_limit_usd"),
            sa.CheckConstraint(
                "alert_pct >= 0 AND alert_pct <= 100",
                name="ck_finops_budgets_alert_pct",
            ),
            sa.UniqueConstraint(
                "scope_type",
                "scope_id",
                "period",
                name="uq_finops_budgets_scope_period",
            ),
        )
        op.create_index("ix_finops_budgets_period", "finops_budgets", ["period"])

    if "finops_savings" not in tables:
        op.create_table(
            "finops_savings",
            sa.Column("id", sa.Uuid(), primary_key=True, nullable=False),
            sa.Column("title", sa.String(200), nullable=False),
            sa.Column("amount_usd", sa.Float(), nullable=False),
            sa.Column("period_month", sa.String(7), nullable=False),
            sa.Column("notes", sa.Text(), nullable=True),
            sa.Column("created_by", sa.String(200), nullable=False),
            sa.Column(
                "created_at",
                sa.DateTime(timezone=True),
                server_default=sa.text("now()"),
                nullable=False,
            ),
            sa.CheckConstraint("amount_usd >= 0", name="ck_finops_savings_amount_usd"),
        )
        op.create_index("ix_finops_savings_period", "finops_savings", ["period_month"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (
        "finops_savings",
        "finops_budgets",
        "contact_verification_codes",
        "safety_incidents",
        "handoffs",
    ):
        if table in tables:
            op.drop_table(table)
